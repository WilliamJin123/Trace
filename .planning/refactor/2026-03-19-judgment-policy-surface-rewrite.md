# Refactor: Judgment/Policy Primitives + Surface Rewrite

**Date:** 2026-03-19
**Commits:** `4dfd342` through `867ac9d` (6 commits)
**Test baseline:** 3095 before, 3080 after (15 removed for deleted internals)

---

## 1. Motivation (Adversarial Audit Findings)

An adversarial architectural audit identified these design tensions:

1. **Five parallel LLM decision systems** (gate, maintain, intelligence, autonomous, routing) all implementing the same pattern independently: build manifest -> call LLM -> parse JSON -> fail-open.
2. **God object**: Tract had ~79 public methods + 16 manager properties with unclear delegation boundaries.
3. **Deterministic/semantic dichotomy**: Every context operation sits on a spectrum from rule-based to LLM-judged, but the codebase had no unified way to express this.
4. **Git metaphor leakage**: Some terminology created false expectations (e.g., `merge` can be blocked by an LLM gate, unlike git).
5. **Configuration scatter**: 6+ config models (TractConfig, OperationConfigs, OperationClients, OperationPrompts, RetryConfig, ToolSummarizationConfig) with unclear precedence.

The user confirmed: tract IS meant for LLMs/agents (not an identity crisis), the god object was unintentional, and a unified LLM primitive was the goal.

## 2. Design Decisions

### 2.1 Judgment Primitive
A **Judgment** is a typed request for LLM evaluation of context state:
- `instructions: str` -- what to evaluate
- `response_model: type[BaseModel]` -- Pydantic model for expected output
- `context: ContextView` -- what context to show the LLM
- `evaluate(tract) -> JudgmentResult` -- sync evaluation
- `aevaluate(tract) -> JudgmentResult` -- async evaluation

Preset response models: GateVerdict, MaintenancePlan, MaintenanceAction, SelectionResult, DedupGroups, SplitPlan, BooleanDecision, RouteSelection.

### 2.2 Policy Primitive
A **Policy** combines condition + strategy, where either can be deterministic (callable) or semantic (Judgment):

```
                    Deterministic Strategy    Semantic Strategy
Det. Condition      tokens>90% -> drop low    tokens>90% -> LLM summarize
Sem. Condition      LLM "redundant?" -> dedup  LLM "done?" -> LLM summarize
```

PolicyEngine replaces MiddlewareManager conceptually but coexists with it (middleware handlers stay for SemanticGate/SemanticMaintainer backwards compat).

### 2.3 Surface Rewrite
From 16 manager properties to 7 focused sub-objects + ~35 direct methods:

**Removed properties (13):** branches, search, annotations, tags, compression, llm, toolkit, intelligence, routing, spawn (as property), tools (old ToolManager accessor).

**Kept sub-objects (7):** config, middleware, policies (new), runtime (new), tools, persistence, templates.

**Rationale for 7 instead of 3:** tools (7 specialized methods), persistence (8+ methods), and templates (5+ methods) each have enough specialized API surface that flattening them onto Tract would re-create the god object. The other 10 managers were genuinely thin enough to flatten.

### 2.4 Decisions NOT Made (Deferred)
- **OperationConfigs/OperationClients/OperationPrompts removal**: Judgments carry their own config, making per-operation config objects redundant. But removing them requires deeper changes to the config system, LLMState, and Tract.open(). Deferred.
- **Middleware -> Policy full migration**: SemanticGate and SemanticMaintainer are middleware handlers (take MiddlewareContext). Migrating them to Policy (takes PolicyContext) requires changing their interfaces. Deferred -- both systems coexist.
- **Git terminology renaming**: "commit" -> "trace", "branch" -> something else. Lower priority, no implementation started.
- **Loop ownership decision**: Whether tract should own the agent loop or be a context layer that any loop uses. Discussed but not resolved.

## 3. What Was Built

### Phase 1: Primitives (commits `4dfd342`, `17cd59c`)
- **New file:** `src/tract/judgment.py` (~350 lines)
  - Judgment dataclass with evaluate()/aevaluate()
  - 8 preset response models (all with `extra="allow"` for LLM flexibility)
  - _extract_json() for robust JSON extraction from messy LLM output
  - _schema_instructions() for generating response format prompts from Pydantic schemas
- **New file:** `src/tract/policy.py` (~300 lines)
  - Policy dataclass with condition/strategy (Callable or Evaluable)
  - PolicyEngine with event bindings, priority ordering, recursion guard
  - Convenience factories: always, never, token_ratio_above, commit_count_above, block_with_reason, pass_through

