"""History operations: status computation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tract.models.commit import CommitInfo


@dataclass(frozen=True)
class StatusInfo:
    """Current tract status information returned by Tract.status().

    Attributes:
        head_hash: Current HEAD commit hash, or None if no commits.
        branch_name: Current branch name, or None if detached.
        is_detached: Whether HEAD is in detached state.
        commit_count: Total commits in compiled chain from HEAD.
        token_count: Compiled token count (from compile()).
        token_budget_max: Maximum token budget, or None if no budget configured.
        token_source: Token source identifier (e.g. "tiktoken:cl100k_base").
        recent_commits: Last 3 commits in reverse chronological order.
    """

    head_hash: str | None
    branch_name: str | None  # None if detached
    is_detached: bool
    commit_count: int  # total commits in chain from HEAD
    token_count: int  # compiled token count (from compile())
    token_budget_max: int | None  # None if no budget configured
    token_source: str
    recent_commits: list[CommitInfo] = field(default_factory=list)  # last 3 commits
