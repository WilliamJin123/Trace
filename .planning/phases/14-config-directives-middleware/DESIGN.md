# Phase 14: Config + Directives + Middleware

Replace the rule engine (`src/tract/rules/`) with three focused concepts that cover the
same capabilities with ~90% less code and a cleaner mental model.

**Guiding principle:** The LLM is the best fuzzy interpreter. Compile behavioral
instructions into context (directives) and let the LLM follow them. The system handles
only deterministic enforcement (config constraints, middleware blocking).

---

## Problem Statement

The rule system (`t.rule()`) conflates three concerns into one abstraction:

1. **Config** (key-value settings) -- `trigger="active"` + `set_config` action
2. **Behavioral instructions** (LLM-facing) -- no clean home; hacked via LLM conditions/actions
3. **Event handling** (blocking, validation) -- `trigger="commit"/"compress"/etc.` + condition/action DSL

This produced a 1,290-line engine with a 4-stage pipeline (gates/work/handoff/post),
recursion guards, deferred actions, 7 trigger types, 7 condition evaluators, 7 action
handlers, and a per-instance registry -- all hidden behind a simple `t.rule()` API.

Rules are also commits with `compilable=False`, breaking the mental model that
"commits = content in the context window."

---

## Solution: Three Concepts

### 1. Config (`content_type="config"`, NOT compiled)

Key-value settings stored as commits. The system reads them; the LLM never sees them.

```python
t.configure(model="gpt-4o", temperature=0.7)
t.configure(auto_compress_threshold=4000)
t.configure(compact_tools={"search_api": 500})

t.get_config("model")        # "gpt-4o" (DAG precedence: closer to HEAD wins)
t.get_all_configs()           # {"model": "gpt-4o", "temperature": 0.7, ...}
```

### 2. Directives (named `InstructionContent`, compiled into LLM context)

Standing behavioral instructions the LLM reads and follows. Same-name directives
use DAG precedence (closer to HEAD wins; compiler deduplicates).

```python
t.directive("review-protocol", "When reviewing: analyze, critique, suggest")
t.directive("safety", "Never include API keys in responses")

# Override: same name, closer to HEAD wins
t.directive("review-protocol", "New protocol: test, review, approve")

# Compressible directive (not pinned)
t.directive("temp-tone", "Use formal tone", priority=Priority.NORMAL)
```

### 3. Middleware (Python callbacks, NOT in DAG)

Event handlers registered in Python. Fire synchronously at operation boundaries.

```python
t.use("pre_commit", my_validator)       # can block with BlockedError
t.use("post_commit", my_logger)
t.use("pre_compile", my_filter)
t.use("pre_compress", my_guard)
t.use("pre_transition", my_gate)

def my_validator(ctx: MiddlewareContext) -> None:
    if ctx.pending and getattr(ctx.pending, "token_count", 0) > 1000:
        raise BlockedError("pre_commit", "Too large")
```

---

## Content Type Changes

### Modified: InstructionContent

```python
class InstructionContent(BaseModel):
    content_type: Literal["instruction"] = "instruction"
    text: str
    name: str | None = None       # NEW: enables override-by-name (directive mode)
```

When `name` is set, the compiler deduplicates: same name -> closest to HEAD wins.
When `name` is None, behavior is identical to today.

### New: ConfigContent

```python
class ConfigContent(BaseModel):
    model_config = ConfigDict(frozen=True)
    content_type: Literal["config"] = "config"
    settings: dict[str, Any]
```

ContentTypeHints:
```python
"config": ContentTypeHints(
    default_priority="normal",
    default_role="system",
    compression_priority=85,
    compilable=False,
)
```

### Deleted: RuleContent

Removed from discriminated union, BUILTIN_CONTENT_TYPES, BUILTIN_TYPE_HINTS, and all
exports. **Breaking change**: existing tracts with `content_type="rule"` blobs in the
DAG will fail deserialization. No migration — users must recreate tracts.

---

## Tract API Changes

### New Methods

