# Phase 6 Plan 01: Policy Storage Foundation Summary

**One-liner:** PolicyProposalRow/PolicyLogRow ORM tables, schema v5 migration, PolicyRepository ABC + SQLite impl, domain models, and policy exceptions.

## Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Schema, migration, domain models, and exceptions | 803883a | schema.py, engine.py, models/policy.py, exceptions.py |
| 2 | PolicyRepository ABC, SqlitePolicyRepository, and storage tests | e854017 | repositories.py, sqlite.py, test_policy_storage.py + 4 test fixups |

**Duration:** ~7m
**Tests:** 29 new, 713 total passing (664 + 29 new + test fixups for v5 assertions)

## What Was Built

### Storage Schema (v5)
- **PolicyProposalRow**: Tracks policy proposals in collaborative mode (proposal_id, tract_id, policy_name, action_type, action_params_json, reason, status, created_at, resolved_at). Composite index on (tract_id, status).
- **PolicyLogRow**: Audit log for all policy evaluations (id autoincrement, tract_id, policy_name, trigger, action_type, reason, outcome, commit_hash, error_message, created_at). Composite index on (tract_id, created_at).
- **Migration v4->v5**: Creates both tables with `checkfirst=True`. Full chain v1->v2->v3->v4->v5 verified.

### Repository Layer
- **PolicyRepository ABC**: 7 abstract methods -- save_proposal, get_proposal, get_pending_proposals, update_proposal_status, save_log_entry, get_log (with since/until/policy_name/limit filters), delete_log_entries (audit GC).
- **SqlitePolicyRepository**: Full implementation using SQLAlchemy 2.0-style queries. Follows exact patterns of SqliteSpawnPointerRepository.

### Domain Models
- **PolicyAction** (frozen dataclass): action_type, params (dict), reason, autonomy level
- **PolicyProposal** (mutable dataclass): approve() calls _execute_fn, reject() sets status. Follows PendingCompression pattern.
- **EvaluationResult** (frozen dataclass): policy_name, triggered, action, outcome, error, commit_hash
- **PolicyLogEntry** (frozen dataclass): Maps 1:1 with PolicyLogRow for domain-level usage

### Exceptions
- **PolicyExecutionError**: For policy action execution failures
- **PolicyConfigError**: For invalid policy configuration

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated existing test assertions from v4 to v5**
- **Found during:** Task 2 regression testing
- **Issue:** Schema version bump from v4 to v5 broke 6 assertions across 4 test files that checked `assert row.value == "4"`
- **Fix:** Updated all assertions to `assert row.value == "5"`, updated docstrings, and added policy table drops to migration simulation tests for accurate v3/v2 state
- **Files modified:** tests/test_compression_storage.py, tests/test_spawn_storage.py, tests/test_storage/test_schema.py, tests/test_integration_multiagent.py
- **Commit:** e854017 (included in Task 2 commit)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| PolicyProposalRow uses String status (not enum) | Consistent with existing pattern; allows future status values without migration |
| PolicyLogRow.trigger is String ("compile"/"commit") | Simple and extensible; mirrors action_type pattern |
| PolicyProposal follows PendingCompression pattern | Proven pattern for deferred execution with user approval |
| PolicyAction is frozen, PolicyProposal is mutable | Actions are determined once; proposals change status during lifecycle |
| Composite indexes on (tract_id, status) and (tract_id, created_at) | Optimizes the two primary query patterns: pending proposals and time-range log queries |

## Success Criteria Verification

1. New databases initialize at schema v5 with policy_proposals and policy_log tables -- VERIFIED
2. v4 databases auto-migrate to v5 on init_db() -- VERIFIED
3. Full v1->v5 migration chain works -- VERIFIED
4. PolicyRepository ABC defines 7 abstract methods -- VERIFIED
5. SqlitePolicyRepository implements all 7 methods with correct SQLAlchemy patterns -- VERIFIED
6. Domain models (PolicyAction, PolicyProposal, EvaluationResult, PolicyLogEntry) exist with correct fields -- VERIFIED
7. All new storage tests pass, zero regressions in existing tests -- VERIFIED (713 passed, 1 pre-existing flaky concurrency test deselected)

## Next Phase Readiness

Plan 06-02 (Policy Evaluation Engine) can proceed. All storage infrastructure is in place:
- Tables exist and are tested
- Repository ABC is defined for DI
- Domain models are ready for the evaluation pipeline
- Exceptions are ready for error handling
