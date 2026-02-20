# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-19)

**Core value:** Agents produce better outputs when their context is clean, coherent, and relevant. Trace makes context a managed, version-controlled resource.
**Current focus:** v3.0 DX & API Overhaul -- Phase 12: LLMConfig Cleanup & Tightening -- PLANNED

## Current Position

Milestone: v3.0 -- DX & API Overhaul
Phase: 12 of 12 (LLMConfig Cleanup & Tightening)
Plan: 0 of 2 (planned, not started)
Status: Planned -- ready for execution
Last activity: 2026-02-19 -- Phase 12 plans created

v1 Progress: [######################] 100% (22/22 plans)
v2 Progress: [######################] 100% (6/6 plans)
v3 Progress: [####################--] 80% (4/5 phases)

## Performance Metrics

**Velocity:**
- Total plans completed: 33
- Average duration: 6.1m
- Total execution time: 3.51 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3/3 | 27m | 9m |
| 1.1 | 2/2 | 6m | 3m |
| 1.2 | 1/1 | 3m | 3m |
| 1.3 | 1/1 | 3m | 3m |
| 1.4 | 1/1 | 4m | 4m |
| 2 | 3/3 | 14m | 4.7m |
| 3 | 5/5 | 30m | 6m |
| 4 | 3/3 | 23m | 7.7m |
| 5 | 3/3 | 28m | 9.3m |
| 6 | 3/3 | 20m | 6.7m |
| 7 | 3/3 | 23m | 7.7m |
| 8 | 1/1 | 7m | 7m |
| 9 | 1/1 | 5m | 5m |
| 10 | 1/1 | 8m | 8m |
| 11 | 2/2 | 13m | 6.5m |

## Accumulated Context

### Decisions

All v1/v2 decisions logged in PROJECT.md Key Decisions table.

| ID | Decision | Rationale |
|----|----------|-----------|
| 08-01-D1 | to_openai() delegates to to_dicts() | OpenAI uses inline system messages |
| 08-01-D2 | to_anthropic() returns {system: str\|None, messages: list} | Anthropic requires separate system key |
| 08-01-D3 | Auto-message uses content_type prefix | Provides context and specificity |
| 08-01-D4 | Auto-message max 72 chars with "..." truncation | Matches git commit convention |
| 08-01-D5 | message=None triggers auto-gen, message="" stores empty | Natural Python convention |
| 09-01-D1 | Response model is authoritative for generation_config | Actual model may differ from requested due to aliases/routing |
| 09-01-D2 | Tract.open() auto-configures LLM only when api_key explicitly provided | No env var auto-detection; explicit is better than implicit |
| 09-01-D3 | Tract owns (and closes) internally-created LLM clients, not external | Follows resource ownership principle |
| 09-01-D4 | chat()/generate() raise TraceError inside batch() | LLM calls are side-effects that cannot be rolled back atomically |
| 10-01-D1 | LLMOperationConfig is a frozen dataclass (not Pydantic) | Runtime-only config, not persisted; avoids Pydantic overhead |
| 10-01-D2 | Three-level resolution: call > operation > tract default | Most specific wins; matches CSS specificity mental model |
| 10-01-D3 | dataclasses.replace() for mutation-safe OrchestratorConfig updates | Avoids mutating caller-supplied objects |
| 10-01-D4 | auto_message excluded from per-operation config | Pure-string function, no LLM call |
| 10-01-D5 | Orchestrate resolution before three-way branch | All code paths benefit from operation config |
| 11-01-D1 | LLMConfig replaces both LLMOperationConfig and dict generation_config | Eliminates type gap between runtime config and persisted config |
| 11-01-D2 | CompileSnapshot internal cache stays tuple[dict,...] | Conversion at boundaries only, for performance |
| 11-01-D3 | Pydantic field_validator auto-coerces dict->LLMConfig on CommitInfo | Backward compatible with all existing code paths |
| 11-01-D4 | extra uses MappingProxyType, unknown dict keys route to extra | Immutable escape hatch for provider-specific params |
| 11-01-D5 | Commits without generation_config produce None in CompiledContext | Not empty LLMConfig(); None signals "not set" clearly |
| 11-02-D1 | get_by_config delegates to get_by_config_multi | DRY: single implementation handles both single and multi-field queries |
| 11-02-D2 | query_by_config uses isinstance dispatch (str vs LLMConfig) | Clean multi-dispatch without @overload, backward compatible |
| 11-02-D3 | Empty LLMConfig returns [] | No fields to match on; returning all commits would be surprising |

### Pending Todos

- Cookbook-driven: run each cookbook example after API changes, discover new issues

### Roadmap Evolution

- Phase 11 added: Unified LLM Config & Query (replace LLMOperationConfig with LLMConfig, full hyperparameters, rich querying)
- v3 milestone COMPLETE: All 15 DX requirements delivered across Phases 8-11
- Phase 12 added: LLMConfig Cleanup & Tightening (typed OperationConfigs, consolidated defaults, smart from_dict, full gen_config capture)
- Phase 12 planned: 2 plans in 2 waves (01: config layer, 02: wiring)

### Blockers/Concerns

None active.

## Session Continuity

Last session: 2026-02-19
Stopped at: Phase 12 planned -- 2 plans created, ready for execution
Resume file: None