```python
def configure(self, **settings: Any) -> CommitInfo:
    """Commit config to DAG. Well-known keys type-checked and enforced.

    Raises ValueError if a well-known key has the wrong type (e.g.
    temperature="hot"). Unknown keys pass through without validation.
    None values are valid (unset semantics).
    """

def directive(
    self,
    name: str,
    text: str,
    *,
    priority: Priority | None = None,   # default: PINNED
    message: str | None = None,
    tags: list[str] | None = None,
) -> CommitInfo:
    """Commit a named standing instruction (compiled, override-by-name)."""

def use(self, event: str, handler: Callable) -> str:
    """Register middleware. Returns handler ID for removal."""

def remove_middleware(self, handler_id: str) -> None:
    """Remove a registered middleware handler."""

def get_all_configs(self) -> dict[str, Any]:
    """Resolve all config key-value pairs from DAG."""
```

### Modified Methods

```python
def get_config(self, key: str, default: Any = None) -> Any:
    """Same signature, backed by ConfigIndex instead of RuleIndex."""

def transition(
    self,
    target: str,
    *,
    handoff: Literal["full", "summary", "none"] | str = "none",
) -> CommitInfo | None:
    """Simplified: middleware for gates, parameter for handoff mode."""
```

### Deleted Methods

```python
t.rule(...)                     # -> t.configure() / t.directive() / t.use()
t.register_condition(...)       # -> gone (no condition DSL)
t.register_action(...)          # -> gone (no action DSL)
t.register_metric(...)          # -> gone (custom logic goes in middleware)
t.rule_index                    # -> t._config_index (internal)
t._rule_engine                  # -> gone
t._fire_rules(...)              # -> t._run_middleware() + config enforcement
t._fire_transition_rules(...)   # -> t._run_middleware("pre_transition")
```

---

## Blocking Semantics

Two mechanisms, both raising `BlockedError`:

### A. Config enforcement (built-in, deterministic)

```python
# In commit() -- before storing:
max_tokens = self.get_config("max_commit_tokens")
if max_tokens is not None and info.token_count > int(max_tokens):
    raise BlockedError("pre_commit", f"Exceeds max_commit_tokens ({max_tokens})")
```

### B. Middleware (custom, Python-side)

```python
t.use("pre_commit", lambda ctx: raise_if_too_large(ctx))
```

### Exception

```python
class BlockedError(TraceError):
    """An operation was blocked by config enforcement or middleware."""
    def __init__(self, event: str, reasons: list[str] | str):
        self.event = event
        self.reasons = reasons if isinstance(reasons, list) else [reasons]
```

Replaces `BlockedByRuleError`. Loop catches it identically:
```python
except BlockedError as e:
    return LoopResult("blocked", str(e), ...)
```

---

## Well-Known Config Keys

| Key | Type | Enforced in | Behavior |
|-----|------|-------------|----------|
| `model` | `str` | LLM calls | Passed to client |
| `temperature` | `float` | LLM calls | Passed to client |
| `max_tokens` | `int` | LLM calls | Passed to client |
| `max_commit_tokens` | `int` | `commit()` | Raises `BlockedError` |
| `auto_compress_threshold` | `int` | Loop post-step | Auto-compresses |
| `compact_tools` | `dict[str,int]` | Loop post-tool | APPEND + EDIT compaction |
| `compile_strategy` | `str` | Loop pre-compile | Strategy override (loop-only; direct `compile()` ignores) |
| `compile_strategy_k` | `int` | Loop pre-compile | K override (loop-only; direct `compile()` ignores) |
| `handoff_summary_k` | `int` | `transition()` | Adaptive K for summary handoff (default 3) |

Unknown keys pass through -- custom code reads them via `get_config()`.
LLMs can set any key via tool calls to `t.configure()`.

**Unset semantics**: `t.configure(model=None)` unsets the key. `ConfigIndex.get()`
treats `None` values as "not set" and returns the default. This allows reverting
a config without needing to know the original value.

---

## Middleware Specification

### Events

| Event | Fires | Context |
|-------|-------|---------|
| `pre_commit` | Before commit stored | commit=None, pending=content payload |
| `post_commit` | After commit stored | commit=CommitInfo |
| `pre_compile` | Before compilation | commit=None |
| `pre_compress` | Before compression | commit=None |
| `pre_merge` | Before merge | commit=None |
| `pre_gc` | Before GC | commit=None |
| `pre_transition` | Before branch switch | target=branch_name |
| `post_transition` | After branch switch | target=branch_name |

