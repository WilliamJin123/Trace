"""Autonomous tract operations: auto-split, auto-rebase, auto-branch, middleware management.

Provides LLM-driven functions for autonomous context management:

* **auto_split** -- LLM splits a large commit into granular pieces.
* **auto_rebase** -- LLM decides whether to rebase and onto which branch.
* **auto_branch** -- LLM decides whether to create a new branch and names it.
* **MiddlewareManager** -- self-managing middleware that adds/removes handlers based on rules.

All follow the fail-open pattern from gate.py/maintain.py: on LLM errors,
operations return safe defaults (no action taken).

Example::

    from tract.autonomous import auto_split, auto_rebase, auto_branch

    result = auto_split(t, commit_hash)
    print(f"Split into {result.split_count} commits")

    rebase_result = auto_rebase(t)
    print(f"Rebased: {rebase_result.rebased}")

    branch_result = auto_branch(t, context="Starting auth implementation")
    print(f"Branched: {branch_result.branched}, name: {branch_result.branch_name}")
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from tract.llm.protocols import acall_llm

if TYPE_CHECKING:
    from tract.middleware import MiddlewareContext
    from tract.tract import Tract

__all__: list[str] = [
    "AutoSplitResult",
    "AutoRebaseResult",
    "AutoBranchResult",
    "MiddlewareManager",
    "auto_split",
    "aauto_split",
    "auto_rebase",
    "aauto_rebase",
    "auto_branch",
    "aauto_branch",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AutoSplitResult:
    """Result of an LLM-driven commit split."""

    original_hash: str
    new_hashes: tuple[str, ...]
    split_count: int
    tokens_used: int
    reasoning: str


@dataclass(frozen=True)
class AutoRebaseResult:
    """Result of an LLM-driven rebase decision."""

    rebased: bool
    reason: str
    target_branch: str | None
    tokens_used: int


@dataclass(frozen=True)
class AutoBranchResult:
    """Result of an LLM-driven branch decision."""

    branched: bool
    branch_name: str | None
    reason: str
    tokens_used: int


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SPLIT_SYSTEM_PROMPT = """\
You are a context management agent. Your job is to split a single large commit \
into multiple smaller, logically coherent pieces.

You will receive the content of a commit. Split it into granular, self-contained pieces.

Respond with JSON:
{
  "reasoning": "Brief explanation of how you split the content",
  "pieces": [
    {"content": "First piece of content", "message": "Description of first piece"},
    {"content": "Second piece of content", "message": "Description of second piece"}
  ]
}

If the content is already small and coherent (cannot be meaningfully split), return:
{
  "reasoning": "Content is already atomic",
  "pieces": []
}
"""

_REBASE_SYSTEM_PROMPT = """\
You are a context management agent. Your job is to decide whether the current \
branch should be rebased onto another branch.

You will receive information about the current branch and available branches.

Respond with JSON:
{
  "reasoning": "Brief explanation of your decision",
  "should_rebase": true,
  "target_branch": "branch-name"
}

Or if no rebase is needed:
{
  "reasoning": "Brief explanation of why no rebase is needed",
  "should_rebase": false,
  "target_branch": null
}

Consider: divergence from the main branch, whether the current branch would \
benefit from upstream changes, and branch relationships.
"""

_BRANCH_SYSTEM_PROMPT = """\
You are a context management agent. Your job is to decide whether a new branch \
should be created for the current task.

You will receive the current branch state, existing branches, recent commits, \
and a task/context description.

Respond with JSON:
{
  "reasoning": "Brief explanation of your decision",
  "should_branch": true,
  "branch_name": "feature/descriptive-name"
}

Or if no new branch is needed:
{
  "reasoning": "Brief explanation of why no branch is needed",
  "should_branch": false,
  "branch_name": null
}

Branch names must follow git naming rules (no spaces, no special characters). \
Use descriptive, kebab-case names.
"""

_MIDDLEWARE_EVAL_SYSTEM_PROMPT = """\
You are a context management agent evaluating middleware rules.

