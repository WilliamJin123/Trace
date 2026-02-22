"""Operations package for Trace.

Higher-level operations that compose storage primitives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tract.models.commit import CommitInfo

if TYPE_CHECKING:
    from tract.storage.schema import CommitRow


def row_to_info(row: CommitRow) -> CommitInfo:
    """Convert a CommitRow to CommitInfo."""
    return CommitInfo(
        commit_hash=row.commit_hash,
        tract_id=row.tract_id,
        parent_hash=row.parent_hash,
        content_hash=row.content_hash,
        content_type=row.content_type,
        operation=row.operation,
        edit_target=row.edit_target,
        message=row.message,
        token_count=row.token_count,
        metadata=row.metadata_json,
        generation_config=row.generation_config_json,
        created_at=row.created_at,
    )
