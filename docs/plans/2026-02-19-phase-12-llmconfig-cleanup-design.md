# Phase 12: LLMConfig Cleanup & Tightening

**Date:** 2026-02-19
**Status:** Design approved, pending implementation planning
**Milestone:** v3.1 (post-DX polish)

## Problem

LLMConfig was built incrementally across Phases 9-11. The result works but has
accumulated artifacts: untyped dicts, duplicate storage paths, incomplete
capture, and inconsistent wiring. This phase resolves all of them in one pass.

## Issue Inventory

| # | Issue | Severity |
|---|---|---|
| 1 | `operation_configs` is `dict[str, LLMConfig]` — unvalidated string keys, typos silently ignored | High |
| 2 | `_build_generation_config()` only captures 3/9 fields (top_p, seed, etc. lost) | High |
| 3 | `model=` on `open()` duplicates `operation_configs` — two storage paths for the same concept | Medium |
| 4 | `_resolve_llm_config()` only accepts 3 call-level overrides — no way to pass top_p/seed at call time | Medium |
| 5 | Orchestrator `_call_llm()` ignores typed fields — only passes model + temperature | Medium |
| 6 | Compression summaries don't record `generation_config` — no record of what produced the summary | Medium |
| 7 | `compress()` silently drops config without LLM client — inconsistent with `generate()` which raises | Low |
| 8 | `from_dict()` doesn't handle cross-framework aliases or API call plumbing keys | Medium |

## Design

### 1. OperationConfigs Typed Dataclass

**Replace** `dict[str, LLMConfig]` with a frozen dataclass in `models/config.py`:

```python
@dataclass(frozen=True)
class OperationConfigs:
    """Per-operation LLM configuration defaults.

    Each field corresponds to an LLM-powered operation on Tract.
    None means 'no operation-level override — use tract default.'
    """
    chat: LLMConfig | None = None
    merge: LLMConfig | None = None
    compress: LLMConfig | None = None
    orchestrate: LLMConfig | None = None
```

**Changes:**

- `Tract._operation_configs: dict[str, LLMConfig]` → `OperationConfigs`
  (initialized to `OperationConfigs()` — all None)
- `Tract.open(operation_configs=dict)` → `Tract.open(operations=OperationConfigs)`
- `configure_operations(**kwargs)` → accepts `OperationConfigs` object or `**kwargs`
  for backward compat (constructs OperationConfigs internally, validates field names
  at dataclass construction time)
- `_resolve_llm_config("chat")` → `getattr(self._operation_configs, operation, None)`
  with validation that `operation` is a valid field name
- `operation_configs` property returns the `OperationConfigs` instance (already frozen)

### 2. Consolidate `_default_model` Into Tract-Level LLMConfig

**Replace** `self._default_model: str | None` with `self._default_config: LLMConfig | None`.

- `Tract.open(model="gpt-4o")` internally creates `LLMConfig(model="gpt-4o")`
  stored as `self._default_config`
- Users can also pass `Tract.open(default_config=LLMConfig(model="gpt-4o", temperature=0.7))`
  for full control at the tract level