### MiddlewareContext

```python
@dataclass(frozen=True)
class MiddlewareContext:
    event: str
    commit: CommitInfo | None
    tract: Tract
    branch: str
    head: str
    target: str | None = None     # for transition events
    pending: BaseModel | dict | None = None  # content payload for pre_* events
```

### Execution Rules

1. **Ordering**: Sequential, registration order. First registered runs first.
2. **Blocking**: Raise `BlockedError` to abort the operation (pre_* events only).
   Remaining handlers skipped. `BlockedError` in post_* events is a programming
   error and propagates as an uncaught exception.
3. **Errors**: Non-BlockedError exceptions propagate (operation aborts with error).
4. **Recursion guard**: `_in_middleware_events: set[str]`. Same-event re-entry is
   skipped (prevents A→B→A indirect loops). Cross-event middleware fires normally
   (pre_commit handler that calls compile() will trigger pre_compile middleware).

### Implementation

```python
def _run_middleware(self, event: str, **kwargs: Any) -> None:
    if event in self._in_middleware_events:
        return  # recursion guard (prevents A->B->A indirect re-entry)
    handlers = self._middleware.get(event, [])
    if not handlers:
        return
    self._in_middleware_events.add(event)
    try:
        ctx = MiddlewareContext(
            event=event,
            commit=kwargs.get("commit"),
            tract=self,
            branch=self.current_branch or "",
            head=self.head or "",
            target=kwargs.get("target"),
            pending=kwargs.get("pending"),
        )
        for _id, fn in handlers:
            fn(ctx)
    finally:
        self._in_middleware_events.discard(event)
```

---

## ConfigIndex (replaces RuleIndex)

```python
class ConfigIndex:
    """Per-key config resolution from DAG ancestry.

    Walks ancestry, collects content_type="config" commits, resolves
    per-key with DAG precedence (closer to HEAD wins).
    """

    _settings: dict[str, tuple[Any, int]]   # key -> (value, dag_distance)
    _stale: bool

    @classmethod
    def build(cls, commit_repo, blob_repo, head_hash, *, parent_repo=None):
        # Uses walk_ancestry (moved from rules/ancestry.py to operations/ancestry.py)
        # Filters content_type="config", parses settings dict, resolves per-key

    def get(self, key, default=None) -> Any
    def get_all(self) -> dict[str, Any]
    def invalidate(self) -> None
```

Approximately 60 lines. Reuses the generic `walk_ancestry()` function.

---

## Compiler Changes: Directive Dedup

In `_build_effective_commits()`, after EDIT resolution, before message building:

```python
# Deduplicate named InstructionContent (directive override-by-name)
# Only deserialize instruction-type commits (check content_type from metadata first)
seen_names: dict[str, int] = {}     # name -> index of closest-to-HEAD
remove_indices: set[int] = set()
for i in range(len(effective) - 1, -1, -1):   # walk HEAD -> root
    if effective[i].content_type != "instruction":
        continue
    blob = self._blob_repo.get(effective[i].content_hash)
    payload = json.loads(blob.payload_json)
    name = payload.get("name")
    if name:
        if name in seen_names:
            remove_indices.add(i)
        else:
            seen_names[name] = i
effective = [c for i, c in enumerate(effective) if i not in remove_indices]
```

