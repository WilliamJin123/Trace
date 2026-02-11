"""Trace: Git-like version control for LLM context windows.

Agents produce better outputs when their context is clean, coherent, and relevant.
Trace makes context a managed, version-controlled resource.
"""

from tract._version import __version__

# Core entry point
from tract.repo import Repo

# Content types
from tract.models.content import (
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
from tract.models.commit import CommitInfo, CommitOperation
from tract.models.annotations import Priority, PriorityAnnotation

# Configuration
from tract.models.config import RepoConfig, TokenBudgetConfig, BudgetAction

# Protocols and output types
from tract.protocols import (
    TokenCounter,
    ContextCompiler,
    Message,
    CompiledContext,
    CompileSnapshot,
    TokenUsage,
)

# Exceptions
from tract.exceptions import (
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
    "CompileSnapshot",
    "TokenUsage",
    # Exceptions
    "TraceError",
    "CommitNotFoundError",
    "BlobNotFoundError",
    "ContentValidationError",
    "BudgetExceededError",
    "EditTargetError",
]
