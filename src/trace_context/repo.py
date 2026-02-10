"""Repo -- the public SDK entry point for Trace.

Ties together storage, commit engine, and context compiler into a clean,
user-facing API.  Users interact with ``Repo.open()``, ``repo.commit()``,
``repo.compile()``, etc.

Not thread-safe in v1.  Each thread should open its own ``Repo``.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from trace_context.engine.commit import CommitEngine
from trace_context.engine.compiler import DefaultContextCompiler
from trace_context.engine.tokens import TiktokenCounter
from trace_context.models.annotations import Priority, PriorityAnnotation
from trace_context.models.commit import CommitInfo, CommitOperation
from trace_context.models.config import RepoConfig
from trace_context.models.content import validate_content
from trace_context.protocols import CompiledContext, ContextCompiler, TokenCounter
from trace_context.storage.engine import create_session_factory, create_trace_engine, init_db
from trace_context.storage.sqlite import (
    SqliteAnnotationRepository,
    SqliteBlobRepository,
    SqliteCommitRepository,
    SqliteRefRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session


class Repo:
    """Primary entry point for Trace -- git-like version control for LLM context.

    Create a repo via :meth:`Repo.open` (recommended) or
    :meth:`Repo.from_components` (testing / DI).

    Example::

        with Repo.open() as repo:
            repo.commit(InstructionContent(text="You are helpful."))
            repo.commit(DialogueContent(role="user", text="Hi"))
            result = repo.compile()
            print(result.messages)
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        engine: Engine | None,
        session: Session,
        commit_engine: CommitEngine,
        compiler: ContextCompiler,
        repo_id: str,
        config: RepoConfig,
        commit_repo: SqliteCommitRepository,
        blob_repo: SqliteBlobRepository,
        ref_repo: SqliteRefRepository,
        annotation_repo: SqliteAnnotationRepository,
        token_counter: TokenCounter,
    ) -> None:
        self._engine = engine
        self._session = session
        self._commit_engine = commit_engine
        self._compiler = compiler
        self._repo_id = repo_id
        self._config = config
        self._commit_repo = commit_repo
        self._blob_repo = blob_repo
        self._ref_repo = ref_repo
        self._annotation_repo = annotation_repo
        self._token_counter = token_counter
        self._custom_type_registry: dict[str, type[BaseModel]] = {}
        self._compile_cache: dict[str, CompiledContext] = {}
        self._closed = False

    @classmethod
    def open(
        cls,
        path: str = ":memory:",
        *,
        repo_id: str | None = None,
        config: RepoConfig | None = None,
        tokenizer: TokenCounter | None = None,
        compiler: ContextCompiler | None = None,
    ) -> Repo:
        """Open (or create) a Trace repository.

        Args:
            path: SQLite path.  ``":memory:"`` for in-memory (default).
            repo_id: Unique repo identifier.  Generated if not provided.
            config: Repository configuration.  Defaults created if *None*.
            tokenizer: Pluggable token counter.  TiktokenCounter by default.
            compiler: Pluggable context compiler.  DefaultContextCompiler by default.

        Returns:
            A ready-to-use ``Repo`` instance.
        """
        if repo_id is None:
            repo_id = uuid.uuid4().hex

        if config is None:
            config = RepoConfig(db_path=path)

        # Engine / session
        engine = create_trace_engine(path)
        init_db(engine)
        session_factory = create_session_factory(engine)
        session = session_factory()

        # Repositories
        commit_repo = SqliteCommitRepository(session)
        blob_repo = SqliteBlobRepository(session)
        ref_repo = SqliteRefRepository(session)
        annotation_repo = SqliteAnnotationRepository(session)

        # Token counter
        token_counter = tokenizer or TiktokenCounter(
            encoding_name=config.tokenizer_encoding,
        )

        # Commit engine
        commit_engine = CommitEngine(
            commit_repo=commit_repo,
            blob_repo=blob_repo,
            ref_repo=ref_repo,
            annotation_repo=annotation_repo,
            token_counter=token_counter,
            repo_id=repo_id,
            token_budget=config.token_budget,
        )

        # Context compiler
        ctx_compiler: ContextCompiler = compiler or DefaultContextCompiler(
            commit_repo=commit_repo,
            blob_repo=blob_repo,
            annotation_repo=annotation_repo,
            token_counter=token_counter,
        )

        # Ensure "main" branch ref exists (idempotent)
        head = ref_repo.get_head(repo_id)
        if head is None:
            # No HEAD yet -- that is fine, first commit will set it.
            pass

        return cls(
            engine=engine,
            session=session,
            commit_engine=commit_engine,
            compiler=ctx_compiler,
            repo_id=repo_id,
            config=config,
            commit_repo=commit_repo,
            blob_repo=blob_repo,
            ref_repo=ref_repo,
            annotation_repo=annotation_repo,
            token_counter=token_counter,
        )

    @classmethod
    def from_components(
        cls,
        *,
        engine: Engine | None = None,
        session: Session,
        commit_repo: SqliteCommitRepository,
        blob_repo: SqliteBlobRepository,
        ref_repo: SqliteRefRepository,
        annotation_repo: SqliteAnnotationRepository,
        token_counter: TokenCounter,
        compiler: ContextCompiler,
        repo_id: str,
        config: RepoConfig | None = None,
    ) -> Repo:
        """Create a ``Repo`` from pre-built components.

        Skips engine/session creation.  Useful for testing and DI.
        """
        if config is None:
            config = RepoConfig()

        commit_engine = CommitEngine(
            commit_repo=commit_repo,
            blob_repo=blob_repo,
            ref_repo=ref_repo,
            annotation_repo=annotation_repo,
            token_counter=token_counter,
            repo_id=repo_id,
            token_budget=config.token_budget,
        )

        return cls(
            engine=engine,
            session=session,
            commit_engine=commit_engine,
            compiler=compiler,
            repo_id=repo_id,
            config=config,
            commit_repo=commit_repo,
            blob_repo=blob_repo,
            ref_repo=ref_repo,
            annotation_repo=annotation_repo,
            token_counter=token_counter,
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def repo_id(self) -> str:
        """The repository identifier."""
        return self._repo_id

    @property
    def head(self) -> str | None:
        """Current HEAD commit hash, or *None* if no commits yet."""
        return self._ref_repo.get_head(self._repo_id)

    @property
    def config(self) -> RepoConfig:
        """The repository configuration."""
        return self._config

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def commit(
        self,
        content: BaseModel | dict,
        *,
        operation: CommitOperation = CommitOperation.APPEND,
        message: str | None = None,
        reply_to: str | None = None,
        metadata: dict | None = None,
    ) -> CommitInfo:
        """Create a new commit.

        Args:
            content: A Pydantic content model *or* a dict (auto-validated).
            operation: ``APPEND`` (default) or ``EDIT``.
            message: Optional human-readable message.
            reply_to: For ``EDIT``, the hash of the commit being replaced.
            metadata: Optional arbitrary metadata.

        Returns:
            :class:`CommitInfo` for the new commit.
        """
        # Auto-validate dicts through the content type system
        if isinstance(content, dict):
            content = validate_content(content, custom_registry=self._custom_type_registry)

        info = self._commit_engine.create_commit(
            content=content,
            operation=operation,
            message=message,
            reply_to=reply_to,
            metadata=metadata,
        )

        # Persist to database
        self._session.commit()

        # Invalidate compile cache (head changed)
        self._compile_cache.clear()

        return info

    def compile(
        self,
        *,
        as_of: datetime | None = None,
        up_to: str | None = None,
        include_edit_annotations: bool = False,
    ) -> CompiledContext:
        """Compile the current context into LLM-ready messages.

        Args:
            as_of: Only include commits at or before this datetime.
            up_to: Only include commits up to this hash.
            include_edit_annotations: Append ``[edited]`` markers.

        Returns:
            :class:`CompiledContext` with messages and token counts.
        """
        current_head = self.head
        if current_head is None:
            return CompiledContext(messages=[], token_count=0, commit_count=0, token_source="")

        # Cache hit (only for unfiltered queries)
        if as_of is None and up_to is None and current_head in self._compile_cache:
            return self._compile_cache[current_head]

        result = self._compiler.compile(
            self._repo_id,
            current_head,
            as_of=as_of,
            up_to=up_to,
            include_edit_annotations=include_edit_annotations,
        )

        # Cache unfiltered results
        if as_of is None and up_to is None:
            self._compile_cache[current_head] = result

        return result

    def get_commit(self, commit_hash: str) -> CommitInfo | None:
        """Fetch a commit by its hash.

        Returns:
            :class:`CommitInfo` if found, *None* otherwise.
        """
        return self._commit_engine.get_commit(commit_hash)

    def annotate(
        self,
        target_hash: str,
        priority: Priority,
        *,
        reason: str | None = None,
    ) -> PriorityAnnotation:
        """Create a priority annotation on a commit.

        Args:
            target_hash: Hash of the commit to annotate.
            priority: Priority level (``SKIP``, ``NORMAL``, ``PINNED``).
            reason: Optional reason for the annotation.

        Returns:
            :class:`PriorityAnnotation` model.
        """
        annotation = self._commit_engine.annotate(target_hash, priority, reason)
        self._session.commit()
        self._compile_cache.clear()
        return annotation

    def get_annotations(self, target_hash: str) -> list[PriorityAnnotation]:
        """Get the full annotation history for a commit.

        Returns:
            List of :class:`PriorityAnnotation` in chronological order.
        """
        rows = self._annotation_repo.get_history(target_hash)
        return [
            PriorityAnnotation(
                id=row.id,
                repo_id=row.repo_id,
                target_hash=row.target_hash,
                priority=row.priority,
                reason=row.reason,
                created_at=row.created_at,
            )
            for row in rows
        ]

    def log(self, limit: int = 10) -> list[CommitInfo]:
        """Walk commit history from HEAD backward.

        Args:
            limit: Maximum number of commits to return.

        Returns:
            List of :class:`CommitInfo` in reverse chronological order
            (newest first).  Empty list if no commits.
        """
        current_head = self.head
        if current_head is None:
            return []

        ancestors = self._commit_repo.get_ancestors(current_head, limit=limit)
        return [self._commit_engine._row_to_info(row) for row in ancestors]

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Context manager for atomic multi-commit batches.

        Defers the session ``commit()`` until the batch exits successfully.
        Rolls back on exception.

        Example::

            with repo.batch():
                repo.commit(InstructionContent(text="System prompt"))
                repo.commit(DialogueContent(role="user", text="Hi"))
        """
        # Stash the real session.commit and replace with a no-op
        _real_commit = self._session.commit

        def _noop_commit() -> None:
            pass

        self._session.commit = _noop_commit  # type: ignore[assignment]
        try:
            yield
            # Success: flush pending and commit once
            _real_commit()
        except Exception:
            self._session.rollback()
            raise
        finally:
            self._session.commit = _real_commit  # type: ignore[assignment]

    def register_content_type(self, name: str, model: type[BaseModel]) -> None:
        """Register a custom content type for this repo instance.

        Args:
            name: The ``content_type`` discriminator value.
            model: A Pydantic ``BaseModel`` subclass.
        """
        self._custom_type_registry[name] = model

    def close(self) -> None:
        """Close the session and dispose the engine."""
        if self._closed:
            return
        self._closed = True
        self._session.close()
        if self._engine is not None:
            self._engine.dispose()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Repo:
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Repo(repo_id='{self._repo_id}', head='{self.head}')"
