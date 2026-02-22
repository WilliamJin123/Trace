# Unified Retry Protocol — Implementation Plan

## Design Principles

1. **Everything is committed** — steering messages, retries, all tracked in commit chain
2. **Patch by default** — surgical fix first, full redo only if fundamentally broken
3. **Isolate failures** — smallest failing unit retried, successful work preserved
4. **Purification is opt-in** — after success, optionally replace retry chain with clean result
5. **Configurable for autonomy** — an agent should be able to tune retry behavior per-operation

---

## Architecture

### New Module: `src/tract/retry.py`

Single reusable function + supporting types. No classes, no inheritance.

```python
@dataclass(frozen=True)
class RetryResult(Generic[T]):
    """Result of a retry-guarded operation."""
    value: T                    # the validated result
    attempts: int               # total attempts (1 = first try succeeded)
    history: list[str] | None   # brief log of failures (if any)

class RetryExhaustedError(TraceError):
    """All retry attempts failed."""
    attempts: int
    last_diagnosis: str
    last_result: Any

def retry_with_steering(
    *,
    attempt: Callable[[], T],
    validate: Callable[[T], tuple[bool, str | None]],
    steer: Callable[[str], None],
    head_fn: Callable[[], str],        # returns current HEAD hash
    reset_fn: Callable[[str], None],   # resets HEAD to hash
    max_retries: int = 3,
    purify: bool = False,
    provenance_note: Callable[[int, list[str]], None] | None = None,
) -> RetryResult[T]:
```

### Flow

```
1. save restore_point = head_fn()
2. result = attempt()
3. (ok, diagnosis) = validate(result)
4. if ok:
     if purify:
       reset_fn(restore_point)
       re-commit clean result          # caller's responsibility via return
     if provenance_note:
       provenance_note(attempts, history)
     return RetryResult(value=result, attempts=1, history=None)
5. if attempts >= max_retries:
     raise RetryExhaustedError(...)
6. steer(diagnosis)                    # commits steering message
7. goto 2
```

### Key Design Decisions

- **`validate` returns `(bool, str | None)`** — the diagnosis string is both the
  error signal AND the content that gets committed as steering. Validator is a
  black box: can be a simple `json.loads()` check or an LLM call internally.

- **`steer` commits to the tract** — it receives the diagnosis string and commits
  a user-role message with correction instructions. The retry runner doesn't
  know about Tract directly; the caller provides a closure.

- **`purify` resets HEAD** — after success, resets to restore_point. The caller
  is responsible for re-committing the clean result (since only the caller knows
  the result type/format). Failed commits become orphaned in DB but still
  queryable via DAG.

- **`provenance_note` is a callable** — caller decides format. Receives
  (attempt_count, list of diagnosis strings). Typically commits a brief meta
  message like "resolved after 2 retries: invalid JSON formatting."

- **No direct Tract dependency** — retry.py takes callables (`head_fn`,
  `reset_fn`, `steer`, `attempt`). This keeps it testable and decoupled.

---

## Wiring: Task Breakdown

### Task 1: Core retry module

**File:** `src/tract/retry.py`

Create:
- `RetryResult` frozen dataclass (generic over T)
- `RetryExhaustedError` exception (subclass of TraceError)
- `retry_with_steering()` function

No Tract dependency. Pure logic + callables.

**Tests:** `tests/test_retry.py`
- Happy path (first attempt succeeds)
- Retry succeeds on 2nd attempt
- Retry succeeds on 3rd attempt
- All retries exhausted → RetryExhaustedError
- Purify mode: verify head_fn/reset_fn called correctly
- Provenance note called with correct args
- Validate returning transformed value (validator can mutate diagnosis)
- Steer called with diagnosis string

---

### Task 2: Wire into `chat()` and `generate()`

**File:** `src/tract/tract.py` — modify `generate()` and `chat()`

New params on both methods:
```python
def chat(
    self,
    text: str,
    *,
    # ... existing params ...
    validator: Callable[[str], tuple[bool, str | None]] | None = None,
    max_retries: int = 3,
    purify: bool = False,
    provenance_note: bool = False,
    retry_prompt: str | None = None,   # custom steering template
) -> ChatResponse:
```

**Wiring in generate():**

```python
if validator is not None:
    restore_point = self.head()

    def _attempt():
        # the existing LLM call + commit logic (lines 948-980)
        ...
        return ChatResponse(...)

    def _validate(resp: ChatResponse):
        return validator(resp.text)

    def _steer(diagnosis: str):
        template = retry_prompt or (
            "Your previous response failed validation: {diagnosis}\n"
            "Please try again, addressing the issue above."
        )
        self.user(template.format(diagnosis=diagnosis))

    def _provenance(attempts, history):
        if provenance_note:
            summary = "; ".join(history)
            self.user(f"[retry resolved after {attempts} attempts: {summary}]",
                      metadata={"retry_provenance": True})

    result = retry_with_steering(
        attempt=_attempt,
        validate=_validate,
        steer=_steer,
        head_fn=self.head,
        reset_fn=lambda h: reset(h, "soft", self._tract_id, self._ref_repo),
        max_retries=max_retries,
        purify=purify,
        provenance_note=_provenance if provenance_note else None,
    )

    if purify:
        # Re-commit the clean result
        self.assistant(result.value.text,
                       generation_config=result.value.generation_config.to_dict())

    return result.value
else:
    # existing path unchanged
    ...
```

