"""Middleware infrastructure for Tract.

Provides MiddlewareContext (the immutable context passed to handlers)
and the VALID_EVENTS set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from tract.models.commit import CommitInfo
    from tract.tract import Tract

VALID_EVENTS = frozenset({
    "pre_commit",
    "post_commit",
    "pre_compile",
    "pre_compress",
    "pre_merge",
    "pre_gc",
    "pre_transition",
    "post_transition",
})


@dataclass(frozen=True)
class MiddlewareContext:
    """Immutable context passed to middleware handlers."""

    event: str
    commit: CommitInfo | None
    tract: Tract
    branch: str
    head: str
    target: str | None = None
    pending: BaseModel | dict | None = None
