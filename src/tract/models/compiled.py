"""Compilation options model for Trace.

CompileOptions is a Pydantic model holding parameters for context compilation.
CompiledContext and Message are re-exported from protocols.py for convenience.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from tract.protocols import CompiledContext, Message


class CompileOptions(BaseModel):
    """Options for context compilation.

    Controls time-travel, edit annotation visibility, role mapping
    overrides, and message aggregation behavior.
    """

    at_time: Optional[datetime] = None
    """Only include commits created at or before this datetime."""

    at_commit: Optional[str] = None
    """Only include commits up to and including this commit hash."""

    include_edit_annotations: bool = False
    """If True, append '[edited]' marker to content that was edited."""

    type_to_role_map: Optional[dict[str, str]] = None
    """Custom overrides for content_type -> role mapping."""

    aggregate_same_role: bool = True
    """If True, concatenate consecutive same-role messages."""


__all__ = ["CompileOptions", "CompiledContext", "Message"]
