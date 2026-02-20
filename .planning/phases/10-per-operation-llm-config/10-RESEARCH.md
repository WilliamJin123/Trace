# Phase 10: Per-Operation LLM Config - Research

**Researched:** 2026-02-19
**Domain:** Internal architecture -- LLM config resolution across operations
**Confidence:** HIGH (all findings from codebase analysis, no external dependencies)

## Summary

Phase 10 adds a per-operation configuration layer between the Tract-level LLM defaults and per-call overrides. Currently, five LLM-powered operations share a single `_llm_client` with a single `_default_model`. Each operation has ad-hoc config handling: `chat()`/`generate()` accept model/temperature/max_tokens as call params; `merge()` accepts model and creates a new resolver; `compress()` passes the raw client with NO model/temperature at all; `orchestrate()` has its own `OrchestratorConfig` with model/temperature; and `_auto_message()` is pure text truncation with no LLM involvement.

The standard approach is a **config resolution chain**: call-level override > operation-level default > tract-level default > client default. This requires: (1) a small `OperationConfig` dataclass to hold per-operation defaults, (2) a dict on Tract mapping operation names to their configs, (3) a `configure_operations()` or similar method to set these, and (4) updates to each operation's internal code to merge configs through the chain.

**Primary recommendation:** Add a frozen `LLMOperationConfig` dataclass and a `_operation_configs: dict[str, LLMOperationConfig]` on Tract, with a `configure_operations()` method and resolution logic in a shared `_resolve_llm_config()` helper. Each operation reads its config from the chain before calling the LLM client.

## Standard Stack

This phase is purely internal architecture -- no new libraries needed.

### Core
| Component | Location | Purpose | Current State |
|-----------|----------|---------|---------------|
| `LLMOperationConfig` | NEW: `src/tract/models/config.py` | Per-operation LLM defaults | Does not exist yet |
| `Tract._operation_configs` | `src/tract/tract.py` | Maps operation names to configs | Does not exist yet |
| `Tract._resolve_llm_config()` | `src/tract/tract.py` | Merges call > operation > tract defaults | Does not exist yet |

### Existing Components (to be modified)
| Component | Location | Purpose | Change Needed |
|-----------|----------|---------|---------------|
| `Tract.chat()` | `src/tract/tract.py:735` | User message + LLM call | Read per-op config from chain |
| `Tract.generate()` | `src/tract/tract.py:651` | Compile + LLM call | Read per-op config from chain |
| `Tract.merge()` | `src/tract/tract.py:1427` | Branch merge | Read per-op config, pass to resolver |
| `Tract.compress()` | `src/tract/tract.py:1699` | Commit compression | Read per-op config, pass model/temp/max_tokens to compress_range |
| `Tract.orchestrate()` | `src/tract/tract.py:2395` | Agent loop | Merge per-op config into OrchestratorConfig |
| `compress_range()` | `src/tract/operations/compression.py:366` | Core compress logic | `_summarize_group` needs model/temperature/max_tokens params |
| `_summarize_group()` | `src/tract/operations/compression.py:316` | LLM summarization call | Currently calls `llm_client.chat(messages)` with NO params |
| `Tract.open()` | `src/tract/tract.py:166` | Factory method | Accept `operation_configs` param |

### No New Dependencies

This phase requires zero new libraries. All changes are internal Python dataclasses and method signature updates.

## Architecture Patterns

### Config Resolution Chain

The core pattern is a 4-level config resolution chain:

```
call-level override  >  operation-level default  >  tract-level default  >  client default
```

**Example:** User sets tract default model to `gpt-4o-mini`, sets compress operation to `gpt-3.5-turbo`, then calls `t.chat("hi", model="gpt-4o")`:
- chat() resolves: call-level `gpt-4o` wins (overrides tract default `gpt-4o-mini`)
- compress() resolves: operation-level `gpt-3.5-turbo` wins (overrides tract default)
- merge() resolves: no operation-level set, so tract default `gpt-4o-mini` wins

### Recommended Data Model

```python
# In src/tract/models/config.py (or src/tract/llm/protocols.py)
from dataclasses import dataclass

@dataclass(frozen=True)
class LLMOperationConfig:
    """Per-operation LLM configuration defaults.

    None fields mean "inherit from tract-level default".
    """
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    extra_kwargs: dict | None = None  # Additional kwargs forwarded to client.chat()
```

### Operation Names (Enum or String Constants)

Five canonical operation names:

| Name | Operation | Current Config Source |
|------|-----------|---------------------|
| `"chat"` | `chat()` / `generate()` | call params only (model, temp, max_tokens) |
| `"merge"` | `merge()` | model param -> creates new OpenAIResolver |
| `"compress"` | `compress()` | NONE -- no model/temp/max_tokens passed at all |
| `"orchestrate"` | `orchestrate()` | OrchestratorConfig.model / .temperature |
| `"auto_message"` | `_auto_message()` | N/A -- currently pure text, no LLM |

