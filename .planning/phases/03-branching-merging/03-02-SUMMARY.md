---
phase: 03
plan: 02
subsystem: llm-client
tags: [httpx, tenacity, openai, llm, protocol, retry]
depends_on:
  requires: []
  provides:
    - "OpenAIClient httpx-based LLM client with tenacity retry"
    - "LLMClient and ResolverCallable protocols"
    - "OpenAIResolver for semantic merge conflict resolution"
    - "LLM error hierarchy (LLMClientError, LLMAuthError, etc.)"
  affects:
    - "03-03 (merge strategies use OpenAIResolver for conflict resolution)"
    - "03-04 (rebase/cherry-pick use resolver for semantic safety)"
    - "Phase 4 (compression uses LLM client)"
tech_stack:
  added:
    - "httpx>=0.27,<1.0 (sync HTTP client)"
    - "tenacity>=8.2,<10 (retry with exponential backoff)"
  patterns:
    - "Protocol-based pluggable LLM client"
    - "Programmatic tenacity.Retrying (not decorator) for per-instance max_retries"
    - "Duck-typed resolver with getattr() for cross-plan type access"
key_files:
  created:
    - "src/tract/llm/__init__.py"
    - "src/tract/llm/client.py"
    - "src/tract/llm/protocols.py"
    - "src/tract/llm/resolver.py"
    - "src/tract/llm/errors.py"
    - "tests/test_llm.py"
  modified:
    - "pyproject.toml"
decisions:
  - id: "03-02-01"
    decision: "Use tenacity.Retrying programmatically (not decorator) for configurable max_retries"
    rationale: "Allows per-instance retry count configuration"
  - id: "03-02-02"
    decision: "Check status codes before raise_for_status() for custom error types"
    rationale: "401/403 -> LLMAuthError, 429 -> LLMRateLimitError with retry_after, others -> HTTPStatusError"
  - id: "03-02-03"
    decision: "Duck-type issue parameter in OpenAIResolver with getattr()"
    rationale: "ConflictInfo/RebaseWarning/CherryPickIssue defined in Plan 03-03; resolver needs no import dependency"
  - id: "03-02-04"
    decision: "Resolution.content_text as string alternative to content (BaseModel)"
    rationale: "Resolver returns raw text; the merge operation creates the proper content model"
metrics:
  duration: "~6m"
  completed: "2026-02-14"
  tests_added: 56
  tests_total: 357
  lines_added: ~1311
---

# Phase 3 Plan 2: LLM Client Infrastructure Summary

**One-liner:** httpx-based OpenAI-compatible client with tenacity retry, LLMClient/ResolverCallable protocols, and built-in OpenAIResolver for semantic merge.

## What Was Built

### LLM Error Hierarchy (`llm/errors.py`)
Five error classes all inheriting from `TraceError`:
- `LLMClientError` -- base for all LLM errors
- `LLMConfigError` -- missing API key or invalid configuration
- `LLMRateLimitError` -- 429 with optional `retry_after` attribute
- `LLMAuthError` -- 401/403 authentication failures
- `LLMResponseError` -- unexpected API response format

### Protocols (`llm/protocols.py`)
- `LLMClient` -- runtime-checkable protocol for pluggable LLM clients (chat + close methods)
- `ResolverCallable` -- runtime-checkable protocol for conflict resolvers (__call__ with issue -> Resolution)
- `Resolution` -- dataclass with action (resolved/abort/skip), content_text, reasoning, generation_config

### OpenAI-Compatible Client (`llm/client.py`)
`OpenAIClient` implementing the `LLMClient` protocol:
- httpx.Client for sync HTTP requests to `/v1/chat/completions`
- Environment variable support: `TRACT_OPENAI_API_KEY`, `TRACT_OPENAI_BASE_URL`
- Programmatic `tenacity.Retrying` with exponential backoff + jitter
- Retries on 429/500/502/503/504 and connection errors
- Immediate failure on 401/403 (`LLMAuthError`) and 400 (`HTTPStatusError`)
- Rate limit error preserves `Retry-After` header value
- Context manager support (`with OpenAIClient(...) as c:`)
- Helper methods: `extract_content()`, `extract_usage()`

### Built-in Resolver (`llm/resolver.py`)
`OpenAIResolver` implementing the `ResolverCallable` protocol:
- Takes any `LLMClient`-conforming object
- Duck-typed issue formatting (works with ConflictInfo, RebaseWarning, etc.)
- Configurable: model, temperature, max_tokens, system_prompt
- Returns `Resolution(action="resolved")` with generation_config including `source: "infrastructure:merge"`
- Records model, temperature, and usage in generation_config

### Test Suite (`tests/test_llm.py`, 799 lines, 56 tests)
- Error hierarchy: 8 tests (inheritance, attributes, TraceError catchability)
- Client chat: 5 tests (success, format, default model, optional params, kwargs)
- Extractors: 4 tests (content, usage, bad format)
- Retry behavior: 11 tests (429/500/502/503/504 retry, 401/403/400 no-retry, exhaustion)
- Configuration: 7 tests (env vars, override, missing key, context manager)
- Protocol conformance: 5 tests (LLMClient, custom client, ResolverCallable)
- Resolver: 12 tests (resolution, messages, prompts, config, formatting)
- Resolution dataclass: 4 tests

## Decisions Made

1. **Programmatic Retrying** (03-02-01): Used `tenacity.Retrying(...)` instead of `@retry` decorator so `max_retries` is configurable per-instance rather than fixed at class definition time.

2. **Custom error checking before raise_for_status** (03-02-02): Check response status codes for 401/403 and 429 before calling `raise_for_status()` to raise domain-specific errors (`LLMAuthError`, `LLMRateLimitError`) instead of generic `HTTPStatusError`.

3. **Duck-typed resolver** (03-02-03): `OpenAIResolver._format_issue()` uses `getattr()` to access issue attributes without importing ConflictInfo (defined in Plan 03-03). This avoids circular dependencies between the LLM package and the merge package.

4. **Resolution.content_text** (03-02-04): Added `content_text: str | None` alongside `content: BaseModel | None`. The resolver returns raw text; the merge operation wraps it in the appropriate content model.

## Deviations from Plan

None -- plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `298d632` | LLM client package: protocols, errors, client, pyproject.toml |
| 2 | `437449a` | OpenAIResolver and 56 comprehensive tests |

## Next Phase Readiness

**For Plan 03-03 (Merge Strategies):**
- `OpenAIResolver` is ready to use as the built-in resolver for conflict resolution
- `ResolverCallable` protocol defines the contract for custom resolvers
- `Resolution` dataclass provides the standard return type from resolvers
- `generation_config` with `source: "infrastructure:merge"` is ready for merge commit metadata

**For Phase 4 (Compression):**
- `OpenAIClient` is ready for compression LLM calls
- `LLMClient` protocol allows custom client substitution

## Success Criteria Verification

- [x] OpenAIClient makes real-shaped HTTP requests (verified via MockTransport in 5 chat tests)
- [x] Retry logic: retries 429/5xx (5 retry tests), fails fast on 401/403/400 (3 no-retry tests)
- [x] LLMClient protocol works for custom implementations (test_custom_client_conforms_to_protocol)
- [x] OpenAIResolver produces Resolution from conflict info (test_resolver_returns_resolution)
- [x] httpx and tenacity added as required dependencies (pyproject.toml verified)
- [x] All existing + new tests pass (357 total, 56 new)
