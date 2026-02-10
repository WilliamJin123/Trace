"""Shared test fixtures for Trace.

Provides in-memory SQLite engine, session, and repository fixtures.
"""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from trace_context.storage.engine import create_trace_engine, init_db
from trace_context.storage.sqlite import (
    SqliteAnnotationRepository,
    SqliteBlobRepository,
    SqliteCommitRepository,
    SqliteRefRepository,
)


@pytest.fixture
def engine():
    """In-memory SQLite engine with all tables created."""
    eng = create_trace_engine(":memory:")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Session with automatic rollback after each test."""
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    sess = SessionLocal()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture
def sample_repo_id() -> str:
    return "test-repo-001"


@pytest.fixture
def blob_repo(session: Session) -> SqliteBlobRepository:
    return SqliteBlobRepository(session)


@pytest.fixture
def commit_repo(session: Session) -> SqliteCommitRepository:
    return SqliteCommitRepository(session)


@pytest.fixture
def ref_repo(session: Session) -> SqliteRefRepository:
    return SqliteRefRepository(session)


@pytest.fixture
def annotation_repo(session: Session) -> SqliteAnnotationRepository:
    return SqliteAnnotationRepository(session)