**Recommendation:** Use string constants, not an Enum. Operations are extensible (users may add custom operations in the future). Store constants as module-level variables for discoverability.

### Resolution Logic

```python
def _resolve_llm_config(
    self,
    operation: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    **kwargs,
) -> dict:
    """Resolve effective LLM config by merging call > operation > tract defaults.

    Returns dict with keys: model, temperature, max_tokens, plus any extra kwargs.
    Only includes keys that have a non-None value at some level.
    """
    op_config = self._operation_configs.get(operation)

    resolved = {}

    # Model: call > operation > tract default > (client handles its own default)
    if model is not None:
        resolved["model"] = model
    elif op_config is not None and op_config.model is not None:
        resolved["model"] = op_config.model
    elif self._default_model is not None:
        resolved["model"] = self._default_model

    # Temperature: call > operation > (no tract default currently)
    if temperature is not None:
        resolved["temperature"] = temperature
    elif op_config is not None and op_config.temperature is not None:
        resolved["temperature"] = op_config.temperature

    # Max tokens: call > operation > (no tract default)
    if max_tokens is not None:
        resolved["max_tokens"] = max_tokens
    elif op_config is not None and op_config.max_tokens is not None:
        resolved["max_tokens"] = op_config.max_tokens

    # Extra kwargs from operation config (call kwargs override)
    if op_config is not None and op_config.extra_kwargs:
        resolved.update(op_config.extra_kwargs)
    resolved.update(kwargs)

    return resolved
```

### API Surface

```python
# Setting per-operation defaults
t = Tract.open(api_key="sk-...", model="gpt-4o-mini")

# Option A: configure_operations() method (recommended)
from tract import LLMOperationConfig
t.configure_operations(
    chat=LLMOperationConfig(model="gpt-4o", temperature=0.7),
    compress=LLMOperationConfig(model="gpt-3.5-turbo", temperature=0.0),
    merge=LLMOperationConfig(model="gpt-4o", temperature=0.3),
)

# Option B: on Tract.open() (for common case)
t = Tract.open(
    api_key="sk-...",
    model="gpt-4o-mini",
    chat_model="gpt-4o",        # Shorthand for chat operation
    compress_model="gpt-3.5-turbo",  # Shorthand for compress
)

# Per-call override still works (highest priority)
t.chat("complex question", model="gpt-4o")  # overrides chat default
```

**Recommendation:** Implement Option A (`configure_operations()`) as the primary API. Option B shortcuts on `Tract.open()` are sugar that can be added but are not essential for LLM-04.

### Recommended Project Structure (changes only)

```
src/tract/
├── models/
│   └── config.py          # ADD LLMOperationConfig dataclass
├── tract.py               # ADD _operation_configs, configure_operations(), _resolve_llm_config()
└── operations/
    └── compression.py     # UPDATE _summarize_group() to accept model/temp/max_tokens
```

### Anti-Patterns to Avoid

- **Per-operation LLM clients:** Do NOT create separate `OpenAIClient` instances per operation. One client handles all operations; only the per-request params change. Creating multiple clients wastes connections and breaks the ownership model.
- **Storing config in TractConfig (Pydantic):** TractConfig is persisted and has Pydantic validation. LLM operation config is runtime-only and should be a plain dataclass. Mixing them creates serialization complexity.
- **Overriding OrchestratorConfig from operation config:** The orchestrator already has its own `OrchestratorConfig.model` and `.temperature`. The per-operation config should feed INTO the orchestrator config as defaults, not replace it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Config merging | Custom merge logic per operation | Single `_resolve_llm_config()` helper | DRY; consistent resolution order across all operations |
| Operation registration | Plugin/registry system | Simple dict[str, LLMOperationConfig] | Only 5 operations; extensibility not needed yet |
| Config validation | Pydantic model with validators | Frozen dataclass + duck typing | Runtime-only, simple structure, no persistence |

**Key insight:** This is a thin configuration layer, not a framework. Five operations, one resolution function, one dataclass. Resist the temptation to over-engineer.

## Common Pitfalls

### Pitfall 1: Compress operation silently ignores model config
**What goes wrong:** `_summarize_group()` currently calls `llm_client.chat(messages)` with zero keyword arguments. Even if you set a per-operation model for compress, it won't get passed through unless `_summarize_group()` is updated.
**Why it happens:** `compress_range()` accepts an `llm_client` but not model/temperature/max_tokens. The function signature must be extended.
**How to avoid:** Update both `_summarize_group()` and `compress_range()` to accept and forward `model`, `temperature`, `max_tokens` kwargs.
**Warning signs:** Tests pass but compress uses client default model regardless of per-operation config.