**Tests:** `tests/test_retry_chat.py`
- chat() with validator that passes first try → normal ChatResponse
- chat() with validator that fails then passes → steering message committed, correct response returned
- chat() with purify=True → only clean result in active branch
- chat() with provenance_note=True → meta commit present
- chat() with custom retry_prompt → custom steering text used
- chat() with validator, all retries fail → RetryExhaustedError
- generate() with same params (chat delegates to generate)
- Backward compat: no validator → existing behavior unchanged

---

### Task 3: Wire into `compress_range()`

**File:** `src/tract/operations/compression.py` — modify `_summarize_group()` caller

New params on `compress_range()`:
```python
def compress_range(
    ...,
    # ... existing params ...
    validator: Callable[[str], tuple[bool, str | None]] | None = None,
    max_retries: int = 3,
) -> CompressResult | PendingCompression:
```

**Wiring:**

The retry wraps `_summarize_group()` per group. On failure, the steering is a
follow-up LLM call with the diagnosis appended to the prompt (not a committed
message — compression doesn't operate on the commit chain the same way).

```python
for group in normal_groups:
    text = _build_messages_text(group, blob_repo)

    def _attempt():
        return _summarize_group(text, llm_client, token_counter, ...)

    def _validate(summary: str):
        if validator:
            return validator(summary)
        return (True, None)

    def _steer(diagnosis: str):
        # For compression, steering means re-calling with amended prompt
        nonlocal instructions
        instructions = (instructions or "") + f"\n\nPrevious attempt issue: {diagnosis}"

    result = retry_with_steering(
        attempt=_attempt,
        validate=_validate,
        steer=_steer,
        head_fn=lambda: "n/a",      # compression doesn't use HEAD
        reset_fn=lambda h: None,    # no HEAD reset needed
        max_retries=max_retries,
        purify=False,               # compression handles its own commits
    )
    summaries.append(result.value)
```

Note: compression retry is simpler — no commits to purify, steering modifies
the prompt rather than committing. The retry_with_steering function still works
because head_fn/reset_fn are no-ops.

**Tests:** `tests/test_retry_compression.py`
- compress_range() with validator that passes → normal CompressResult
- compress_range() with validator that fails then passes → retried summary used
- compress_range() with all retries exhausted → error propagated
- Validator receives summary text, can check for key terms

---

### Task 4: Export + error hierarchy update

**Files:**
- `src/tract/__init__.py` — export RetryResult, RetryExhaustedError
- `src/tract/exceptions.py` — add RetryExhaustedError to hierarchy
- `src/tract/retry.py` — import TraceError from exceptions

**Tests:** Import tests in existing test files.

---

## Execution Order

```
Task 1 (core module)
  ↓
Task 2 (chat/generate wiring)  ←──── can parallelize
Task 3 (compression wiring)    ←──── can parallelize
  ↓
Task 4 (exports + cleanup)
```

Tasks 2 and 3 are independent and can be done in parallel.
Task 4 depends on all others.

---

## What This Does NOT Cover (Future Work)

- **Merge resolution retry** — resolver pattern is already duck-typed; retry can
  be added later by wrapping the resolver callable
- **IMPORTANT priority tier** — separate plan in `IMPORTANT_PARTIAL_PINS.md`
- **Tool definitions modeling** — separate plan in `TOOL_TRACKING.md`
- **Orchestrator retry** — the orchestrator has its own loop; retry can be
  integrated later using the same `retry_with_steering()` core
- **Structured validator helpers** (json_validator, regex_validator) — convenience
  wrappers, trivial to add after core is in place

---

## File Impact Summary

| File | Change |
|------|--------|
| `src/tract/retry.py` | **NEW** — core retry module |
| `src/tract/tract.py` | MODIFY — add validator/retry params to chat()/generate() |
| `src/tract/operations/compression.py` | MODIFY — add validator/retry to compress_range() |
| `src/tract/exceptions.py` | MODIFY — add RetryExhaustedError |
| `src/tract/__init__.py` | MODIFY — export new types |
| `tests/test_retry.py` | **NEW** — core retry tests |
| `tests/test_retry_chat.py` | **NEW** — chat/generate retry integration |
| `tests/test_retry_compression.py` | **NEW** — compression retry integration |

Estimated: ~200 lines new code, ~50 lines modified, ~300 lines tests.
