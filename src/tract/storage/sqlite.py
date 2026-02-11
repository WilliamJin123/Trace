"""SQLite implementations of repository interfaces.

All repositories use SQLAlchemy 2.0-style queries (select() + session.execute()).
Each repository takes a Session in its constructor.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tract.storage.repositories import (
    AnnotationRepository,
    BlobRepository,
    CommitRepository,
    RefRepository,
)
from tract.storage.schema import (
    AnnotationRow,
    BlobRow,
    CommitRow,
    RefRow,
)


class SqliteBlobRepository(BlobRepository):
    """SQLite implementation of blob repository.

    Content-addressable: save_if_absent checks existence before insert.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, content_hash: str) -> BlobRow | None:
        stmt = select(BlobRow).where(BlobRow.content_hash == content_hash)
        return self._session.execute(stmt).scalar_one_or_none()

    def save_if_absent(self, blob: BlobRow) -> None:
        """Store blob only if content_hash not already present (dedup)."""
        existing = self.get(blob.content_hash)
        if existing is None:
            self._session.add(blob)
            self._session.flush()


class SqliteCommitRepository(CommitRepository):
    """SQLite implementation of commit repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, commit_hash: str) -> CommitRow | None:
        stmt = select(CommitRow).where(CommitRow.commit_hash == commit_hash)
        return self._session.execute(stmt).scalar_one_or_none()

    def save(self, commit: CommitRow) -> None:
        self._session.add(commit)
        self._session.flush()

    def get_ancestors(self, commit_hash: str, limit: int | None = None) -> Sequence[CommitRow]:
        """Walk parent chain from commit to root.

        Returns commits in reverse chronological order (newest first).
        """
        ancestors: list[CommitRow] = []
        current_hash: str | None = commit_hash

        while current_hash is not None:
            if limit is not None and len(ancestors) >= limit:
                break
            commit = self.get(current_hash)
            if commit is None:
                break
            ancestors.append(commit)
            current_hash = commit.parent_hash

        return ancestors

    def get_by_type(self, content_type: str, tract_id: str) -> Sequence[CommitRow]:
        stmt = (
            select(CommitRow)
            .where(CommitRow.tract_id == tract_id, CommitRow.content_type == content_type)
            .order_by(CommitRow.created_at)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_children(self, commit_hash: str) -> Sequence[CommitRow]:
        stmt = select(CommitRow).where(CommitRow.parent_hash == commit_hash)
        return list(self._session.execute(stmt).scalars().all())

    def get_by_config(
        self, tract_id: str, json_path: str, operator: str, value: object
    ) -> Sequence[CommitRow]:
        extracted = func.json_extract(
            CommitRow.generation_config_json, f'$.{json_path}'
        )
        ops = {
            "=": lambda e, v: e == v,
            "!=": lambda e, v: e != v,
            ">": lambda e, v: e > v,
            "<": lambda e, v: e < v,
            ">=": lambda e, v: e >= v,
            "<=": lambda e, v: e <= v,
        }
        if operator not in ops:
            raise ValueError(f"Unsupported operator: {operator}. Use one of: {list(ops.keys())}")
        condition = ops[operator](extracted, value)
        stmt = (
            select(CommitRow)
            .where(CommitRow.tract_id == tract_id, condition)
            .order_by(CommitRow.created_at)
        )
        return list(self._session.execute(stmt).scalars().all())


class SqliteRefRepository(RefRepository):
    """SQLite implementation of ref repository.

    HEAD is stored as ref_name="HEAD".
    Branches are stored as ref_name="refs/heads/{name}".
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_head(self, tract_id: str) -> str | None:
        stmt = select(RefRow).where(
            RefRow.tract_id == tract_id, RefRow.ref_name == "HEAD"
        )
        ref = self._session.execute(stmt).scalar_one_or_none()
        return ref.commit_hash if ref else None

    def update_head(self, tract_id: str, commit_hash: str) -> None:
        stmt = select(RefRow).where(
            RefRow.tract_id == tract_id, RefRow.ref_name == "HEAD"
        )
        ref = self._session.execute(stmt).scalar_one_or_none()
        if ref is None:
            self._session.add(
                RefRow(tract_id=tract_id, ref_name="HEAD", commit_hash=commit_hash)
            )
        else:
            ref.commit_hash = commit_hash
        self._session.flush()

    def get_branch(self, tract_id: str, branch_name: str) -> str | None:
        ref_name = f"refs/heads/{branch_name}"
        stmt = select(RefRow).where(
            RefRow.tract_id == tract_id, RefRow.ref_name == ref_name
        )
        ref = self._session.execute(stmt).scalar_one_or_none()
        return ref.commit_hash if ref else None

    def set_branch(self, tract_id: str, branch_name: str, commit_hash: str) -> None:
        ref_name = f"refs/heads/{branch_name}"
        stmt = select(RefRow).where(
            RefRow.tract_id == tract_id, RefRow.ref_name == ref_name
        )
        ref = self._session.execute(stmt).scalar_one_or_none()
        if ref is None:
            self._session.add(
                RefRow(tract_id=tract_id, ref_name=ref_name, commit_hash=commit_hash)
            )
        else:
            ref.commit_hash = commit_hash
        self._session.flush()

    def list_branches(self, tract_id: str) -> list[str]:
        prefix = "refs/heads/"
        stmt = select(RefRow).where(
            RefRow.tract_id == tract_id,
            RefRow.ref_name.startswith(prefix),
        )
        refs = self._session.execute(stmt).scalars().all()
        return [ref.ref_name[len(prefix):] for ref in refs]


class SqliteAnnotationRepository(AnnotationRepository):
    """SQLite implementation of annotation repository.

    Annotations are append-only. The latest annotation for a given
    target_hash (by created_at) is the current priority.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_latest(self, target_hash: str) -> AnnotationRow | None:
        stmt = (
            select(AnnotationRow)
            .where(AnnotationRow.target_hash == target_hash)
            .order_by(AnnotationRow.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def save(self, annotation: AnnotationRow) -> None:
        self._session.add(annotation)
        self._session.flush()

    def get_history(self, target_hash: str) -> Sequence[AnnotationRow]:
        stmt = (
            select(AnnotationRow)
            .where(AnnotationRow.target_hash == target_hash)
            .order_by(AnnotationRow.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def batch_get_latest(self, target_hashes: list[str]) -> dict[str, AnnotationRow]:
        """Get latest annotation per target using a single query with subquery."""
        if not target_hashes:
            return {}

        # Subquery: max created_at per target_hash
        max_time_subq = (
            select(
                AnnotationRow.target_hash,
                func.max(AnnotationRow.created_at).label("max_created_at"),
            )
            .where(AnnotationRow.target_hash.in_(target_hashes))
            .group_by(AnnotationRow.target_hash)
            .subquery()
        )

        # Join to get full rows
        stmt = (
            select(AnnotationRow)
            .join(
                max_time_subq,
                (AnnotationRow.target_hash == max_time_subq.c.target_hash)
                & (AnnotationRow.created_at == max_time_subq.c.max_created_at),
            )
        )

        rows = self._session.execute(stmt).scalars().all()
        return {row.target_hash: row for row in rows}
