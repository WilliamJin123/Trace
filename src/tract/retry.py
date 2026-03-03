"""Unified retry protocol for Trace operations.

Provides retry_with_steering() -- a generic retry loop that validates
results, steers the LLM via diagnosis feedback, and optionally hides
failed attempts from the commit history on success.

The retry protocol works for any operation that produces a result that
can be validated: chat/generate (validate response text), compression
(validate summary quality), or any future LLM-backed operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from tract.exceptions import RetryExhaustedError

T = TypeVar("T")


@dataclass(frozen=True)
class RetryResult(Generic[T]):
    """Result of a retry-guarded operation.

    Attributes:
        value: The successful result value.
        attempts: Total attempts (1 = first try succeeded).
        history: Brief log of failure diagnoses (None if first try succeeded).
    """

    value: T
    attempts: int
    history: list[str] | None = None


def retry_with_steering(
    *,
    attempt: callable,
    validate: callable,
    steer: callable,
    head_fn: callable,
    reset_fn: callable,
    max_retries: int = 3,
    hide_retries: bool = False,
    retry_metadata: callable | None = None,
) -> RetryResult:
    """Execute an operation with validation, steering, and optional retry hiding.

    Flow:
        1. Save restore_point = head_fn()
        2. result = attempt()
        3. (ok, diagnosis) = validate(result)
        4. If ok: optionally hide retries, then record retry_metadata, return
        5. If attempts >= max_retries: raise RetryExhaustedError
        6. steer(diagnosis) -- inject steering feedback
        7. Goto 2

    If hide_retries=True AND success after retries: calls
    reset_fn(restore_point) before returning. The CALLER is responsible
    for re-committing clean results. retry_metadata runs AFTER the
    reset so it can attach metadata to the re-committed result.

    Args:
        attempt: Callable that produces a result (e.g. LLM call + commit).
        validate: Callable taking the result, returns (ok, diagnosis).
            diagnosis is None on success, a string on failure.
        steer: Callable taking a diagnosis string, injects steering
            feedback (e.g. commits a user message with the diagnosis).
        head_fn: Callable returning the current HEAD hash (restore point).
        reset_fn: Callable taking a hash, resets HEAD to that point.
        max_retries: Maximum total attempts (default 3).
        hide_retries: If True, reset to restore_point on success so
            caller can re-commit clean results without retry artifacts.
        retry_metadata: Optional callable(attempts, history) called on
            success to record retry metadata. Runs AFTER hide_retries
            reset so it can attach to the re-committed result.

    Returns:
        RetryResult with the successful value, attempt count, and history.

    Raises:
        RetryExhaustedError: If all attempts fail validation.
    """
    restore_point = head_fn()
    history: list[str] = []
    last_diagnosis: str | None = None

    for attempt_num in range(1, max_retries + 1):
        result = attempt()
        ok, diagnosis = validate(result)

        if ok:
            # Reset first (caller re-commits clean), then record metadata
            if hide_retries and attempt_num > 1:
                reset_fn(restore_point)

            if retry_metadata is not None:
                retry_metadata(attempt_num, history if history else [])

            return RetryResult(
                value=result,
                attempts=attempt_num,
                history=history if history else None,
            )

        # Failed -- record and steer
        last_diagnosis = diagnosis or "validation failed"
        history.append(last_diagnosis)

        if attempt_num < max_retries:
            steer(last_diagnosis)

    raise RetryExhaustedError(
        attempts=max_retries,
        last_diagnosis=last_diagnosis or "validation failed",
        last_result=result,  # type: ignore[possibly-undefined]
    )
