"""Snapshots -- Named Restore Points for Safe Rollback

Tract's snapshot system creates lightweight, named restore points in the DAG.
Unlike branch-based checkpoints (which require manual branch/reset wiring),
snapshots are a single API call to create and a single call to restore.

Think of them as "save game" slots: snapshot before a risky operation,
and restore if things go wrong.

Patterns shown:
  1. Creating Named Snapshots    -- t.snapshot("label") returns a tag
  2. Listing Snapshots           -- t.list_snapshots() for inspection
  3. Restoring via Branch        -- safe restore that preserves history
  4. Restoring via Direct Reset  -- destructive restore for quick rollback
  5. Practical: Snapshot Before Experimental Work -- undo a bad direction
  6. Practical: Snapshot Before Risky Merge -- undo a bad merge

Demonstrates: t.snapshot(), t.list_snapshots(), t.restore_snapshot(),
              t.branch(), t.merge(), t.compile(), t.log()

No LLM required.
"""

from tract import Tract


def main():
    # =================================================================
    # 1. Creating Named Snapshots
    # =================================================================
    #
    # t.snapshot(label) creates a restore point at the current HEAD.
    # It returns a tag string like "snapshot:<label>:<short-hash>".
    # The snapshot is stored as a metadata commit in the DAG, so it
    # survives close/reopen and is visible in the log.

    print("=" * 60)
    print("1. Creating Named Snapshots")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are an infrastructure engineer.")
        t.user("Design the CI/CD pipeline for our monorepo.")
        t.assistant(
            "Proposed pipeline:\n"
            "1. Lint + type-check on every PR\n"
            "2. Unit tests with coverage gating (80%)\n"
            "3. Integration tests against staging\n"
            "4. Canary deploy to 5% of production"
        )

        # Create a named snapshot
        tag = t.snapshot("after-initial-design")
        print(f"  Created snapshot: {tag}")

        # The tag follows the pattern: snapshot:<label>:<short-hash>
        assert tag.startswith("snapshot:after-initial-design:")
        print(f"  Tag format verified: snapshot:<label>:<short-hash>")

        # Snapshot without a label uses a timestamp instead
        t.user("What about rollback strategy?")
        t.assistant("Use blue-green deploys with automated rollback on error-rate spike.")
        auto_tag = t.snapshot()
        parts = auto_tag.split(":")
        assert parts[0] == "snapshot"
        assert parts[1].isdigit()  # timestamp
        print(f"  Auto-labeled snapshot: {auto_tag}")

    print("\n  Named snapshots: PASSED")

    # =================================================================
    # 2. Listing Snapshots
    # =================================================================
    #
    # t.list_snapshots() returns all snapshots as dicts with keys:
    # tag, label, head, branch, timestamp, hash.
    # Results are sorted newest-first (reverse chronological).

    print()
    print("=" * 60)
    print("2. Listing Snapshots")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a database administrator.")

        t.user("Plan the schema migration for v2.")
        t.assistant("Step 1: Add new columns with defaults. Step 2: Backfill. Step 3: Drop old columns.")
        t.snapshot("pre-migration-v2")

        t.user("What about the index strategy?")
        t.assistant("Add composite index on (tenant_id, created_at) for the queries table.")
        t.snapshot("pre-index-changes")

        t.user("Should we partition the events table?")
        t.assistant("Yes, range-partition by month on event_date. Keeps queries fast.")
        t.snapshot("pre-partitioning")

        # List all snapshots
        snaps = t.list_snapshots()
        assert len(snaps) == 3

        print(f"  Found {len(snaps)} snapshots (newest first):")
        for snap in snaps:
            print(f"    [{snap['label']:20s}]  head={snap['head'][:8]}  branch={snap['branch']}")

        # Verify ordering: newest first
        assert snaps[0]["label"] == "pre-partitioning"
        assert snaps[1]["label"] == "pre-index-changes"
        assert snaps[2]["label"] == "pre-migration-v2"
        print("\n  Ordering verified: newest first")

        # Each snapshot dict has the expected keys
        expected_keys = {"tag", "label", "head", "branch", "timestamp", "hash"}
        for snap in snaps:
            assert expected_keys.issubset(snap.keys()), f"Missing keys in {snap.keys()}"
        print(f"  All snapshots have keys: {sorted(expected_keys)}")

    print("\n  Listing snapshots: PASSED")

    # =================================================================
    # 3. Restoring via Branch (Safe Mode)
    # =================================================================
    #
    # By default, restore_snapshot() creates a new branch at the
    # snapshot point.  This is the safe option: no history is lost,
    # and you can compare the restored state with the current one.

    print()
    print("=" * 60)
    print("3. Restoring via Branch (Safe Mode)")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a security auditor.")
        t.user("Review our authentication flow.")
        t.assistant(
            "Auth flow looks solid: OAuth2 + PKCE, token rotation on "
            "privilege escalation, bcrypt with cost=12."
        )
        head_at_snapshot = t.head
        t.snapshot("before-deep-audit")

        # Work continues -- add several more commits
        t.user("Now audit the session management.")
        t.assistant("Sessions use HTTP-only cookies with 30-min expiry. Secure.")
        t.user("And the API rate limiting?")
        t.assistant("Rate limiting at 200 req/min per key. Per-endpoint limits needed.")

        assert t.head != head_at_snapshot
        print(f"  HEAD after more work: {t.head[:8]} (moved past snapshot)")

        # Restore creates a branch named "restore/<label>"
        restored_head = t.restore_snapshot("before-deep-audit")

        assert restored_head == head_at_snapshot
        assert t.current_branch == "restore/before-deep-audit"
        assert t.head == head_at_snapshot
        print(f"  Restored to: {restored_head[:8]}")
        print(f"  On branch:   {t.current_branch}")
        print(f"  HEAD matches snapshot: {t.head[:8]} == {head_at_snapshot[:8]}")

    print("\n  Restore via branch: PASSED")

    # =================================================================
    # 4. Restoring via Direct Reset
    # =================================================================
    #
    # Pass create_branch=False to restore_snapshot() for a direct
    # HEAD reset.  This is faster but discards commits after the
    # snapshot on the current branch.  Use when you are certain
    # the post-snapshot work is not needed.

    print()
    print("=" * 60)
    print("4. Restoring via Direct Reset")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a deployment engineer.")
        t.user("Deploy v3.2 to production.")
        t.assistant("Deployment plan: canary at 5%, monitor for 15 min, full rollout.")
        head_at_snapshot = t.head
        original_branch = t.current_branch
        t.snapshot("pre-deploy-v3.2")

        # Simulate a bad deployment sequence
        t.user("Canary is showing 5% error rate increase!")
        t.assistant("Rolling back immediately. Reverting to v3.1.")
        t.user("Root cause: database migration had a column type mismatch.")

        commits_after = len(t.log(limit=50))
        print(f"  Commits after bad deploy: {commits_after}")

        # Direct reset -- no new branch, just rewind HEAD
        restored_head = t.restore_snapshot("pre-deploy-v3.2", create_branch=False)

        assert restored_head == head_at_snapshot
        assert t.head == head_at_snapshot
        assert t.current_branch == original_branch  # stayed on same branch
        print(f"  Reset HEAD to: {restored_head[:8]}")
        print(f"  Still on branch: {t.current_branch}")

        commits_after_reset = len(t.log(limit=50))
        print(f"  Commits after reset: {commits_after_reset} (was {commits_after})")

    print("\n  Restore via direct reset: PASSED")

    # =================================================================
    # 5. Practical: Snapshot Before Experimental Work
    # =================================================================
    #
    # Snapshot before trying an experimental direction.  If the new
    # approach turns out to be a dead end, restore to the snapshot
    # to discard the failed attempt and try something else.
    #
    # Note: snapshots are metadata commits in the DAG, so they
    # survive normal commit appends but are replaced by compress().
    # For compression safety, use branch-based checkpoints instead
    # (see cookbook 01, section 3).

    print()
    print("=" * 60)
    print("5. Practical: Snapshot Before Experimental Work")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a technical architect.")

        # Build up a solid design
        t.user("Design the caching layer.")
        t.assistant(
            "Caching architecture:\n"
            "- L1: In-process LRU (128MB, 50ms P99)\n"
            "- L2: Redis cluster (3 nodes, 500ms P99)\n"
            "- L3: CDN edge cache for static assets\n"
            "- Invalidation: event-driven via Kafka"
        )
        t.user("What about cache warming?")
        t.assistant(
            "Cache warming strategy:\n"
            "- Pre-populate top 1000 queries on deploy\n"
            "- Background refresh for items within 10% of TTL\n"
            "- Stale-while-revalidate for non-critical paths"
        )

        # Good state -- snapshot before going down an experimental path
        pre_ctx = t.compile()
        pre_messages = len(pre_ctx.messages)
        pre_tokens = pre_ctx.token_count
        good_head = t.head
        t.snapshot("before-experiment")
        print(f"  Solid design: {pre_messages} messages, ~{pre_tokens} tokens")
        print(f"  Snapshot created at: {good_head[:8]}")

        # Try an experimental approach that turns out badly
        t.user("Actually, let's replace the entire caching layer with a single Memcached instance.")
        t.assistant(
            "Single Memcached approach:\n"
            "- Remove L1/L2/L3 tiering entirely\n"
            "- One Memcached node, 64GB RAM\n"
            "- No invalidation strategy needed\n"
            "WARNING: Single point of failure, no persistence"
        )
        t.user("How do we handle failover?")
        t.assistant(
            "With single Memcached there is no failover. On crash, "
            "all cached data is lost and must be rebuilt from DB. "
            "Cold start could take 30+ minutes."
        )

        bad_ctx = t.compile()
        bad_text = bad_ctx.to_text()
        print(f"  After experiment: {len(bad_ctx.messages)} messages")
        print(f"  Has bad advice ('no failover'): {'no failover' in bad_text}")

        # The experiment was a dead end -- restore to the good state
        restored_head = t.restore_snapshot("before-experiment")

        assert restored_head == good_head
        restored_ctx = t.compile()
        restored_text = restored_ctx.to_text()

        # The experimental dead-end is gone; the solid design remains
        assert "no failover" not in restored_text
        assert "Pre-populate top 1000" in restored_text
        assert "event-driven via Kafka" in restored_text
        print(f"  After restore: {len(restored_ctx.messages)} messages, ~{restored_ctx.token_count} tokens")
        print(f"  Bad advice gone: {'no failover' not in restored_text}")
        print(f"  Good design intact: {'event-driven via Kafka' in restored_text}")
        print(f"  On branch: {t.current_branch}")

    print("\n  Snapshot before experimental work: PASSED")

    # =================================================================
    # 6. Practical: Snapshot Before Risky Merge
    # =================================================================
    #
    # Before merging an experimental branch, snapshot the target
    # branch.  If the merge introduces unwanted content or conflicts,
    # restore to the pre-merge state with a single call.

    print()
    print("=" * 60)
    print("6. Practical: Snapshot Before Risky Merge")
    print("=" * 60)
    print()

    with Tract.open() as t:
        # Set up main branch with stable context
        t.system("You are a product manager.")
        t.user("Define the v2 feature set.")
        t.assistant(
            "v2 features: real-time collaboration, role-based access, "
            "audit logging, webhook integrations."
        )

        main_head = t.head

        # Create an experimental branch with risky changes
        t.branch("experiment/ai-features")
        t.user("What if we add AI-powered auto-complete?")
        t.assistant(
            "AI auto-complete: fine-tune GPT-4 on user data, "
            "serve via streaming API, estimated cost $50K/month. "
            "WARNING: requires PII handling infrastructure."
        )

        # Go back to main for the merge
        t.switch("main")

        # Snapshot before the merge
        t.snapshot("before-merge-ai-features")
        print(f"  Snapshot on main at: {t.head[:8]}")

        # Merge the experimental branch
        t.merge("experiment/ai-features")
        merged_ctx = t.compile()
        merged_text = merged_ctx.to_text()
        print(f"  After merge: {len(merged_ctx.messages)} messages")

        # The merge brought in risky PII content we did not want
        has_pii_warning = "PII handling" in merged_text
        print(f"  PII warning in merged context: {has_pii_warning}")

        # Restore to pre-merge state
        restored_head = t.restore_snapshot("before-merge-ai-features")
        assert restored_head == main_head

        restored_ctx = t.compile()
        restored_text = restored_ctx.to_text()

        # Verify the merge content is gone
        assert "PII handling" not in restored_text
        assert "v2 features" in restored_text
        print(f"  After restore: {len(restored_ctx.messages)} messages")
        print(f"  PII warning gone: {'PII handling' not in restored_text}")
        print(f"  Core features preserved: {'v2 features' in restored_text}")
        print(f"  Restored to branch: {t.current_branch}")

    print("\n  Snapshot before risky merge: PASSED")

    # =================================================================
    # Summary
    # =================================================================

    print()
    print("=" * 60)
    print("Summary: Snapshot Patterns")
    print("=" * 60)
    print()
    print("  Pattern                       Key API")
    print("  ----------------------------  -----------------------------------")
    print("  Create named snapshot         t.snapshot('label') -> tag string")
    print("  Create auto-labeled snapshot  t.snapshot() -> timestamp-based tag")
    print("  List all snapshots            t.list_snapshots() -> [dict, ...]")
    print("  Restore via branch (safe)     t.restore_snapshot('label')")
    print("  Restore via reset (fast)      t.restore_snapshot('x', create_branch=False)")
    print("  Undo experimental work        snapshot() -> experiment -> restore_snapshot()")
    print("  Undo risky merge              snapshot() -> merge() -> restore_snapshot()")
    print()
    print("  Snapshots vs. branch checkpoints:")
    print("  - Snapshots: one call to create, one call to restore")
    print("  - Branch checkpoints: manual branch() + reset() wiring")
    print("  - Snapshots carry metadata (label, timestamp, branch, head)")
    print("  - Both persist across close/reopen")
    print()
    print("Done.")


# Alias for pytest discovery
test_snapshots = main


if __name__ == "__main__":
    main()
