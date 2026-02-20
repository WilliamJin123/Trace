# Phase 11: Unified LLM Config & Query - Research

**Researched:** 2026-02-19
**Domain:** Frozen dataclass design, SQLite JSON querying, dict-to-typed-model migration
**Confidence:** HIGH

## Summary

Phase 11 replaces `LLMOperationConfig` (a minimal 4-field frozen dataclass) with a comprehensive `LLMConfig` frozen dataclass covering all standard LLM hyperparameters, and upgrades `query_by_config` to support multi-field AND queries, IN operator, and whole-config matching via LLMConfig objects. The third requirement updates the 3 Tier 1 cookbook examples from dict-based `generation_config` access to typed LLMConfig attribute access.

The core challenge is a dict-to-typed-model migration that touches every layer: commit creation, storage boundaries (JSON serialization/deserialization), the compile cache (copy-on-output safety), the resolution chain, and the query API. The storage layer (SQLite JSON column) does NOT change -- the conversion between LLMConfig and dict happens at the boundary (CommitRow -> CommitInfo and vice versa).

**Primary recommendation:** Define LLMConfig as a frozen dataclass with all fields Optional (None = not set), use `__post_init__` with `object.__setattr__` to freeze the `extra` dict into a `types.MappingProxyType`, and convert at storage boundaries using `LLMConfig.from_dict()` / `LLMConfig.to_dict()` class methods.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| dataclasses (stdlib) | Python 3.10+ | LLMConfig frozen dataclass | Already used for LLMOperationConfig, CompileSnapshot, ChatResponse |
| types.MappingProxyType (stdlib) | Python 3.3+ | Immutable dict proxy for `extra` field | Prevents mutation of frozen dataclass's dict field; already in stdlib |
| SQLAlchemy func.json_extract | 2.0+ | JSON field queries in SQLite | Already used in get_by_config; extended with AND and IN |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | - | JSON serialization at boundaries | CommitRow.generation_config_json <-> LLMConfig conversion |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| MappingProxyType for extra | tuple of (key, value) pairs | MappingProxyType is more ergonomic for dict-like access; tuples lose key lookup |
| Frozen dataclass | Pydantic BaseModel | Project decision: LLMOperationConfig is explicitly a dataclass, not Pydantic (10-01-D1) |
| dict extra field | No extra field | Escape hatch is required by spec ("extra dict for provider-specific params") |

**Installation:** No new dependencies. All stdlib + existing SQLAlchemy.

## Architecture Patterns

### LLMConfig Frozen Dataclass Design

```python
# Source: project conventions (protocols.py, models/config.py)
from __future__ import annotations
import types
from dataclasses import dataclass, field, fields

@dataclass(frozen=True)
class LLMConfig:
    """Fully-typed LLM configuration.

    All fields are Optional -- None means "not set / inherit from higher level."
    Used everywhere: operation defaults, call-time overrides, commit-level storage.
    """
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop_sequences: tuple[str, ...] | None = None  # tuple, not list (frozen)
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    top_k: int | None = None
    seed: int | None = None
    extra: dict | None = None  # escape hatch for provider-specific params

    def __post_init__(self) -> None:
        # Freeze extra dict to prevent mutation of frozen dataclass internals
        if self.extra is not None:
            object.__setattr__(self, "extra", types.MappingProxyType(dict(self.extra)))
        # Freeze stop_sequences from list input to tuple
        if self.stop_sequences is not None and not isinstance(self.stop_sequences, tuple):
            object.__setattr__(self, "stop_sequences", tuple(self.stop_sequences))
```

### Storage Boundary Conversion Pattern

The SQLite column remains `generation_config_json: JSON` (a dict). Conversion happens at two boundaries:

1. **CommitRow -> CommitInfo** (read path): `LLMConfig.from_dict(row.generation_config_json)`
2. **CommitInfo/commit() -> CommitRow** (write path): `config.to_dict()` or pass raw dict

