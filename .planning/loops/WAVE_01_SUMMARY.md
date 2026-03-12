# Cookbook Debug Waves 1-11 (2026-03-11)

Ran all 50 cookbook files (49 original + 1 new), fixed bugs, improved library design, verified end-to-end.

---

## Wave 1 — Non-LLM Cookbooks (27 files)
**27/27 passed.** 1 soft fix (strategy labels).

## Wave 2 — LLM-Dependent Cookbooks (24 files)
**24/24 ran. 7 code bugs fixed.**
- **Commit:** `e23a001`

## Wave 3 — Design & Consistency Audit
- Compact profile translation, None-safety, max_tokens, tool descriptions
- **Commit:** `5cfd16b` (2319 tests)

## Wave 4 — Re-verification
**12/12 pass.**

## Wave 5 — ContentValidationError UX
- **Commit:** `772c3e6`

## Wave 6 — Design Discrepancies
- Middleware, gate alignment, API surface
- **Commit:** `d878e71`

## Wave 7 — Deeper Fixes
- Blocking-path tests, review gate
- **Commit:** `5cfada2`

## Wave 8 — Merge Parent Traversal + Snapshot Cookbook
- find()/log()/query_by_tags()/list_tags() now traverse merge parents (+15 tests)
- New cookbook: persistence/03_snapshots.py
- **Commit:** `2ba2e2e` (2334 tests)

## Wave 9 — Async Parity + Error Handling
- arun() params, JSONDecodeError, Anthropic 403
- **Commit:** `dd2d226` (2338 tests)

## Wave 10 — Final Verification
**30/30 non-LLM cookbooks pass. 2338 tests. Zero regressions.**

## Wave 11 — Edge Cases + Spot Check
- StepMetrics.compressed flag: only set True on successful compression
- export_state/load_state: documented limitations accurately
- 4/4 LLM cookbooks spot-checked: all pass
- **Commits:** `027807c`, `4b33733`

---

## Cumulative Stats

| Metric | Value |
|--------|-------|
| Cookbooks verified | 50/50 |
| Library bugs fixed | 14 |
| Cookbook bugs fixed | 10 |
| Design/doc improvements | 11 |
| New tests | +28 |
| New cookbook | persistence/03_snapshots.py |
| Total tests | 2338 |
| Total commits | 9 |

## All Library Fixes
1. _resolve_tools() compact profile bypassed tool_names/overrides
2. LLMToolUseError for Groq tool_use_failed 400s
3. ACTION_TO_DOMAIN translation for compact tool_names
4. run()/arun() tool_names delegation
5. ContentValidationError: LLM-actionable messages
6. RetryExhaustedError + StreamPrinter public exports
7. find()/log()/query_by_tags()/list_tags() merge parent traversal
8. arun() missing step_budget/tool_validator/auto_compress_threshold
9. arun() sentinel handling parity with run()
10. _extract_tool_calls JSONDecodeError crash
11. Anthropic 403 PermissionDeniedError → LLMAuthError
12. Tool descriptions (commit, transition, switch, register_tag)
13. StepMetrics.compressed accuracy on failed compress
14. export_state/load_state docstring accuracy

## All Cookbook Fixes
1. _logging.py Unicode on Windows
2. 05_async.py None slicing
3. 03_custom_tools + 04_streaming profile mismatch
4. 05_staged_workflow + 07_quality_gates max_tokens
5. 04_streaming_pipeline stage config
6. 02_event_automation pre_commit ctx.commit→ctx.pending
7. 06_coding_with_tests configure→transition + gate logic
8. 05_ecomm_pipeline docstring accuracy
9. 02_config_resolution vestigial orchestrate
10. 05_custom_extensions private API → public API
+ None-safety (11 files), max_tokens (12 instances), profile (6 files), imports (3 files)

## Remaining Non-Code Issues
- Groq free-tier rate limits (6000 TPM)
- Smaller models don't reliably call tools
- export_state/load_state doesn't preserve DAG structure (documented, by design)