You will receive a set of rules and the current context state. For each rule, \
decide whether its condition is met.

Respond with JSON:
{
  "evaluations": [
    {"rule_index": 0, "should_fire": true, "reasoning": "Condition met because..."},
    {"rule_index": 1, "should_fire": false, "reasoning": "Condition not met because..."}
  ]
}
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Strip markdown code fences if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    return cleaned


def _safe_llm_call(
    client: Any,
    messages: list[dict[str, str]],
    llm_kwargs: dict[str, Any],
) -> tuple[str, int] | None:
    """Make an LLM call, return (raw_text, tokens_used) or None on failure."""
    tokens_used = 0
    try:
        response = client.chat(messages, **llm_kwargs)
    except Exception:
        logger.warning(
            "Autonomous LLM call failed; using fail-open default.",
            exc_info=True,
        )
        return None

    try:
        raw_text = client.extract_content(response)
    except Exception:
        logger.warning(
            "Failed to extract LLM response; using fail-open default.",
            exc_info=True,
        )
        return None

    try:
        usage = client.extract_usage(response) if hasattr(client, "extract_usage") else None
        if usage and isinstance(usage, dict):
            tokens_used = int(usage.get("total_tokens", 0))
    except Exception:
        pass

    return raw_text, tokens_used


async def _async_safe_llm_call(
    client: Any,
    messages: list[dict[str, str]],
    llm_kwargs: dict[str, Any],
) -> tuple[str, int] | None:
    """Async version of _safe_llm_call."""
    tokens_used = 0
    try:
        response = await acall_llm(client, messages, **llm_kwargs)
    except Exception:
        logger.warning(
            "Autonomous async LLM call failed; using fail-open default.",
            exc_info=True,
        )
        return None

    try:
        raw_text = client.extract_content(response)
    except Exception:
        logger.warning(
            "Failed to extract async LLM response; using fail-open default.",
            exc_info=True,
        )
        return None

    try:
        usage = client.extract_usage(response) if hasattr(client, "extract_usage") else None
        if usage and isinstance(usage, dict):
            tokens_used = int(usage.get("total_tokens", 0))
    except Exception:
        pass

    return raw_text, tokens_used


def _resolve_client(tract: Tract, operation: str = "autonomous") -> Any | None:
    """Resolve the LLM client, trying autonomous > intelligence > chat.

    Returns None if no client available (fail-open).
    """
    for op in (operation, "intelligence", "chat"):
        try:
            return tract._resolve_llm_client(op)
        except RuntimeError:
            continue
    return None


