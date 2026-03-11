"""Middleware infrastructure for Tract.

Provides MiddlewareContext (the immutable context passed to handlers),
MiddlewareEvent Literal type, and the VALID_EVENTS set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from pydantic import BaseModel

if TYPE_CHECKING:
    from tract.models.commit import CommitInfo
    from tract.tract import Tract

__all__: list[str] = [
    "MiddlewareEvent",
    "VALID_EVENTS",
    "MiddlewareContext",
]

# ---------------------------------------------------------------------------
# Canonical middleware event type — single source of truth
# ---------------------------------------------------------------------------
MiddlewareEvent = Literal[
    "pre_commit",
    "post_commit",
    "pre_compile",
    "pre_compress",
    "pre_merge",
    "pre_gc",
    "pre_transition",
    "post_transition",
    "pre_generate",
    "post_generate",
    "pre_tool_execute",
    "post_tool_execute",
]

VALID_EVENTS: frozenset[str] = frozenset(get_args(MiddlewareEvent))


@dataclass(frozen=True)
class MiddlewareContext:
    """Immutable context passed to middleware handlers."""

    event: MiddlewareEvent
    commit: CommitInfo | None
    tract: Tract
    branch: str
    head: str
    target: str | None = None
    pending: BaseModel | dict | None = None