### Pitfall 2: Merge resolver recreation on every call
**What goes wrong:** Current merge code creates a NEW `OpenAIResolver` when model is overridden (line 1469). If per-operation config is always set, this creates a resolver on every merge call.
**Why it happens:** `OpenAIResolver.__init__` stores model/temperature/max_tokens. Per-operation config means these are always "overridden."
**How to avoid:** Create the resolver once with the resolved config. Or refactor to pass model/temp into the resolver's `__call__` (but this changes the protocol). Simpler: accept the recreation; it's cheap (no I/O in constructor).
**Warning signs:** None visible to users; this is a performance micro-optimization that doesn't matter.

### Pitfall 3: Orchestrator config double-merging
**What goes wrong:** `OrchestratorConfig` already has `model` and `temperature` fields. If you also set per-operation config for "orchestrate," there's ambiguity about which takes priority.
**Why it happens:** Two config systems converging.
**How to avoid:** Define clear precedence: `OrchestratorConfig` fields ARE the operation-level config for orchestrate. `configure_operations(orchestrate=...)` should update `OrchestratorConfig`, not create a parallel path.
**Warning signs:** Setting config in two places and getting unexpected model.

### Pitfall 4: Breaking _build_generation_config
**What goes wrong:** `_build_generation_config()` currently only considers call-level params and `self._default_model`. It needs to also consider per-operation defaults so generation_config accurately reflects what was actually used.
**Why it happens:** The generation_config should record the ACTUAL model used, which may come from the per-operation default.
**How to avoid:** Pass the resolved config dict into `_build_generation_config()` or refactor it to use `_resolve_llm_config()`.
**Warning signs:** generation_config on commits doesn't reflect the per-operation model.

### Pitfall 5: auto_message LLM scope creep
**What goes wrong:** Requirements mention "auto-commit-messages" as an LLM-powered operation. But `_auto_message()` is currently pure text truncation (no LLM). Adding LLM-powered message generation is a feature addition, not just config routing.
**Why it happens:** Requirement LLM-04 lists it as configurable, implying it should have LLM support.
**How to avoid:** Decide scope: either (a) add LLM-powered auto-message generation AND its per-operation config, or (b) add the config slot but leave the LLM implementation as a future task. Recommendation: add the config slot (so the API is complete) but keep `_auto_message()` as text truncation for now. The config slot is ready when LLM messages are added later.
**Warning signs:** Overengineering a feature that isn't needed yet.

## Code Examples

### Current: chat() config flow (from tract.py:651-778)

```python
# generate() currently:
def generate(self, *, model=None, temperature=None, max_tokens=None, ...):
    llm_kwargs = {}
    if model is not None:
        llm_kwargs["model"] = model
    if temperature is not None:
        llm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens
    response = self._llm_client.chat(messages, **llm_kwargs)
```

### After: generate() with per-operation config

```python
def generate(self, *, model=None, temperature=None, max_tokens=None, ...):
    # Resolve: call > operation > tract > client
    resolved = self._resolve_llm_config(
        "chat", model=model, temperature=temperature, max_tokens=max_tokens,
    )
    response = self._llm_client.chat(messages, **resolved)
```

### Current: compress() passes no config

```python
# compress() currently:
llm_client = getattr(self, "_llm_client", None)
result = compress_range(..., llm_client=llm_client, ...)

# _summarize_group() currently:
response = llm_client.chat(messages)  # NO model/temp/max_tokens!
```

### After: compress() with per-operation config

```python
# compress():
resolved = self._resolve_llm_config("compress")
result = compress_range(..., llm_client=llm_client, llm_kwargs=resolved, ...)

# _summarize_group() updated:
response = llm_client.chat(messages, **llm_kwargs)
```

### Current: merge() config flow

```python
# merge() currently:
if model is not None and effective_resolver is getattr(self, "_default_resolver", None):
    if hasattr(self, "_llm_client"):
        effective_resolver = OpenAIResolver(self._llm_client, model=model)
```

### After: merge() with per-operation config

```python
# merge():
resolved = self._resolve_llm_config("merge", model=model)
if effective_resolver is None or effective_resolver is getattr(self, "_default_resolver", None):
    if hasattr(self, "_llm_client"):
        effective_resolver = OpenAIResolver(
            self._llm_client,
            model=resolved.get("model"),
            temperature=resolved.get("temperature", 0.3),
            max_tokens=resolved.get("max_tokens", 2048),
        )
```

### configure_operations() API