```python
@classmethod
def from_dict(cls, d: dict | None) -> LLMConfig | None:
    """Convert a JSON dict from storage to LLMConfig."""
    if d is None:
        return None
    known_fields = {f.name for f in fields(cls)} - {"extra"}
    known = {k: v for k, v in d.items() if k in known_fields}
    extra = {k: v for k, v in d.items() if k not in known_fields}
    # Handle stop_sequences: stored as list in JSON, needs tuple
    if "stop_sequences" in known and isinstance(known["stop_sequences"], list):
        known["stop_sequences"] = tuple(known["stop_sequences"])
    return cls(**known, extra=extra if extra else None)

def to_dict(self) -> dict:
    """Convert LLMConfig to a flat dict for JSON storage."""
    result = {}
    for f in fields(self):
        if f.name == "extra":
            continue
        val = getattr(self, f.name)
        if val is not None:
            # Convert tuple back to list for JSON
            if isinstance(val, tuple):
                val = list(val)
            result[f.name] = val
    if self.extra:
        result.update(self.extra)
    return result
```

### Three-Level Resolution Chain (Preserved from Phase 10)

The existing resolution chain (call > operation > tract default) is preserved. `_resolve_llm_config` changes from building a dict from individual params to merging LLMConfig objects.

```python
def _resolve_llm_config(self, operation: str, *, call_config: LLMConfig | None = None) -> dict:
    """Resolve: call > operation > tract default. Returns kwargs dict for LLM client."""
    # Start with tract default
    base = LLMConfig(model=self._default_model) if self._default_model else LLMConfig()
    # Layer operation config
    op_config = self._operation_configs.get(operation)
    if op_config is not None:
        base = _merge_configs(base, op_config)
    # Layer call config
    if call_config is not None:
        base = _merge_configs(base, call_config)
    return base.to_dict()  # LLM clients expect dict kwargs
```

### Multi-Field AND Query Pattern

```python
# SQLite: multiple json_extract conditions with AND
def get_by_config_multi(
    self, tract_id: str, conditions: list[tuple[str, str, object]]
) -> Sequence[CommitRow]:
    """Query with multiple field conditions (AND semantics)."""
    where_clauses = [CommitRow.tract_id == tract_id]
    for json_path, operator, value in conditions:
        extracted = func.json_extract(CommitRow.generation_config_json, f'$.{json_path}')
        where_clauses.append(ops[operator](extracted, value))
    stmt = select(CommitRow).where(and_(*where_clauses)).order_by(CommitRow.created_at)
    return list(self._session.execute(stmt).scalars().all())
```

### IN Operator Pattern

```python
# SQLite json_extract works with SQLAlchemy .in_()
extracted = func.json_extract(CommitRow.generation_config_json, '$.model')
condition = extracted.in_(["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])
```

### Recommended Project Structure Changes

```
src/tract/
  models/
    config.py          # LLMConfig replaces LLMOperationConfig (same file)
  storage/
    sqlite.py          # get_by_config enhanced with multi-field, IN support
    repositories.py    # CommitRepository.get_by_config signature updated
  engine/
    commit.py          # generation_config: LLMConfig | dict | None at boundary
    cache.py           # generation_configs: tuple[dict, ...] -> internal still dict for perf
    compiler.py        # generation_configs list stays dict internally
  protocols.py         # CommitInfo.generation_config: Optional[LLMConfig], ChatResponse.generation_config: LLMConfig
  tract.py             # _resolve_llm_config, configure_operations, query_by_config
  __init__.py          # Export LLMConfig, remove LLMOperationConfig
```

