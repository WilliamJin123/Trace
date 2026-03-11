# Tract Consumers

Projects that depend on tract-ai as an editable install.

## Active consumers

| Repo | Path | Key APIs | Status |
|------|------|----------|--------|
| tract-coding | `../tract-coding` | Session, run_loop, ToolSummarizationConfig, branching | Scaffold |
| tract-ecomm | `../tract-ecomm` | Session.spawn/collapse, branching (A/B), compression, tool compaction | Scaffold |
| tract-research | `../tract-research` | Session.spawn/collapse, branching (hypotheses), compression, knowledge persistence | Scaffold |

## API stability

### Stable (safe to depend on)
- `Tract.open()`, `.commit()`, `.compile()`, `.close()`
- `Tract.system()`, `.user()`, `.assistant()` shorthand
- `CompiledContext.to_dicts()`, `.to_openai()`, `.to_anthropic()`
- `Tract.branch()`, `.switch()`, `.merge()`
- `Session.open()`, `.create_tract()`, `.spawn()`, `.collapse()`
- All content types (InstructionContent, DialogueContent, etc.)
- CommitInfo, CommitOperation, Priority
- `ConfigIndex` — 6 cookbook patterns, 26 integration tests, 4 dedicated test classes
- `Tract.find()` / `.find_one()` — commit search by content/tag/type/metadata
- `Tract.compare()` — cross-branch diff returning `DiffResult`
- `MergeStrategy` (ours/theirs/auto) — conflict resolution for merge operations
- `RetryConfig` — retry with exponential backoff + jitter
- `DirectiveTemplate` / `list_templates()` / `get_template()` — parameterized directives
- `WorkflowProfile` / `get_profile()` / `list_profiles()` — config+directive+stage bundles
- `Tract.snapshot()` / `list_snapshots()` / `restore_snapshot()` — named restore points
- `Tract.health()` — DAG validation returning `HealthReport`
- `Tract.batch()` — atomic multi-commit context manager

### In flux (may change)
- `run_loop()` — still being enhanced (step_budget, tool_validator, auto_compress_threshold added)
- `ToolSummarizationConfig` — compaction behavior still being tuned
- `OperationConfigs` / `OperationClients` — wiring may simplify
- `Tract.chat()` / `.generate()` — used in multiple cookbooks but convenience API may evolve
- Middleware system `t.use()` / `t.remove_middleware()` — used in cookbooks and integration tests, stage gating patterns validated
- `LoopConfig.step_budget` / `.tool_validator` / `.auto_compress_threshold` — new loop options, being validated
- `StepMetrics` / `LoopResult.step_metrics` — new observability, not yet populated by default loop

### Not yet validated by consumers

(Section cleared -- all previously listed APIs have been moved to Stable or In flux above.)

## Breaking changes

| Date | Change | Consumers affected | Migration |
|------|--------|--------------------|-----------|
| 2026-03 | API surface expanded: find/compare/snapshot/health/batch added to Stable; middleware/loop config options added to In flux | All | No breakage -- additive only |
| 2026-03 | Orchestrator module removed | tract-coding (if used) | Replace with `run_loop()` |
| 2026-03 | `t.on()`/`t.off()` renamed to `t.use()`/`t.remove_middleware()` | Any consumer using old hook names | Update method names |