~15 lines. Cache invalidation already handled (new commits invalidate parent's cache).

---

## Tool Auto-Compaction

### Flow

```
1. t.configure(compact_tools={"search_api": 500})        <- stored in DAG
2. Loop commits tool result (APPEND, full content)
3. Loop checks get_config("compact_tools"):
   tool_name in config and token_count > threshold?
   -> t.compress_tool_calls(name=tool_name, target_tokens=threshold)  # existing method
   -> EDIT commit over original (compacted version)
4. compile() returns EDIT version; original inspectable in history
```

### In run_loop()

```python
# After committing a tool result (tc_name = tc["name"] from tool call dict):
compact_config = tract.get_config("compact_tools")
if compact_config and tc_name in compact_config:
    threshold = compact_config[tc_name]
    if result_ci.token_count > threshold:
        try:
            tract.compress_tool_calls(name=tc_name, target_tokens=threshold)
        except (CompressionError, ValueError):
            pass   # no LLM or compaction failed -- keep original
```

### Edge Cases

- **No LLM configured**: Skip auto-compaction, log warning. Original stays.
- **In batch() context**: Defer to after batch (same as cache updates).
- **compress_tool_calls() failure**: Swallow error, keep original. Non-fatal.

---

## Transition (simplified)

```python
def transition(
    self,
    target: str,
    *,
    handoff: Literal["full", "summary", "none"] | str = "none",
) -> CommitInfo | None:
    """Transition to target branch with optional handoff.

    1. Run pre_transition middleware (can block)
    2. Build handoff payload if requested
    3. Switch to / create target branch
    4. Commit handoff on target

    Args:
        target: Branch name.
        handoff: "full" (compile all), "summary" (adaptive), "none",
                 or custom text string.
    """
    self._run_middleware("pre_transition", target=target)

    payload = None
    if handoff == "full":
        payload = str(self.compile().to_dicts())
    elif handoff == "summary":
        k = self.get_config("handoff_summary_k") or 3
        payload = str(self.compile(strategy="adaptive", strategy_k=k).to_dicts())
    elif handoff != "none":
        payload = handoff

    existing = {b.name for b in self.list_branches()}
    if target not in existing:
        from tract.operations.branch import create_branch
        create_branch(target, self._tract_id, self._ref_repo, self._commit_repo)
        self._session.commit()
    self.switch(target)

    result = None
    if payload:
        result = self.system(f"Context handoff:\n{payload}", message=f"handoff to {target}")

    self._run_middleware("post_transition", target=target)
    return result
```

Toolkit `transition` tool updated to pass `handoff=` parameter.

---

## Deletion Inventory

### Files Deleted

| File | Lines | Notes |
|------|-------|-------|
| `src/tract/rules/engine.py` | ~248 | Replaced by _run_middleware (~25 lines) |
| `src/tract/rules/actions.py` | ~246 | 7 action handlers -> config enforcement |
| `src/tract/rules/conditions.py` | ~233 | Condition DSL -> config well-known keys |
| `src/tract/rules/registries.py` | ~100 | No DSL -> no registry |
| `src/tract/rules/models.py` | ~80 | RuleEntry/EvalContext -> MiddlewareContext |
| `src/tract/rules/index.py` | ~186 | Replaced by ConfigIndex (~60 lines) |
| `src/tract/rules/config.py` | ~40 | Folded into ConfigIndex |
| `src/tract/rules/__init__.py` | ~30 | Package deleted |
| `src/tract/hooks/__pycache__/` | -- | Stale .pyc from removed hook system |

### Files Moved

| From | To |
|------|-----|
| `src/tract/rules/ancestry.py` | `src/tract/operations/ancestry.py` |

### Tract State Removed

```python
# These fields/properties deleted from Tract.__init__ and body:
self._rule_index: RuleIndex | None
self._rule_eval_depth: int
self.__rule_engine: RuleEngine | None
self._registry: Registry

# Replaced by:
self._config_index: ConfigIndex | None
self._middleware: dict[str, list[tuple[str, Callable]]]   # event -> [(id, handler)]
self._in_middleware_events: set[str]                      # recursion guard
```

### Exports Removed from __init__.py

```python
# Rule engine (11 symbols):
RuleEntry, EvalContext, ActionResult, EvalResult,
RuleIndex, RuleEngine, evaluate_condition,
BUILTIN_CONDITIONS, BUILTIN_ACTIONS,
resolve_config, resolve_all_configs, Registry

# Content type:
RuleContent
```

### Exports Added to __init__.py

```python
ConfigContent, ConfigIndex, MiddlewareContext, BlockedError
```

---

## Test Migration

### Delete (rule-specific tests)

- `tests/test_rule_models.py`
- `tests/test_rule_config.py`
- `tests/test_rule_api.py`
- `tests/test_conditions.py`
- `tests/test_rule_index.py`
- `tests/test_rule_engine.py`
- `tests/test_rule_engine_integration.py`
- `tests/test_rule_actions.py`
- `tests/test_registries.py`
- `tests/test_llm_conditions.py`

### New Tests

- `tests/test_config_content.py` -- ConfigContent model, ConfigIndex build/get/invalidate
- `tests/test_directives.py` -- named InstructionContent, compiler dedup, DAG precedence
- `tests/test_middleware.py` -- registration, ordering, blocking, recursion guard, removal
- `tests/test_configure_api.py` -- t.configure(), t.get_config(), well-known key enforcement
- `tests/test_transition_simplified.py` -- middleware gates, handoff modes

### Modify

- `tests/test_loop.py` -- `BlockedByRuleError` -> `BlockedError`, config strategy reads
- `tests/test_tract.py` -- remove rule method tests, add configure/directive tests
- Any test importing `RuleContent` or rule symbols

---

## Cookbook Migration

### Rewrite

| File | Current | New |
|------|---------|-----|
| `getting_started/02_rules.py` | Rules demo | Config + Directives demo |
| `rules/01_config_and_strategy.py` | Config rules | `t.configure()` examples |
| `rules/02_event_automation.py` | Event rules | Middleware examples |
| `rules/03_gates_and_transitions.py` | Transition rules | `t.transition(handoff=)` + middleware |
| `rules/04_data_preservation.py` | Preserve rules | Priority.PINNED + config |
| `rules/05_custom_extensions.py` | Custom registries | Middleware escape hatch |
| `workflows/01_coding_assistant.py` | Rule-based workflow | Directives + middleware |
| `workflows/02_research_pipeline.py` | Rule-based workflow | Directives + config |
| `workflows/03_customer_support.py` | Rule-based workflow | Directives + config |
| `agent/05_staged_workflow.py` | Transition gates | Middleware + transition |
| `agent/07_quality_gates.py` | Rule gates | Middleware |

### Rename Directory

`cookbook/rules/` -> `cookbook/config_and_middleware/` (or fold into getting_started/)

---

## How Requirements Map

| Capability | Before (rules) | After |
|------------|----------------|-------|
| LLM-defined workflows | Possible via create_rule DSL (high friction) | `t.directive()` -- LLM commits protocol, reads it next iteration |
| Deterministic validation | condition DSL + block action | `t.configure(max_commit_tokens=500)` |
| Fuzzy LLM interventions | LLM condition (separate LLM call) | `t.directive()` -- LLM self-regulates |
| User interventions | Not clean | Middleware + directives |
| Protocols / retries | Not supported | Directives (LLM follows) + config (retry params) |
| Auto-compress | operation action in rule engine | `t.configure(auto_compress_threshold=N)` |
| Tool compaction | manual compress_tool_calls() calls | `t.configure(compact_tools={"x": N})` |
| Branch-portable behavior | Rules travel in DAG | Config + directives travel in DAG |
| Event blocking | _fire_rules + BlockedByRuleError | Config enforcement + middleware + BlockedError |
| Stage transitions | transition() + rule gates/handoff | transition(handoff=) + middleware |
| Custom logic | Registry (conditions/actions/metrics) | Python middleware (full power, no DSL) |

---

## Compiled Context (what the LLM sees)

```
+-- Directives (named instructions, deduplicated, system role) -----+
| [directive: review-protocol] "New protocol: test, review, approve" |
| [directive: safety] "Never include API keys in responses"          |
+-- Conversation (chronological) -----------------------------------+
| [system] "You are a coding assistant"                              |
| [user] "Review this PR"                                           |
| [assistant] "Here's my analysis..."                                |
+-------------------------------------------------------------------+

NOT in compiled context: ConfigContent commits
```

---

## Execution Order

1. Content types: add ConfigContent, add name to InstructionContent, remove RuleContent
2. ConfigIndex: new class (reuses walk_ancestry), wire to Tract
3. Tract API: configure(), directive(), use(), remove_middleware(), get_all_configs()
4. Blocking: BlockedError, config enforcement in commit/compile/compress/merge/gc
5. Middleware pipeline: _run_middleware(), MiddlewareContext
6. Compiler: directive dedup in _build_effective_commits()
7. Transition: simplify to middleware + handoff parameter
8. Loop: auto-compaction, BlockedError catch, config strategy reads
9. Toolkit: update transition tool, keep get_config tool
10. Delete: rules/ package (except ancestry.py -> operations/), rule state on Tract
11. Exports: update __init__.py
12. Tests: delete rule tests, write new test suite
13. Cookbooks: rewrite all 11 affected files