### Anti-Patterns to Avoid
- **Changing the SQLite schema:** The JSON column stays as-is. Conversion happens at the Python boundary, not in SQL.
- **Making generation_configs in CompileSnapshot use LLMConfig:** The cache layer handles dicts internally for copy-on-output performance. Only the public-facing boundaries (CommitInfo, ChatResponse, CompiledContext.generation_configs) use LLMConfig.
- **Deep-freezing the extra dict:** MappingProxyType is one level deep. For this use case (flat key-value provider params) that's sufficient. Don't add recursive freezing complexity.
- **Breaking backward compatibility in commit():** The `generation_config` parameter on `commit()` should accept both `dict` and `LLMConfig` during transition. Normalize to dict for storage.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Immutable dict for frozen dataclass | Custom FrozenDict class | `types.MappingProxyType` | Stdlib, well-tested, sufficient for one-level freeze |
| JSON field IN queries | Python-side filtering after SELECT | `func.json_extract().in_()` | SQLite handles it natively via json1 extension |
| Multi-field AND queries | Multiple separate queries + intersection | Single SELECT with `and_(*conditions)` | Single query is more efficient and atomic |
| Config merging | Custom merge logic per field | Generic field iteration with `dataclasses.fields()` | Avoids maintaining merge logic for every new field |

**Key insight:** The entire LLMConfig-to-dict and dict-to-LLMConfig conversion is a boundary concern. Internally, storage and cache still use dicts. Only the public API surface changes to typed LLMConfig.

## Common Pitfalls

### Pitfall 1: MappingProxyType Not Hashable
**What goes wrong:** Using `types.MappingProxyType` for `extra` breaks `hash()` on the frozen dataclass if someone tries to use LLMConfig as a dict key or set member.
**Why it happens:** MappingProxyType is not hashable even though the containing dataclass is frozen.
**How to avoid:** Implement `__hash__` on LLMConfig that converts `extra` to a tuple of sorted items for hashing, or use `eq=True, frozen=True` defaults and add a custom `__hash__`.
**Warning signs:** TypeError when putting LLMConfig in a set or using as dict key.

### Pitfall 2: stop_sequences Mutability
**What goes wrong:** If `stop_sequences` is stored as a `list`, users can mutate it through the frozen dataclass.
**Why it happens:** `frozen=True` only prevents field reassignment, not mutation of mutable field values.
**How to avoid:** Use `tuple[str, ...]` for the type, convert list input to tuple in `__post_init__`. JSON storage uses list; Python uses tuple.
**Warning signs:** Tests that modify stop_sequences after creation succeed when they shouldn't.

### Pitfall 3: Cache Copy-on-Output with LLMConfig
**What goes wrong:** If CompiledContext.generation_configs becomes `list[LLMConfig]`, the cache's copy-on-output pattern (`[dict(c) for c in snapshot.generation_configs]`) breaks.
**Why it happens:** The cache currently copies dicts to prevent mutation. LLMConfig is frozen, so no copy needed -- but the cache code must change.
**How to avoid:** Two options: (A) Keep cache internal as dicts, convert to LLMConfig only at the CompiledContext boundary. (B) Change cache to store LLMConfig (frozen = no copy needed). Option A is simpler and touches less code.
**Warning signs:** TypeError in cache.py copy-on-output code.

### Pitfall 4: Backward Compatibility of query_by_config Signature
**What goes wrong:** Changing query_by_config to only accept the new multi-field signature breaks all existing callers.
**Why it happens:** Current signature is `query_by_config(field, operator, value)`.
**How to avoid:** Support BOTH signatures -- single-field (backward compat) and multi-field (new). Detect by checking if first arg is a string (old) or list of conditions (new). Or add new methods while keeping old signature.
**Warning signs:** Existing tests fail with TypeError.

### Pitfall 5: Extra Dict Keys Lost in Round-Trip
**What goes wrong:** Provider-specific params stored in `extra` get lost or duplicated when converting dict -> LLMConfig -> dict.
**Why it happens:** `from_dict()` must correctly separate known fields from extra fields, and `to_dict()` must flatten extra back into the top-level dict.
**How to avoid:** Use `dataclasses.fields()` to get the set of known field names. Everything else goes to `extra`. `to_dict()` merges extra back to top level.
**Warning signs:** Round-trip test `LLMConfig.from_dict(config.to_dict()) == config` fails.