```python
def configure_operations(self, **operation_configs: LLMOperationConfig) -> None:
    """Set per-operation LLM defaults.

    Args:
        **operation_configs: Keyword arguments where keys are operation names
            ("chat", "merge", "compress", "orchestrate", "auto_message")
            and values are LLMOperationConfig instances.

    Example::

        t.configure_operations(
            chat=LLMOperationConfig(model="gpt-4o"),
            compress=LLMOperationConfig(model="gpt-3.5-turbo"),
        )
    """
    for name, config in operation_configs.items():
        self._operation_configs[name] = config
```

## State of the Art

| Current Approach | New Approach | Impact |
|------------------|-------------|--------|
| Single `_default_model` on Tract | Per-operation configs dict | Operations can use different models |
| `compress()` passes no LLM params | `compress()` passes resolved config | Compress uses correct model |
| `merge()` only accepts model override | `merge()` uses full resolved config | Temperature/max_tokens configurable per-operation |
| Each operation has ad-hoc config logic | Shared `_resolve_llm_config()` | Consistent behavior across operations |

## Analysis: What Each Operation Needs

### chat() / generate()
- **Current config:** model, temperature, max_tokens as call params
- **Needed change:** Small -- insert `_resolve_llm_config("chat", ...)` before building llm_kwargs
- **Complexity:** LOW

### merge()
- **Current config:** model param -> creates new OpenAIResolver
- **Needed change:** Medium -- resolve config, pass temperature/max_tokens to resolver too
- **Complexity:** LOW-MEDIUM

### compress()
- **Current config:** NONE (client default only)
- **Needed change:** Larger -- `compress_range()` and `_summarize_group()` signatures must change
- **Complexity:** MEDIUM (function signature change in operations/compression.py)

### orchestrate()
- **Current config:** `OrchestratorConfig.model`, `.temperature`
- **Needed change:** Small -- when building OrchestratorConfig, fill in defaults from operation config
- **Complexity:** LOW

### auto_message (LLM-powered)
- **Current config:** N/A (no LLM)
- **Needed change:** Config slot only (no LLM implementation needed yet)
- **Complexity:** TRIVIAL (just the config key, no implementation)

## Open Questions

1. **Should `Tract.open()` accept per-operation shorthand params?**
   - e.g., `Tract.open(api_key=..., chat_model="gpt-4o", compress_model="gpt-3.5-turbo")`
   - Pros: Convenient for common case. Cons: Parameter explosion on already-busy constructor.
   - Recommendation: NO for Phase 10. `configure_operations()` is sufficient. Shorthand can be added later.

2. **Should operation config support `extra_kwargs`?**
   - e.g., `LLMOperationConfig(model="gpt-4o", extra_kwargs={"top_p": 0.9})`
   - Pros: Forwards arbitrary params (top_p, frequency_penalty, etc.) to `client.chat()`.
   - Cons: Slight complexity; Phase 9 deferred kwargs to Phase 10.
   - Recommendation: YES. Phase 9 research explicitly said "Extra kwargs can be added in Phase 10."

3. **Should auto_message get LLM implementation or just config slot?**
   - Requirements list it. But implementing LLM-powered commit messages is more than config routing.
   - Recommendation: Config slot only. Mark LLM implementation as future enhancement.

4. **Should per-operation config be settable on `Tract.open()`?**
   - Could accept `operation_configs={"chat": LLMOperationConfig(...)}` kwarg.
   - Recommendation: YES -- it's a simple dict passthrough and makes the "set it up once" story clean.

## Sources

### Primary (HIGH confidence)
- `src/tract/tract.py` -- full codebase read of chat/generate/merge/compress/orchestrate/close/configure_llm
- `src/tract/llm/client.py` -- OpenAIClient.chat() signature and default_model
- `src/tract/llm/resolver.py` -- OpenAIResolver constructor and __call__
- `src/tract/llm/protocols.py` -- LLMClient protocol, Resolution dataclass
- `src/tract/operations/compression.py` -- compress_range and _summarize_group
- `src/tract/orchestrator/loop.py` -- Orchestrator._call_llm
- `src/tract/orchestrator/config.py` -- OrchestratorConfig.model and .temperature
- `src/tract/models/config.py` -- TractConfig (no LLM config currently)
- `.planning/phases/03-branching-merging/03-CONTEXT.md` -- "Config pattern: Default on Tract, overridable per-operation"
- `.planning/phases/09-conversation-layer/09-RESEARCH.md` -- "Extra kwargs can be added in Phase 10"
- `tests/test_conversation.py` -- MockLLMClient test pattern

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all internal codebase, no external dependencies
- Architecture: HIGH -- follows established "default on Tract, override per-operation" pattern from Phase 3
- Pitfalls: HIGH -- identified from actual code analysis of each operation
- API design: MEDIUM -- open questions around Tract.open() shortcuts and auto_message scope

**Research date:** 2026-02-19
**Valid until:** indefinite (internal codebase architecture, not external library)
