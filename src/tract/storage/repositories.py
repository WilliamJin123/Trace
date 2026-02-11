"""Abstract repository interfaces for Trace storage.

Defines ABC interfaces for all database operations. No SQLAlchemy
imports here -- pure abstract contracts.

Concrete implementations are in sqlite.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from tract.storage.schema import AnnotationRow, BlobRow, CommitRow


class CommitRepository(ABC):
    """Abstract interface for commit storage operations."""

    @abstractmethod
    def get(self, commit_hash: str) -> CommitRow | None:
        """Get a commit by its hash. Returns None if not found."""
        ...

    @abstractmethod
    def save(self, commit: CommitRow) -> None:
        """Save a commit to storage."""
        ...

    @abstractmethod
    def get_ancestors(self, commit_hash: str, limit: int | None = None) -> Sequence[CommitRow]:
        """Get ancestor chain from commit to root (inclusive).

        Returns commits in reverse chronological order (newest first).
        """
        ...

    @abstractmethod
    def get_by_type(self, content_type: str, repo_id: str) -> Sequence[CommitRow]:
        """Get all commits of a given content type in a repo."""
        ...

    @abstractmethod
    def get_children(self, commit_hash: str) -> Sequence[CommitRow]:
        """Get all commits whose parent_hash is the given hash."""
        ...


class BlobRepository(ABC):
    """Abstract interface for blob storage operations."""

    @abstractmethod
    def get(self, content_hash: str) -> BlobRow | None:
        """Get a blob by its content hash. Returns None if not found."""
        ...

    @abstractmethod
    def save_if_absent(self, blob: BlobRow) -> None:
        """Store a blob only if its content_hash is not already present.

        Content-addressable: same content = same hash = stored once.
        """
        ...


class RefRepository(ABC):
    """Abstract interface for ref (branch/HEAD pointer) operations."""

    @abstractmethod
    def get_head(self, repo_id: str) -> str | None:
        """Get the HEAD commit hash for a repo. Returns None if no HEAD."""
        ...

    @abstractmethod
    def update_head(self, repo_id: str, commit_hash: str) -> None:
        """Update the HEAD pointer for a repo."""
        ...

    @abstractmethod
    def get_branch(self, repo_id: str, branch_name: str) -> str | None:
        """Get the commit hash for a named branch. Returns None if not found."""
        ...

    @abstractmethod
    def set_branch(self, repo_id: str, branch_name: str, commit_hash: str) -> None:
        """Set or update a named branch to point at a commit."""
        ...

    @abstractmethod
    def list_branches(self, repo_id: str) -> list[str]:
        """List all branch names for a repo."""
        ...


class AnnotationRepository(ABC):
    """Abstract interface for priority annotation operations."""

    @abstractmethod
    def get_latest(self, target_hash: str) -> AnnotationRow | None:
        """Get the most recent annotation for a commit. Returns None if none."""
        ...

    @abstractmethod
    def save(self, annotation: AnnotationRow) -> None:
        """Save an annotation (append-only)."""
        ...

    @abstractmethod
    def get_history(self, target_hash: str) -> Sequence[AnnotationRow]:
        """Get all annotations for a commit, ordered by created_at ascending."""
        ...

    @abstractmethod
    def batch_get_latest(self, target_hashes: list[str]) -> dict[str, AnnotationRow]:
        """Get the latest annotation for each of multiple commits.

        Returns a dict mapping target_hash to the latest AnnotationRow.
        Commits with no annotations are omitted from the result.

        This avoids N+1 queries during compilation.
        """
        ...