### Pitfall 6: CommitInfo is Pydantic, LLMConfig is Dataclass
**What goes wrong:** Pydantic's `model_dump()` and `model_validate()` don't automatically handle dataclass fields.
**Why it happens:** CommitInfo is a Pydantic BaseModel. If `generation_config` becomes `Optional[LLMConfig]`, Pydantic needs to know how to serialize/deserialize it.
**How to avoid:** Pydantic v2 can handle dataclasses as field types (it auto-wraps them). But test this explicitly. Alternatively, use a Pydantic validator/serializer on the field to handle dict <-> LLMConfig conversion.
**Warning signs:** `CommitInfo.model_dump()` serializes LLMConfig incorrectly; `CommitInfo.model_validate()` fails with dict input.

## Code Examples

### LLMConfig Definition (recommended)

```python
# Source: project patterns from models/config.py and protocols.py
from __future__ import annotations
import types
from dataclasses import dataclass, field, fields as dc_fields

@dataclass(frozen=True)
class LLMConfig:
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop_sequences: tuple[str, ...] | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    top_k: int | None = None
    seed: int | None = None
    extra: dict | None = None

    def __post_init__(self) -> None:
        if self.extra is not None:
            object.__setattr__(self, "extra", types.MappingProxyType(dict(self.extra)))
        if self.stop_sequences is not None and not isinstance(self.stop_sequences, tuple):
            object.__setattr__(self, "stop_sequences", tuple(self.stop_sequences))

    @classmethod
    def from_dict(cls, d: dict | None) -> LLMConfig | None:
        if d is None:
            return None
        known = {f.name for f in dc_fields(cls)} - {"extra"}
        known_kwargs = {}
        extra_kwargs = {}
        for k, v in d.items():
            if k in known:
                known_kwargs[k] = v
            else:
                extra_kwargs[k] = v
        if "stop_sequences" in known_kwargs and isinstance(known_kwargs["stop_sequences"], list):
            known_kwargs["stop_sequences"] = tuple(known_kwargs["stop_sequences"])
        return cls(**known_kwargs, extra=extra_kwargs if extra_kwargs else None)

    def to_dict(self) -> dict:
        result = {}
        for f in dc_fields(self):
            if f.name == "extra":
                continue
            val = getattr(self, f.name)
            if val is not None:
                if isinstance(val, tuple):
                    val = list(val)
                result[f.name] = val
        if self.extra:
            result.update(dict(self.extra))
        return result

    def non_none_fields(self) -> dict:
        """Return dict of non-None typed fields (excludes extra). For query building."""
        result = {}
        for f in dc_fields(self):
            if f.name == "extra":
                continue
            val = getattr(self, f.name)
            if val is not None:
                result[f.name] = val
        return result
```

### Multi-Field AND Query at Repository Level

```python
# Source: extending existing get_by_config in storage/sqlite.py
def get_by_config(
    self, tract_id: str, json_path: str, operator: str, value: object
) -> Sequence[CommitRow]:
    """Original single-field query (backward compatible)."""
    return self.get_by_config_multi(tract_id, [(json_path, operator, value)])

def get_by_config_multi(
    self, tract_id: str, conditions: list[tuple[str, str, object]]
) -> Sequence[CommitRow]:
    """Multi-field AND query."""
    where_clauses = [CommitRow.tract_id == tract_id]
    ops = {
        "=": lambda e, v: e == v,
        "!=": lambda e, v: e != v,
        ">": lambda e, v: e > v,
        "<": lambda e, v: e < v,
        ">=": lambda e, v: e >= v,
        "<=": lambda e, v: e <= v,
        "in": lambda e, v: e.in_(v),
    }
    for json_path, operator, value in conditions:
        if operator not in ops:
            raise ValueError(f"Unsupported operator: {operator}")
        extracted = func.json_extract(
            CommitRow.generation_config_json, f'$.{json_path}'
        )
        where_clauses.append(ops[operator](extracted, value))
    stmt = (
        select(CommitRow)
        .where(and_(*where_clauses))
        .order_by(CommitRow.created_at)
    )
    return list(self._session.execute(stmt).scalars().all())
```

### Whole-Config Query at Facade Level