- If both `model=` and `default_config=` are provided, raise `ValueError`
  (one source of truth — don't silently merge)
- `_resolve_llm_config()` fallback chain: call → operation → `_default_config`
- All 9 LLMConfig fields now available as tract-level defaults, not just model

### 3. Call-Level `llm_config=` Parameter

**Add** `llm_config: LLMConfig | None = None` to `chat()`, `generate()`,
`merge()`, `compress()`.

- Keep `model=`, `temperature=`, `max_tokens=` as sugar parameters
- **Precedence:** sugar params > `llm_config` fields > operation config > tract default
- Docstrings must explicitly document this: *"The model, temperature, and
  max_tokens parameters are sugar for the common case. When provided, they
  override the corresponding fields in llm_config."*
- `_resolve_llm_config()` updated to accept `llm_config: LLMConfig | None`
  in addition to the 3 sugar params

**Merge logic in `_resolve_llm_config()`:**

```
For each LLMConfig field:
  1. Sugar param (model=, temperature=, max_tokens=) — highest priority
  2. llm_config field (if llm_config provided and field is not None)
  3. Operation-level config field
  4. Tract-level default config field
  5. Not set (omitted from output dict)
```

### 4. Smart `from_dict()` With Aliases and Ignore List

**Enhance** `LLMConfig.from_dict()` to handle cross-framework field names and
filter out non-config API call parameters:

```python
# Known aliases across LLM frameworks
_ALIASES: dict[str, str] = {
    "stop": "stop_sequences",                # OpenAI
    "max_completion_tokens": "max_tokens",   # newer OpenAI
}

# Keys that are API call plumbing, not generation config
_IGNORED: frozenset[str] = frozenset({
    "messages", "tools", "tool_choice", "stream",
    "response_format", "n", "logprobs", "top_logprobs",
    "functions", "function_call",            # legacy OpenAI
    "system", "metadata",                    # Anthropic
})
```

**Pipeline:** apply aliases → drop ignored keys → route to known fields or `extra`.

This means you can extract LLMConfig from an API call setup dict:

```python
# Pull config out of an OpenAI-style call dict
call_kwargs = {"model": "gpt-4o", "temperature": 0.7, "messages": [...], "tools": [...]}
config = LLMConfig.from_dict(call_kwargs)
# Result: LLMConfig(model="gpt-4o", temperature=0.7) — messages/tools ignored
```

**Add** `from_obj(obj)` classmethod: extracts from any object with `__dict__`
or dataclass fields, runs through the same `from_dict()` pipeline:

```python
# Extract from a LangChain config object, dataclass, Pydantic model, etc.
config = LLMConfig.from_obj(some_framework_config)
```

### 5. Fix `_build_generation_config()` — Capture All Resolved Fields

**Replace** the 3-field capture with full resolved-config capture:

```python
def _build_generation_config(self, response: dict, *, resolved: dict) -> dict:
    """Build generation_config from the full resolved LLM kwargs.

    Captures ALL fields that were sent to the LLM (model, temperature,
    top_p, seed, etc.) so they can be queried via query_by_config().

    The response's model field is authoritative (actual model used may
    differ from requested model due to aliases/routing).
    """
    config = dict(resolved)
    # Response model is authoritative
    if "model" in response:
        config["model"] = response["model"]
    return config
```

**Impact:** Commits from `generate()` now store the full config. `query_by_config()`
works for all fields, not just model/temperature/max_tokens.

### 6. Fix Compression Summary `generation_config`

Pass `llm_kwargs` through the compression pipeline so summary commits record
what model/settings produced them:

**In `compress_range()` / summary commit creation (`compression.py`):**

```python
info = commit_engine.create_commit(
    content=summary_content,
    message=f"Compressed {n_commits} commits",
    generation_config=llm_kwargs,  # NEW: record LLM config used
)
```

This requires threading `llm_kwargs` through to the commit creation site.

### 7. Fix Orchestrator `_call_llm()` — Forward Full Config

Update `orchestrator/loop.py:_call_llm()` to pass all resolved config fields,
not just model + temperature:

- Add `max_tokens: int | None = None` to `OrchestratorConfig`
- Add `extra_llm_kwargs: dict | None = None` to `OrchestratorConfig` for
  passing through top_p, seed, etc.
- `_call_llm()` unpacks these into the `client.chat()` call

The operation-config merge in `tract.orchestrate()` also needs updating to
forward all fields from the resolved config, not just model and temperature.

### 8. Consistent Error on Config Without LLM Client

`compress()` currently silently ignores operation config when no LLM client
is configured. Change to match `generate()` behavior:

- If user provides call-level LLM params (model=, temperature=, llm_config=)
  **and** no LLM client is configured → raise `LLMConfigError`
- If only operation-level config exists but no LLM client → still allow
  (compression can work without LLM via manual content)
- Only the explicit "I want LLM here" signal triggers the error

## Non-Goals

- No new LLM provider integrations (just alias handling)
- No breaking changes to storage schema (generation_config is already JSON)
- No changes to the compile cache system
- No changes to query_by_config() — it already supports all fields, it was
  just not getting them stored

## Migration / Backward Compatibility

- `configure_operations(**kwargs)` continues to work (internally constructs
  OperationConfigs), so existing code doesn't break
- `open(model=...)` continues to work (internally creates default LLMConfig)
- `chat(model=..., temperature=...)` continues to work (sugar params unchanged)
- `operation_configs` property return type changes from `dict[str, LLMConfig]`
  to `OperationConfigs` — minor breaking change for anyone introspecting it
- `_default_model` removed as internal attribute — no public API impact