### Phase 2: Internal Refactoring (commits `7d089af`, `4dfd342`, `17cd59c`)
All 5 semantic systems refactored to use Judgment internally:
- **gate.py**: `__call__` creates Judgment(response_model=GateVerdict), evaluates, converts to GateResult. Removed: _parse_response (JSON+regex), _build_messages, _build_manifest (instance method).
- **maintain.py**: Single-pass uses Judgment(response_model=MaintenancePlan). Two-pass uses PeekOrActions model for first pass. Empty peek list now short-circuits (1 call instead of 2). Removed: _build_messages, _build_peek_messages, _build_enriched_messages, _safe_llm_call/_safe_llm_call_raw.
- **intelligence.py**: cherry_pick/deduplicate create Judgments with SelectionResult/DedupGroups models. Custom manifest builder kept (provides content previews ContextView doesn't).
- **autonomous.py**: auto_split/rebase/branch create Judgments with SplitPlan/BooleanDecision models. System prompts updated for new response schema.
- **routing.py**: SemanticRouter creates Judgment with RouteSelection model. Fuzzy fallback preserved.

### Phase 3: Wiring (commit `7d089af`)
- `t.policies` property exposes PolicyEngine
- `t.evaluate(judgment)` / `t.aevaluate(judgment)` for one-shot evaluations
- PolicyEngine fires AFTER middleware handlers on events (via MiddlewareManager._run integration)
- 20 new public exports in `__init__.py`

### Phase 4: Surface Rewrite (commits `743412e`, `867ac9d`)
- Added ~35 direct methods to Tract delegating to internal managers
- Created `_Runtime` class wrapping LLMManager + ToolkitManager
- Removed 13 old manager properties
- Migrated 61 test files (~2000 replacements), 19 cookbook files, 11 source files
- Fixed internal references in: context_view.py, session.py, loop.py, toolkit/definitions.py, toolkit/discovery.py, cli.py, autonomous.py, gate.py, intelligence.py, maintain.py, policy.py

## 4. API Mapping Reference

```
OLD                              NEW
t.branches.create(name)          t.branch(name)
t.branches.checkout(name)        t.checkout(name)
t.branches.switch(name)          t.switch(name)
t.branches.list()                t.list_branches()
t.branches.delete(name)          t.delete_branch(name)
t.branches.resolve(ref)          t.resolve(ref)
t.branches.reset(hash)           t.reset(hash)
t.search.find(...)               t.find(...)
t.search.find_one(...)           t.find_one(...)
t.search.log(...)                t.log(...)
t.search.status()                t.status()
t.search.diff(...)               t.diff(...)
t.search.compare(...)            t.compare(...)
t.search.health()                t.health()
t.search.get_content(hash)       t.get_content(hash)
t.search.get_commit(hash)        t.get_commit(hash)
t.search.skipped()               t.skipped()
t.search.pinned()                t.pinned()
t.search.manifest()              t.manifest()
t.annotations.set(hash, pri)     t.annotate(hash, pri)
t.annotations.get(hash)          t.get_annotation(hash)
t.tags.register(name)            t.register_tag(name)
t.tags.add(hash, tag)            t.tag(hash, tag)
t.tags.remove(hash, tag)         t.untag(hash, tag)
t.tags.list()                    t.list_tags()
t.tags.get(hash)                 t.get_tags(hash)
t.compression.compress(...)      t.compress(...)
t.compression.gc(...)            t.gc(...)
t.llm.chat(...)                  t.runtime.chat(...)
t.llm.generate(...)              t.runtime.generate(...)
t.toolkit.as_tools(...)          t.runtime.tools.as_tools(...)
t.spawn.info()                   t.spawn_parent()
t.spawn.list_children()          t.spawn_children()
t.intelligence.cherry_pick(...)  cherry_pick(t, ...)  [standalone function]
t.intelligence.deduplicate(...)  deduplicate(t, ...)   [standalone function]
```

## 5. Known Gaps / Things to Verify

1. **tags.query()**: ~~No direct method added.~~ VERIFIED: Tests use `t.find(tag=...)` or `t._tags_mgr.query()`. Cookbooks updated. TagManager.query() is available via internal access; not worth a direct method since `t.find(tag=...)` covers the common case.
2. **compress_tool_calls()**: ~~No direct method.~~ FIXED: `t.compress_tool_calls()` and `t.acompress_tool_calls()` added as direct methods on Tract.
3. **compress_range()**: VERIFIED: `compress_range()` exists in `operations/compression.py`. `t.compress(from_commit=..., to_commit=...)` works correctly. Tested.
4. **Internal manager access via `t._*_mgr`**: VERIFIED: ~130 test refs, ~6 source refs. Most are in tract.py delegation. Two source-level accesses remain: `toolkit/definitions.py` uses `_annotations_mgr._enrich_with_priorities()` and `_tags_mgr.query()`. These are acceptable internal access for specialized queries.
5. **Cookbook files**: ~~19 were migrated but the remaining ~20 may still have old API patterns.~~ FIXED: All 28 cookbook files migrated. Zero old API patterns remain (verified by grep). `t.llm.*` → `t.runtime.*`, `t.search.*` → direct methods, `t.compression.*` → direct methods.
6. **OperationConfigs/OperationClients/OperationPrompts**: Still exist, still used (~105 refs). Deferred removal — too entangled with LLMState and Tract.open(). Design debt, not a bug.
7. **Middleware vs PolicyEngine coexistence**: VERIFIED: Both fire correctly (middleware first, then policies). Integration is in `MiddlewareManager._run()`. No cross-system interaction bugs found. Could use a dedicated integration test.
8. **Async variants**: CONFIRMED: PolicyEngine.fire() is sync only. No consumer currently needs async policy evaluation. Design decision, not a gap.
9. **BAML comparison**: Informational. BAML (call boundary) and tract (context lifecycle) are orthogonal. No action needed.
10. **15 tests were removed**: VERIFIED: All deleted internal methods (`_parse_response`, `_build_messages`, `_build_peek_messages`, `_safe_llm_call`, etc.) are truly gone from the codebase. No remaining references.

## 6. Post-Refactor Audit (2026-03-19, Wave 2)

An adversarial audit was conducted across Judgment, Policy, and the surface rewrite. Issues found and fixed:

### Fixed
- **MaintenanceAction field naming mismatch**: `from_commit`/`to_commit` fields didn't match LLM prompt schema (`"from"`/`"to"`). Fixed with Pydantic `Field(alias="from")` + `populate_by_name=True`. Also fixed `_actions_to_dicts()` and `_judgment_result_to_outcome()` to use `by_alias=True`.
- **evaluate()/aevaluate() duplication**: Extracted shared `_prepare()` method eliminating 30 lines of duplicated setup code.
- **Dead `_global_policies` field**: PolicyEngine declared `_global_policies: list[str]` but never used it. Removed.
- **PolicyContext.tract typed as `Any`**: Changed to proper `Tract` forward ref (works via `from __future__ import annotations` + TYPE_CHECKING import).
- **Middleware accessing private `_event_bindings`**: Added `PolicyEngine.has_event_policies(event)` public method. Middleware now uses it instead of `_event_bindings` directly.
- **_Runtime missing run()/arun()**: Added `run()` and `arun()` to `_Runtime`, completing the `t.llm.*` → `t.runtime.*` migration.
- **Missing `compress_tool_calls()` on Tract**: Added `t.compress_tool_calls()` and `t.acompress_tool_calls()` as direct methods.
- **Cookbook migration incomplete**: Fixed all 28 cookbook files — `t.llm.*`, `t.search.*`, `t.tags.*`, `t.compression.*` → new API.

### Accepted Design Debt (not fixing)
- **Async PolicyEngine**: No `afire()` method. No consumer needs it yet. Would require async condition/strategy protocols.
- **JudgmentResult.output lacks Generic typing**: Output is `BaseModel | None` — callers must know the concrete type. Could use `Generic[T]` but would be a large API change.
- **Response models in judgment.py**: GateVerdict, MaintenancePlan, etc. are defined alongside core Judgment. Separation into `response_models.py` would be cleaner but isn't worth the churn.
- **Schema instruction generation**: `_schema_instructions()` doesn't handle discriminated unions, nested $refs, or field defaults. Works for all current models.
- **Semantic conditions lose PolicyContext metadata**: Evaluable.evaluate() takes only `tract`, not event/branch/trigger_data. By design — semantic conditions query LLM about tract state, not event metadata.
- **Side-effect execution order in PolicyEngine.fire()**: All policies evaluate even if a higher-priority one blocks. Prevents wasted LLM calls but is a semantic change to fix.
- **OperationConfigs/Clients/Prompts**: Still exist (~105 refs). Removal requires LLMState refactor. Deferred.