```python
# Source: tract.py query_by_config enhanced signature
def query_by_config(
    self,
    field_or_config: str | LLMConfig,
    operator: str | None = None,
    value: object = None,
    *,
    conditions: list[tuple[str, str, object]] | None = None,
) -> list[CommitInfo]:
    """Query commits by generation config.

    Supports three calling patterns:
    1. Single field: query_by_config("model", "=", "gpt-4o")
    2. Multi-field:  query_by_config(conditions=[("model", "=", "gpt-4o"), ("temperature", ">", 0.5)])
    3. Whole config: query_by_config(LLMConfig(model="gpt-4o", temperature=0.7))
       -> finds commits matching ALL non-None fields with "=" semantics
    """
    if isinstance(field_or_config, LLMConfig):
        # Convert non-None fields to AND conditions
        conds = [(k, "=", v) for k, v in field_or_config.non_none_fields().items()]
        if not conds:
            return []
        rows = self._commit_repo.get_by_config_multi(self._tract_id, conds)
    elif conditions is not None:
        rows = self._commit_repo.get_by_config_multi(self._tract_id, conditions)
    else:
        rows = self._commit_repo.get_by_config_multi(
            self._tract_id, [(field_or_config, operator, value)]
        )
    return [self._commit_engine._row_to_info(row) for row in rows]
```

### Config Merging Helper

