"""Trace: Git-like version control for LLM context windows.

Agents produce better outputs when their context is clean, coherent, and relevant.
Trace makes context a managed, version-controlled resource.
"""

from trace_context._version import __version__

# Core entry point
from trace_context.repo import Repo

# Content types
from trace_context.models.content import (
    BUILTIN_TYPE_HINTS,
    ContentPayload,
    ContentTypeHints,
    DialogueContent,
    FreeformContent,
    InstructionContent,
    ArtifactContent,
    OutputContent,
    ReasoningContent,
    ToolIOContent,
    validate_content,
)

# Commit and annotation types
from trace_context.models.commit import CommitInfo, CommitOperation
from trace_context.models.annotations import Priority, PriorityAnnotation

# Configuration
from trace_context.models.config import RepoConfig, TokenBudgetConfig, BudgetAction

# Protocols and output types
from trace_context.protocols import (
    TokenCounter,
    ContextCompiler,
    Message,
    CompiledContext,
    TokenUsage,
)

# Exceptions
from trace_context.exceptions import (
    TraceError,
    CommitNotFoundError,
    BlobNotFoundError,
    ContentValidationError,
    BudgetExceededError,
    EditTargetError,
)

__all__ = [
    "__version__",
    "Repo",
    # Content types
    "ContentPayload",
    "InstructionContent",
    "DialogueContent",
    "ToolIOContent",
    "ReasoningContent",
    "ArtifactContent",
    "OutputContent",
    "FreeformContent",
    "validate_content",
    "BUILTIN_TYPE_HINTS",
    "ContentTypeHints",
    # Commit types
    "CommitInfo",
    "CommitOperation",
    # Annotations
    "Priority",
    "PriorityAnnotation",
    # Config
    "RepoConfig",
    "TokenBudgetConfig",
    "BudgetAction",
    # Protocols
    "TokenCounter",
    "ContextCompiler",
    "Message",
    "CompiledContext",
    "TokenUsage",
    # Exceptions
    "TraceError",
    "CommitNotFoundError",
    "BlobNotFoundError",
    "ContentValidationError",
    "BudgetExceededError",
    "EditTargetError",
]
