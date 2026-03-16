"""Shared internal utilities for tract LLM modules.

Provides de-duplicated helpers used across intelligence, autonomous,
maintain, gate, and routing modules.  This module contains ONLY
reusable plumbing -- no business logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tract.tract import Tract

logger = logging.getLogger(__name__)


def resolve_llm_client(
    tract: Tract,
    *operation_names: str,
) -> Any | None:
    """Try to resolve an LLM client by cascading through *operation_names*.

    Each name is passed to ``tract.config._resolve_llm_client(name)`` in order.
    The first one that succeeds is returned.  If **all** raise
    ``RuntimeError``, the function returns ``None`` (fail-open).

    Parameters
    ----------
    tract:
        The Tract instance whose LLM registry is consulted.
    *operation_names:
        One or more operation names to try, in priority order.
        Example: ``resolve_llm_client(t, "intelligence", "chat")``.
    """
    for name in operation_names:
        try:
            return tract.config._resolve_llm_client(name)
        except RuntimeError:
            continue
    return None


def strip_fences(text: str) -> str:
    """Strip markdown code fences (```...```) if present.

    Handles optional language tags (e.g. ````` ```json `````).
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    return cleaned


def safe_llm_call(
    client: Any,
    messages: list[dict[str, str]],
    llm_kwargs: dict[str, Any],
    *,
    caller: str = "llm",
) -> tuple[str, int] | None:
    """Make a synchronous LLM call, returning ``(raw_text, tokens_used)`` or *None*.

    Fail-open: all exceptions are caught and logged, never re-raised.

    Parameters
    ----------
    client:
        An object implementing ``chat()``, ``extract_content()``, and
        optionally ``extract_usage()``.
    messages:
        Chat messages to send.
    llm_kwargs:
        Extra keyword arguments forwarded to ``client.chat()``.
    caller:
        Human-readable label included in log warnings (e.g.
        ``"Intelligence"``, ``"Autonomous"``).
    """
    tokens_used = 0
    try:
        response = client.chat(messages, **llm_kwargs)
    except Exception:
        logger.warning(
            "%s LLM call failed; using fail-open default.",
            caller,
            exc_info=True,
        )
        return None

    try:
        raw_text = client.extract_content(response)
    except Exception:
        logger.warning(
            "%s failed to extract LLM response; using fail-open default.",
            caller,
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


async def async_safe_llm_call(
    client: Any,
    messages: list[dict[str, str]],
    llm_kwargs: dict[str, Any],
    *,
    caller: str = "llm",
) -> tuple[str, int] | None:
    """Async version of :func:`safe_llm_call`.

    Uses ``acall_llm`` from ``tract.llm.protocols`` to dispatch the call,
    which tries ``achat()`` first, then falls back to ``asyncio.to_thread(chat())``.
    """
    from tract.llm.protocols import acall_llm

    tokens_used = 0
    try:
        response = await acall_llm(client, messages, **llm_kwargs)
    except Exception:
        logger.warning(
            "%s async LLM call failed; using fail-open default.",
            caller,
            exc_info=True,
        )
        return None

    try:
        raw_text = client.extract_content(response)
    except Exception:
        logger.warning(
            "%s failed to extract async LLM response; using fail-open default.",
            caller,
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