```python
def _merge_configs(base: LLMConfig, override: LLMConfig) -> LLMConfig:
    """Merge two LLMConfigs. Override's non-None fields win."""
    merged = {}
    for f in dc_fields(LLMConfig):
        if f.name == "extra":
            continue
        override_val = getattr(override, f.name)
        base_val = getattr(base, f.name)
        merged[f.name] = override_val if override_val is not None else base_val
    # Merge extra dicts
    base_extra = dict(base.extra) if base.extra else {}
    override_extra = dict(override.extra) if override.extra else {}
    merged_extra = {**base_extra, **override_extra}
    return LLMConfig(**merged, extra=merged_extra if merged_extra else None)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `LLMOperationConfig` (4 fields + extra_kwargs) | `LLMConfig` (9 typed fields + extra) | Phase 11 | Single class everywhere; typed access |
| `generation_config: Optional[dict]` on CommitInfo | `generation_config: Optional[LLMConfig]` | Phase 11 | Typed access: `.model` instead of `.get("model")` |
| `query_by_config(field, op, value)` single-field | Multi-field AND, IN operator, whole-config | Phase 11 | Rich querying without multiple calls |
| `extra_kwargs: dict` (untyped overflow) | `extra: dict` (same concept, renamed) | Phase 11 | Consistent naming with new class |

**Deprecated/outdated:**
- `LLMOperationConfig`: Replaced entirely by `LLMConfig`. All imports, type hints, and isinstance checks must be updated.
- `extra_kwargs` field name: Becomes `extra` on LLMConfig.
- `response.generation_config.get("model")`: Becomes `response.generation_config.model`.

## Migration Surface Analysis

### Files That Must Change (by category)

**Definition (1 file):**
- `src/tract/models/config.py` -- Replace LLMOperationConfig with LLMConfig

**Public API / exports (2 files):**
- `src/tract/__init__.py` -- Export LLMConfig, remove LLMOperationConfig
- `src/tract/models/__init__.py` -- May need LLMConfig export

**Facade (1 file):**
- `src/tract/tract.py` -- _resolve_llm_config, configure_operations, query_by_config, generate, chat, merge, compress, orchestrate, Tract.open() signature

**Domain models (2 files):**
- `src/tract/models/commit.py` -- CommitInfo.generation_config type
- `src/tract/protocols.py` -- ChatResponse.generation_config type, CompiledContext.generation_configs type

**Storage layer (2 files):**
- `src/tract/storage/repositories.py` -- CommitRepository.get_by_config signature
- `src/tract/storage/sqlite.py` -- SqliteCommitRepository.get_by_config + new get_by_config_multi

**Engine layer (3 files):**
- `src/tract/engine/commit.py` -- generation_config parameter type (accept both dict and LLMConfig)
- `src/tract/engine/cache.py` -- copy-on-output for generation_configs
- `src/tract/engine/compiler.py` -- generation_configs list construction

**Operations (4 files):**
- `src/tract/operations/merge.py` -- generation_config handling
- `src/tract/operations/rebase.py` -- generation_config handling
- `src/tract/operations/compression.py` -- generation_config handling
- `src/tract/operations/diff.py` -- generation_config_changes

**Other consumers (3+ files):**
- `src/tract/toolkit/definitions.py` -- generation_config field
- `src/tract/llm/protocols.py` -- generation_config field
- `src/tract/operations/session_ops.py`, `spawn.py` -- generation_config from rows

**Cookbook (3 files):**
- `cookbook/01_foundations/first_conversation.py`
- `cookbook/01_foundations/atomic_batch.py`
- `cookbook/01_foundations/token_budget_guardrail.py`

**Tests (2+ files):**
- `tests/test_operation_config.py` -- Rename to test_llm_config.py, all LLMOperationConfig -> LLMConfig
- `tests/test_tract.py` -- query_by_config tests
- New tests for multi-field, IN, whole-config queries

### Total estimated touch points: ~20 files

## Open Questions

1. **CompiledContext.generation_configs type change**
   - What we know: Currently `list[dict]`. Phase spec says CommitInfo changes to LLMConfig.
   - What's unclear: Should CompiledContext.generation_configs also become `list[LLMConfig | None]`? This affects the cache layer significantly.
   - Recommendation: Change CompiledContext.generation_configs to `list[LLMConfig | None]` for consistency. The cache can convert at the `to_compiled()` boundary (already a conversion point). Internally the cache stores dicts.

2. **Pydantic + Dataclass interop for CommitInfo**
   - What we know: CommitInfo is a Pydantic BaseModel. LLMConfig is a frozen dataclass. Pydantic v2 supports dataclass fields.
   - What's unclear: Does Pydantic v2 auto-serialize/deserialize LLMConfig correctly when it's a field on CommitInfo? Does `model_dump()` produce a dict?
   - Recommendation: Test explicitly. If Pydantic doesn't handle it cleanly, add a `model_validator` on CommitInfo to convert dict -> LLMConfig on input, and a `model_serializer` for output. LOW confidence until tested.

3. **query_by_config signature backward compatibility**
   - What we know: Current callers use `(field, operator, value)`. New API needs multi-field and whole-config.
   - What's unclear: Whether to overload one method or add separate methods.
   - Recommendation: Overload with type checking on first argument. `str` = old single-field, `LLMConfig` = whole-config, `conditions=` kwarg = multi-field. This preserves all existing callers.

## Sources

### Primary (HIGH confidence)
- `src/tract/models/config.py` -- Current LLMOperationConfig definition
- `src/tract/protocols.py` -- Current ChatResponse, CompiledContext, CompileSnapshot
- `src/tract/models/commit.py` -- Current CommitInfo with generation_config: Optional[dict]
- `src/tract/storage/sqlite.py` -- Current get_by_config with func.json_extract
- `src/tract/engine/cache.py` -- Cache copy-on-output patterns for generation_configs
- `src/tract/tract.py` -- _resolve_llm_config, configure_operations, query_by_config
- `tests/test_operation_config.py` -- Full test suite for current LLMOperationConfig
- SQLite JSON1 documentation (https://sqlite.org/json1.html) -- json_extract with IN operator

### Secondary (MEDIUM confidence)
- Python dataclasses documentation -- frozen=True, __post_init__, object.__setattr__
- types.MappingProxyType -- immutable dict proxy behavior

### Tertiary (LOW confidence)
- Pydantic v2 + stdlib dataclass interop -- needs validation through testing

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all stdlib, no new dependencies
- Architecture: HIGH -- boundary conversion pattern is well-established in codebase
- Pitfalls: HIGH -- identified from direct code analysis of ~20 affected files
- Query patterns: HIGH -- SQLite json_extract + IN verified via official docs
- Pydantic interop: LOW -- needs testing; Pydantic v2 supports dataclasses but edge cases possible

**Research date:** 2026-02-19
**Valid until:** 30 days (stable domain, no external dependency changes)