def _build_llm_kwargs(
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Build LLM kwargs dict from optional parameters."""
    kwargs: dict[str, Any] = {}
    if model is not None:
        kwargs["model"] = model
    if temperature is not None:
        kwargs["temperature"] = temperature
    else:
        kwargs["temperature"] = 0.2
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return kwargs


# ---------------------------------------------------------------------------
# auto_split
# ---------------------------------------------------------------------------

def auto_split(
    tract: Tract,
    commit_hash: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AutoSplitResult:
    """Split a commit into smaller, logically coherent pieces using LLM judgment.

    Gets the commit content, asks an LLM to split it into pieces, then
    creates new APPEND commits for each piece and EDITs the original to SKIP it.

    Fail-open: on LLM error, returns original hash unchanged.

    Args:
        tract: The Tract instance.
        commit_hash: Hash of the commit to split.
        model: Model override for the LLM call.
        temperature: Temperature override.
        max_tokens: Max tokens override.

    Returns:
        :class:`AutoSplitResult` with the new commit hashes.
    """
    # Fail-open default
    fail_open = AutoSplitResult(
        original_hash=commit_hash,
        new_hashes=(commit_hash,),
        split_count=1,
        tokens_used=0,
        reasoning="No split performed (fail-open).",
    )

    # Resolve client
    client = _resolve_client(tract)
    if client is None:
        return AutoSplitResult(
            original_hash=commit_hash,
            new_hashes=(commit_hash,),
            split_count=1,
            tokens_used=0,
            reasoning="No LLM client configured; no split performed (fail-open).",
        )

    # Get the commit content
    try:
        content = tract.get_content(commit_hash)
        if content is None:
            return fail_open
        content_str = json.dumps(content, default=str) if isinstance(content, dict) else str(content)
    except Exception:
        logger.warning("Failed to get content for commit %s; no split.", commit_hash[:12], exc_info=True)
        return fail_open

    # Build LLM messages
    messages = [
        {"role": "system", "content": _SPLIT_SYSTEM_PROMPT},
        {"role": "user", "content": f"=== COMMIT CONTENT ===\n{content_str}"},
    ]

    llm_kwargs = _build_llm_kwargs(model, temperature, max_tokens)

    # LLM call
    result = _safe_llm_call(client, messages, llm_kwargs)
    if result is None:
        return fail_open

    raw_text, tokens_used = result

    # Parse response
    pieces = _parse_split_response(raw_text)
    if not pieces:
        return AutoSplitResult(
            original_hash=commit_hash,
            new_hashes=(commit_hash,),
            split_count=1,
            tokens_used=tokens_used,
            reasoning="LLM returned no split pieces; keeping original.",
        )

    # Create new commits and skip original
    return _execute_split(tract, commit_hash, pieces, tokens_used)


async def aauto_split(
    tract: Tract,
    commit_hash: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AutoSplitResult:
    """Async version of :func:`auto_split`."""
    fail_open = AutoSplitResult(
        original_hash=commit_hash,
        new_hashes=(commit_hash,),
        split_count=1,
        tokens_used=0,
        reasoning="No split performed (fail-open).",
    )

    client = _resolve_client(tract)
    if client is None:
        return AutoSplitResult(
            original_hash=commit_hash,
            new_hashes=(commit_hash,),
            split_count=1,
            tokens_used=0,
            reasoning="No LLM client configured; no split performed (fail-open).",
        )

    try:
        content = tract.get_content(commit_hash)
        if content is None:
            return fail_open
        content_str = json.dumps(content, default=str) if isinstance(content, dict) else str(content)
    except Exception:
        return fail_open

    messages = [
        {"role": "system", "content": _SPLIT_SYSTEM_PROMPT},
        {"role": "user", "content": f"=== COMMIT CONTENT ===\n{content_str}"},
    ]

    llm_kwargs = _build_llm_kwargs(model, temperature, max_tokens)

    result = await _async_safe_llm_call(client, messages, llm_kwargs)
    if result is None:
        return fail_open

    raw_text, tokens_used = result
    pieces = _parse_split_response(raw_text)
    if not pieces:
        return AutoSplitResult(
            original_hash=commit_hash,
            new_hashes=(commit_hash,),
            split_count=1,
            tokens_used=tokens_used,
            reasoning="LLM returned no split pieces; keeping original.",
        )

    return _execute_split(tract, commit_hash, pieces, tokens_used)


def _parse_split_response(text: str) -> list[dict[str, str]]:
    """Parse an LLM split response into a list of {content, message} dicts."""
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            pieces = data.get("pieces", [])
            if not isinstance(pieces, list):
                return []
            valid = []
            for piece in pieces:
                if isinstance(piece, dict) and "content" in piece:
                    valid.append({
                        "content": str(piece["content"]),
                        "message": str(piece.get("message", "Split piece")),
                    })
            return valid
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def _execute_split(
    tract: Tract,
    original_hash: str,
    pieces: list[dict[str, str]],
    tokens_used: int,
) -> AutoSplitResult:
    """Create new commits for each split piece and SKIP the original."""
    from tract.models.annotations import Priority
    from tract.models.commit import CommitOperation

    new_hashes: list[str] = []
    reasoning_parts: list[str] = []

    for piece in pieces:
        try:
            info = tract.commit(
                {"content_type": "freeform", "payload": {"text": piece["content"]}},
                operation=CommitOperation.APPEND,
                message=piece["message"],
            )
            new_hashes.append(info.commit_hash)
            reasoning_parts.append(f"Created: {info.commit_hash[:8]} - {piece['message']}")
        except Exception as exc:
            logger.warning(
                "Failed to create split commit: %s", exc, exc_info=True,
            )

    if not new_hashes:
        # All pieces failed -- fail-open, keep original
        return AutoSplitResult(
            original_hash=original_hash,
            new_hashes=(original_hash,),
            split_count=1,
            tokens_used=tokens_used,
            reasoning="All split commit creations failed; keeping original.",
        )

    # SKIP the original commit
    try:
        tract.annotate(original_hash, Priority.SKIP, reason="Split into smaller commits")
    except Exception:
        logger.warning(
            "Failed to SKIP original commit %s after split.", original_hash[:12], exc_info=True,
        )

    reasoning = f"Split into {len(new_hashes)} pieces. " + "; ".join(reasoning_parts)

    return AutoSplitResult(
        original_hash=original_hash,
        new_hashes=tuple(new_hashes),
        split_count=len(new_hashes),
        tokens_used=tokens_used,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# auto_rebase
# ---------------------------------------------------------------------------

def _build_rebase_manifest(tract: Tract) -> str:
    """Build a manifest for rebase decisions."""
    current = tract.current_branch or "(detached)"
    head = tract.head
    head_short = head[:8] if head else "(empty)"
    branches = tract.list_branches()

    lines = [
        "=== BRANCH STATE ===",
        f"Current branch: {current} | HEAD: {head_short}",
        "",
        "BRANCHES:",
    ]
    for b in branches:
        marker = " *" if b.is_current else ""
        commit_count = len(tract.log(limit=100))  # approximate
        lines.append(f"  {b.name}{marker} -> {b.commit_hash[:8] if b.commit_hash else '(empty)'}")

    # Recent commits on current branch
    entries = tract.log(limit=10)
    if entries:
        lines.append("")
        lines.append("RECENT COMMITS (current branch):")
        for e in entries:
            lines.append(f"  [{e.commit_hash[:8]}] {e.content_type} | \"{e.message or '(no msg)'}\"")

    return "\n".join(lines)


def auto_rebase(
    tract: Tract,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AutoRebaseResult:
    """Decide whether to rebase the current branch using LLM judgment.

    Builds a manifest of branch state and asks the LLM whether a rebase
    would be beneficial. If yes, executes the rebase.

    Fail-open: on error, returns rebased=False.

    Args:
        tract: The Tract instance.
        model: Model override for the LLM call.
        temperature: Temperature override.
        max_tokens: Max tokens override.

    Returns:
        :class:`AutoRebaseResult`.
    """
    fail_open = AutoRebaseResult(
        rebased=False,
        reason="No rebase performed (fail-open).",
        target_branch=None,
        tokens_used=0,
    )

    client = _resolve_client(tract)
    if client is None:
        return AutoRebaseResult(
            rebased=False,
            reason="No LLM client configured; no rebase performed (fail-open).",
            target_branch=None,
            tokens_used=0,
        )

    # Build manifest
    manifest = _build_rebase_manifest(tract)

    messages = [
        {"role": "system", "content": _REBASE_SYSTEM_PROMPT},
        {"role": "user", "content": manifest},
    ]

    llm_kwargs = _build_llm_kwargs(model, temperature, max_tokens)

    result = _safe_llm_call(client, messages, llm_kwargs)
    if result is None:
        return fail_open

    raw_text, tokens_used = result

    # Parse response
    decision = _parse_rebase_response(raw_text)
    if decision is None:
        return AutoRebaseResult(
            rebased=False,
            reason="Could not parse LLM response; no rebase performed.",
            target_branch=None,
            tokens_used=tokens_used,
        )

    should_rebase, target_branch, reasoning = decision

    if not should_rebase or not target_branch:
        return AutoRebaseResult(
            rebased=False,
            reason=reasoning,
            target_branch=None,
            tokens_used=tokens_used,
        )

    # Execute rebase
    try:
        tract.rebase(target_branch)
        return AutoRebaseResult(
            rebased=True,
            reason=reasoning,
            target_branch=target_branch,
            tokens_used=tokens_used,
        )
    except Exception as exc:
        logger.warning(
            "Auto-rebase onto '%s' failed: %s", target_branch, exc, exc_info=True,
        )
        return AutoRebaseResult(
            rebased=False,
            reason=f"Rebase failed: {exc}",
            target_branch=target_branch,
            tokens_used=tokens_used,
        )


async def aauto_rebase(
    tract: Tract,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AutoRebaseResult:
    """Async version of :func:`auto_rebase`."""
    fail_open = AutoRebaseResult(
        rebased=False,
        reason="No rebase performed (fail-open).",
        target_branch=None,
        tokens_used=0,
    )

    client = _resolve_client(tract)
    if client is None:
        return AutoRebaseResult(
            rebased=False,
            reason="No LLM client configured; no rebase performed (fail-open).",
            target_branch=None,
            tokens_used=0,
        )

    manifest = _build_rebase_manifest(tract)

    messages = [
        {"role": "system", "content": _REBASE_SYSTEM_PROMPT},
        {"role": "user", "content": manifest},
    ]

    llm_kwargs = _build_llm_kwargs(model, temperature, max_tokens)

    result = await _async_safe_llm_call(client, messages, llm_kwargs)
    if result is None:
        return fail_open

    raw_text, tokens_used = result
    decision = _parse_rebase_response(raw_text)
    if decision is None:
        return AutoRebaseResult(
            rebased=False,
            reason="Could not parse LLM response; no rebase performed.",
            target_branch=None,
            tokens_used=tokens_used,
        )

    should_rebase, target_branch, reasoning = decision
    if not should_rebase or not target_branch:
        return AutoRebaseResult(
            rebased=False,
            reason=reasoning,
            target_branch=None,
            tokens_used=tokens_used,
        )

    try:
        tract.rebase(target_branch)
        return AutoRebaseResult(
            rebased=True,
            reason=reasoning,
            target_branch=target_branch,
            tokens_used=tokens_used,
        )
    except Exception as exc:
        return AutoRebaseResult(
            rebased=False,
            reason=f"Rebase failed: {exc}",
            target_branch=target_branch,
            tokens_used=tokens_used,
        )


def _parse_rebase_response(text: str) -> tuple[bool, str | None, str] | None:
    """Parse an LLM rebase response. Returns (should_rebase, target, reasoning) or None."""
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            reasoning = str(data.get("reasoning") or "").strip() or "(no reasoning given)"
            should_rebase = bool(data.get("should_rebase", False))
            target = data.get("target_branch")
            if target is not None:
                target = str(target).strip() or None
            return should_rebase, target, reasoning
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# auto_branch
# ---------------------------------------------------------------------------

def _build_branch_manifest(tract: Tract, context: str = "") -> str:
    """Build a manifest for branch decisions."""
    current = tract.current_branch or "(detached)"
    head = tract.head
    head_short = head[:8] if head else "(empty)"
    branches = tract.list_branches()

    lines = [
        "=== BRANCH STATE ===",
        f"Current branch: {current} | HEAD: {head_short}",
        "",
        "EXISTING BRANCHES:",
    ]
    for b in branches:
        marker = " *" if b.is_current else ""
        lines.append(f"  {b.name}{marker}")

    # Recent commits
    entries = tract.log(limit=10)
    if entries:
        lines.append("")
        lines.append("RECENT COMMITS:")
        for e in entries:
            lines.append(f"  [{e.commit_hash[:8]}] {e.content_type} | \"{e.message or '(no msg)'}\"")

    # Active directives
    try:
        ci = tract.config_index
        if ci.directives:
            lines.append("")
            lines.append("ACTIVE DIRECTIVES:")
            for name, text in ci.directives.items():
                lines.append(f"  {name}: {text[:80]}...")
    except Exception:
        pass

    if context:
        lines.append("")
        lines.append("=== TASK CONTEXT ===")
        lines.append(context)

    return "\n".join(lines)


def auto_branch(
    tract: Tract,
    *,
    context: str = "",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AutoBranchResult:
    """Decide whether to create a new branch using LLM judgment.

    Builds a manifest of current state and asks the LLM whether a new
    branch should be created. If yes, creates and switches to it.

    Fail-open: on error, returns branched=False.

    Args:
        tract: The Tract instance.
        context: Optional task/context description to inform the decision.
        model: Model override for the LLM call.
        temperature: Temperature override.
        max_tokens: Max tokens override.

    Returns:
        :class:`AutoBranchResult`.
    """
    fail_open = AutoBranchResult(
        branched=False,
        branch_name=None,
        reason="No branch created (fail-open).",
        tokens_used=0,
    )

    client = _resolve_client(tract)
    if client is None:
        return AutoBranchResult(
            branched=False,
            branch_name=None,
            reason="No LLM client configured; no branch created (fail-open).",
            tokens_used=0,
        )

    manifest = _build_branch_manifest(tract, context)

    messages = [
        {"role": "system", "content": _BRANCH_SYSTEM_PROMPT},
        {"role": "user", "content": manifest},
    ]

    llm_kwargs = _build_llm_kwargs(model, temperature, max_tokens)

    result = _safe_llm_call(client, messages, llm_kwargs)
    if result is None:
        return fail_open

    raw_text, tokens_used = result
    decision = _parse_branch_response(raw_text)
    if decision is None:
        return AutoBranchResult(
            branched=False,
            branch_name=None,
            reason="Could not parse LLM response; no branch created.",
            tokens_used=tokens_used,
        )

    should_branch, branch_name, reasoning = decision

    if not should_branch or not branch_name:
        return AutoBranchResult(
            branched=False,
            branch_name=None,
            reason=reasoning,
            tokens_used=tokens_used,
        )

    # Create and switch to branch
    try:
        tract.branch(branch_name)
        return AutoBranchResult(
            branched=True,
            branch_name=branch_name,
            reason=reasoning,
            tokens_used=tokens_used,
        )
    except Exception as exc:
        logger.warning(
            "Auto-branch '%s' failed: %s", branch_name, exc, exc_info=True,
        )
        return AutoBranchResult(
            branched=False,
            branch_name=branch_name,
            reason=f"Branch creation failed: {exc}",
            tokens_used=tokens_used,
        )


async def aauto_branch(
    tract: Tract,
    *,
    context: str = "",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AutoBranchResult:
    """Async version of :func:`auto_branch`."""
    fail_open = AutoBranchResult(
        branched=False,
        branch_name=None,
        reason="No branch created (fail-open).",
        tokens_used=0,
    )

    client = _resolve_client(tract)
    if client is None:
        return AutoBranchResult(
            branched=False,
            branch_name=None,
            reason="No LLM client configured; no branch created (fail-open).",
            tokens_used=0,
        )

    manifest = _build_branch_manifest(tract, context)

    messages = [
        {"role": "system", "content": _BRANCH_SYSTEM_PROMPT},
        {"role": "user", "content": manifest},
    ]

    llm_kwargs = _build_llm_kwargs(model, temperature, max_tokens)

    result = await _async_safe_llm_call(client, messages, llm_kwargs)
    if result is None:
        return fail_open

    raw_text, tokens_used = result
    decision = _parse_branch_response(raw_text)
    if decision is None:
        return AutoBranchResult(
            branched=False,
            branch_name=None,
            reason="Could not parse LLM response; no branch created.",
            tokens_used=tokens_used,
        )

    should_branch, branch_name, reasoning = decision
    if not should_branch or not branch_name:
        return AutoBranchResult(
            branched=False,
            branch_name=None,
            reason=reasoning,
            tokens_used=tokens_used,
        )

    try:
        tract.branch(branch_name)
        return AutoBranchResult(
            branched=True,
            branch_name=branch_name,
            reason=reasoning,
            tokens_used=tokens_used,
        )
    except Exception as exc:
        return AutoBranchResult(
            branched=False,
            branch_name=branch_name,
            reason=f"Branch creation failed: {exc}",
            tokens_used=tokens_used,
        )


def _parse_branch_response(text: str) -> tuple[bool, str | None, str] | None:
    """Parse an LLM branch response. Returns (should_branch, name, reasoning) or None."""
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            reasoning = str(data.get("reasoning") or "").strip() or "(no reasoning given)"
            should_branch = bool(data.get("should_branch", False))
            name = data.get("branch_name")
            if name is not None:
                name = str(name).strip() or None
            return should_branch, name, reasoning
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# MiddlewareManager -- self-managing middleware
# ---------------------------------------------------------------------------

@dataclass
class MiddlewareManager:
    """Self-managing middleware that adds/removes handlers based on rules.

    Registered as a middleware handler itself (typically on ``post_commit``).
    When triggered, evaluates its rules against the current context and
    manages (adds/removes) other middleware handlers accordingly.

    Rules are declarative dicts::

        {
            "event": "post_commit",          # when this manager fires
            "condition": "more than 20 commits",  # natural-language condition
            "action": "add_middleware",       # or "remove_middleware"
            "handler_event": "pre_compile",  # event for the managed handler
            "handler_type": "gate",          # "gate" or "maintainer"
            "criterion": "Context is focused and relevant",  # for gates
        }

    The manager can use LLM evaluation to determine whether conditions
    are met, or fall back to simple heuristics.

    Attributes:
        name: Human-readable identifier for this manager.
        rules: List of rule dicts.
        model: Model override for LLM evaluation.
        temperature: Temperature for LLM calls.
        max_tokens: Max tokens for LLM calls.
    """

    name: str
    rules: list[dict[str, Any]]
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None

    # Tracks handler IDs of managed middleware
    _managed_handlers: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __call__(self, ctx: MiddlewareContext) -> None:
        """Evaluate rules and manage middleware handlers."""
        tract = ctx.tract

        # Try LLM evaluation first
        client = _resolve_client(tract)
        if client is not None:
            evaluations = self._llm_evaluate(tract, client, ctx)
        else:
            evaluations = self._heuristic_evaluate(tract, ctx)

        # Execute actions for fired rules
        for idx, should_fire in evaluations.items():
            if not should_fire:
                continue
            if idx >= len(self.rules):
                continue
            rule = self.rules[idx]
            try:
                self._execute_rule(tract, rule)
            except Exception as exc:
                logger.warning(
                    "MiddlewareManager '%s' rule %d failed: %s",
                    self.name, idx, exc, exc_info=True,
                )

    def _llm_evaluate(
        self,
        tract: Tract,
        client: Any,
        ctx: MiddlewareContext,
    ) -> dict[int, bool]:
        """Use LLM to evaluate rule conditions. Returns {rule_index: should_fire}."""
        # Build context summary
        entries = tract.log(limit=30)
        commit_count = len(entries)
        branch = tract.current_branch or "(detached)"

        context_lines = [
            f"Branch: {branch}",
            f"Total commits shown: {commit_count}",
            f"Event: {ctx.event}",
        ]
        if entries:
            context_lines.append("Recent commits:")
            for e in entries[:5]:
                context_lines.append(
                    f"  [{e.commit_hash[:8]}] {e.content_type} | \"{e.message or '(no msg)'}\""
                )

        rules_desc = []
        for idx, rule in enumerate(self.rules):
            rules_desc.append(
                f"Rule {idx}: condition=\"{rule.get('condition', '(no condition)')}\""
            )

        messages = [
            {"role": "system", "content": _MIDDLEWARE_EVAL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "=== CONTEXT ===\n"
                    + "\n".join(context_lines)
                    + "\n\n=== RULES ===\n"
                    + "\n".join(rules_desc)
                ),
            },
        ]

        llm_kwargs = _build_llm_kwargs(self.model, self.temperature, self.max_tokens)
        result = _safe_llm_call(client, messages, llm_kwargs)
        if result is None:
            return self._heuristic_evaluate(tract, ctx)

        raw_text, _ = result
        return self._parse_evaluations(raw_text)

    def _heuristic_evaluate(
        self,
        tract: Tract,
        ctx: MiddlewareContext,
    ) -> dict[int, bool]:
        """Simple heuristic evaluation when no LLM is available."""
        results: dict[int, bool] = {}
        entries = tract.log(limit=100)
        commit_count = len(entries)

        for idx, rule in enumerate(self.rules):
            condition = str(rule.get("condition", "")).lower()
            # Simple keyword-based heuristics
            if "more than" in condition and "commit" in condition:
                # Extract number
                import re
                numbers = re.findall(r"\d+", condition)
                if numbers:
                    threshold = int(numbers[0])
                    results[idx] = commit_count > threshold
                else:
                    results[idx] = False
            elif "always" in condition:
                results[idx] = True
            else:
                # Default: don't fire
                results[idx] = False

        return results

    def _parse_evaluations(self, text: str) -> dict[int, bool]:
        """Parse LLM evaluation response."""
        cleaned = _strip_fences(text)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                evaluations = data.get("evaluations", [])
                if isinstance(evaluations, list):
                    results: dict[int, bool] = {}
                    for ev in evaluations:
                        if isinstance(ev, dict):
                            idx = ev.get("rule_index", -1)
                            should_fire = bool(ev.get("should_fire", False))
                            if isinstance(idx, int) and idx >= 0:
                                results[idx] = should_fire
                    return results
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return {}

    def _execute_rule(self, tract: Tract, rule: dict[str, Any]) -> None:
        """Execute a single rule's action."""
        action = rule.get("action", "")
        handler_event = rule.get("handler_event", "pre_compile")
        handler_type = rule.get("handler_type", "gate")
        rule_key = f"{handler_event}:{handler_type}:{rule.get('criterion', rule.get('instructions', ''))[:30]}"

        if action == "add_middleware":
            # Don't add duplicate managed handlers
            if rule_key in self._managed_handlers:
                return
            handler_id = self._create_handler(tract, rule)
            if handler_id:
                self._managed_handlers[rule_key] = handler_id

        elif action == "remove_middleware":
            # Remove managed handler if it exists
            if rule_key in self._managed_handlers:
                handler_id = self._managed_handlers.pop(rule_key)
                try:
                    tract.remove_middleware(handler_id)
                except ValueError:
                    pass  # already removed

    def _create_handler(self, tract: Tract, rule: dict[str, Any]) -> str | None:
        """Create and register a middleware handler from a rule."""
        handler_event = rule.get("handler_event", "pre_compile")
        handler_type = rule.get("handler_type", "gate")

        if handler_type == "gate":
            criterion = rule.get("criterion", "Context is relevant and focused")
            handler_id = tract.gate(
                name=f"managed-{self.name}-{uuid.uuid4().hex[:6]}",
                event=handler_event,
                check=criterion,
                model=self.model,
            )
            return handler_id

        elif handler_type == "maintainer":
            instructions = rule.get("instructions", "Maintain context quality")
            actions = rule.get("actions", ["annotate", "compress"])
            handler_id = tract.maintain(
                name=f"managed-{self.name}-{uuid.uuid4().hex[:6]}",
                event=handler_event,
                instructions=instructions,
                actions=actions,
                model=self.model,
            )
            return handler_id

        return None

    def to_spec(self) -> dict[str, Any]:
        """Serialize manager configuration to a dict for persistence.

        Returns:
            Dict with all declarative manager configuration.
        """
        return {
            "name": self.name,
            "rules": [dict(r) for r in self.rules],
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "managed_handlers": dict(self._managed_handlers),
        }

    @classmethod
    def from_spec(cls, data: dict[str, Any]) -> MiddlewareManager:
        """Reconstruct a MiddlewareManager from a persisted spec dict.

        Managed handler IDs are restored but may reference stale handlers
        if the tract was closed and reopened.
        """
        manager = cls(
            name=data["name"],
            rules=data.get("rules", []),
            model=data.get("model"),
            temperature=data.get("temperature", 0.2),
            max_tokens=data.get("max_tokens"),
        )
        manager._managed_handlers = dict(data.get("managed_handlers", {}))
        return manager
