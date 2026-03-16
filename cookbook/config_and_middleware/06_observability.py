"""Observability and Monitoring with Middleware

Production observability patterns using tract's middleware system. Middleware
handlers fire on every significant operation, letting you build structured
metrics, audit trails, and dashboards without wrapper functions or monkey-
patching.

Patterns shown:
  1. LLM Call Logging          -- track model, tokens, latency, cost per commit
  2. Token Budget Dashboard    -- cumulative usage by stage with budget warnings
  3. Operation Audit Trail     -- timestamped log of every tract operation
  4. Stage Timing              -- measure time spent in each workflow stage
  5. Compression Efficiency    -- pre/post token counts and compression ratios

Demonstrates: t.middleware.add(), post_commit metadata capture, pre_compile / pre_compress /
              pre_transition / post_transition hooks, closure-based state,
              t.compile().token_count, t.search.log() for audit, t.compression.compress()

Why middleware beats logging wrappers:
  - Every operation fires automatically -- nothing to forget
  - Context object gives you branch, HEAD, commit details for free
  - Structured data (not string parsing) from the start
  - Composable: stack multiple monitors on the same event

No LLM required.
"""

import time
from datetime import datetime, timezone

from tract import Tract, MiddlewareContext


def main() -> None:
    # =================================================================
    # 1. LLM Call Logging
    # =================================================================
    #
    # Track every commit that carries generation metadata. In production,
    # each LLM-generated assistant commit has generation_config and
    # token_count on CommitInfo. Middleware captures this automatically.

    print("=" * 60)
    print("1. LLM Call Logging")
    print("=" * 60)
    print()

    with Tract.open() as t:

        # --- In-memory metrics tracker ---
        llm_metrics = {
            "calls": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
        }

        # Approximate cost per 1K tokens (production would use actual rates)
        COST_PER_1K = {"input": 0.003, "output": 0.015}

        def track_llm_calls(ctx: MiddlewareContext):
            """Post-commit: capture generation metadata from every commit."""
            if ctx.commit is None:
                return
            # In production, generation_config is set on LLM-generated commits.
            # Here we simulate by treating assistant commits as LLM calls.
            meta = ctx.commit.metadata or {}
            input_tokens = meta.get("input_tokens", ctx.commit.token_count)
            output_tokens = meta.get("output_tokens", ctx.commit.token_count)
            model = meta.get("model", "simulated")
            latency_ms = meta.get("latency_ms", 0)

            cost = (
                (input_tokens / 1000) * COST_PER_1K["input"]
                + (output_tokens / 1000) * COST_PER_1K["output"]
            )

            entry = {
                "hash": ctx.commit.commit_hash[:8],
                "branch": ctx.branch,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "cost_usd": round(cost, 6),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            llm_metrics["calls"].append(entry)
            llm_metrics["total_input_tokens"] += input_tokens
            llm_metrics["total_output_tokens"] += output_tokens
            llm_metrics["total_cost_usd"] += cost

        tracker_id = t.middleware.add("post_commit", track_llm_calls)

        # Simulate a conversation with metadata mimicking real LLM responses
        t.system("You are a financial analyst.")
        t.user("Analyze Q3 revenue trends.")
        t.assistant(
            "Q3 revenue grew 18% YoY driven by enterprise expansion.",
            metadata={"model": "gpt-4o", "input_tokens": 45, "output_tokens": 32, "latency_ms": 820},
        )
        t.user("Break down by segment.")
        t.assistant(
            "Enterprise: +24% ($12M). SMB: +8% ($4M). Consumer: -2% ($1.5M).",
            metadata={"model": "gpt-4o", "input_tokens": 92, "output_tokens": 48, "latency_ms": 1150},
        )
        t.user("What is the forecast for Q4?")
        t.assistant(
            "Projecting 15% QoQ growth based on pipeline and seasonal patterns.",
            metadata={"model": "gpt-4o-mini", "input_tokens": 138, "output_tokens": 35, "latency_ms": 450},
        )

        # --- Print metrics dashboard ---
        print(f"  Total LLM calls tracked: {len(llm_metrics['calls'])}")
        print(f"  Total input tokens:      {llm_metrics['total_input_tokens']}")
        print(f"  Total output tokens:     {llm_metrics['total_output_tokens']}")
        print(f"  Estimated cost:          ${llm_metrics['total_cost_usd']:.4f}")
        print()
        print("  Per-call breakdown:")
        for call in llm_metrics["calls"]:
            if call["model"] != "simulated":
                print(
                    f"    [{call['hash']}] {call['model']:15s} "
                    f"in={call['input_tokens']:>4d}  out={call['output_tokens']:>4d}  "
                    f"latency={call['latency_ms']:>5d}ms  "
                    f"cost=${call['cost_usd']:.4f}"
                )

        t.middleware.remove(tracker_id)

    # =================================================================
    # 2. Token Budget Dashboard
    # =================================================================
    #
    # Track cumulative token usage across workflow stages. Each stage
    # (research, drafting, review) gets its own budget. Middleware
    # accumulates per-stage metrics and warns when approaching limits.

    print()
    print("=" * 60)
    print("2. Token Budget Dashboard")
    print("=" * 60)
    print()

    with Tract.open() as t:

        # --- Budget tracker ---
        budget = {
            "stage_tokens": {},       # stage_name -> cumulative tokens
            "stage_commits": {},      # stage_name -> commit count
            "warnings": [],           # budget warning messages
            "current_stage": "research",
        }
        STAGE_BUDGETS = {
            "research": 500,
            "drafting": 800,
            "review": 300,
        }

        def track_stage_tokens(ctx: MiddlewareContext):
            """Post-commit: accumulate tokens for the current stage."""
            if ctx.commit is None:
                return
            stage = budget["current_stage"]
            budget["stage_tokens"].setdefault(stage, 0)
            budget["stage_commits"].setdefault(stage, 0)
            budget["stage_tokens"][stage] += ctx.commit.token_count
            budget["stage_commits"][stage] += 1

            # Check budget threshold (warn at 80%)
            limit = STAGE_BUDGETS.get(stage, float("inf"))
            used = budget["stage_tokens"][stage]
            if used >= limit * 0.8 and used < limit:
                warning = f"WARNING: stage '{stage}' at {used}/{limit} tokens ({used/limit:.0%})"
                budget["warnings"].append(warning)

        def update_stage_on_transition(ctx: MiddlewareContext):
            """Post-transition: update current stage tracker."""
            if ctx.target:
                budget["current_stage"] = ctx.target

        token_id = t.middleware.add("post_commit", track_stage_tokens)
        stage_id = t.middleware.add("post_transition", update_stage_on_transition)

        # --- Research stage ---
        t.system("You are a market researcher.")
        t.user("Research the competitive landscape for AI coding tools.")
        t.assistant(
            "The AI coding tools market includes GitHub Copilot, Cursor, "
            "Cody, Tabnine, and Amazon CodeWhisperer. Market size est. $5B by 2027."
        )
        t.user("What are the key differentiators?")
        t.assistant(
            "Key differentiators: context window size, IDE integration depth, "
            "language support breadth, and enterprise security features."
        )

        print(f"  Research stage: {budget['stage_tokens'].get('research', 0)} tokens "
              f"({budget['stage_commits'].get('research', 0)} commits)")

        # --- Transition to drafting ---
        t.transition("drafting")

        t.user("Draft an executive summary of our competitive analysis.")
        t.assistant(
            "Executive Summary: The AI coding tools market is projected to reach "
            "$5B by 2027. Our analysis of 5 major competitors reveals that context "
            "window size and enterprise security are the primary battlegrounds. "
            "GitHub Copilot leads in market share but faces increasing competition "
            "from context-aware tools like Cursor."
        )
        t.user("Add a recommendation section.")
        t.assistant(
            "Recommendation: Focus on (1) expanding context window to 200K tokens, "
            "(2) SOC2 compliance for enterprise, (3) deep IDE integration beyond VS Code."
        )

        print(f"  Drafting stage: {budget['stage_tokens'].get('drafting', 0)} tokens "
              f"({budget['stage_commits'].get('drafting', 0)} commits)")

        # --- Transition to review ---
        t.transition("review")

        t.user("Review the draft for accuracy.")
        t.assistant("Draft reviewed. One correction: market size should cite Gartner 2026 report.")

        print(f"  Review stage:   {budget['stage_tokens'].get('review', 0)} tokens "
              f"({budget['stage_commits'].get('review', 0)} commits)")

        # --- Print budget dashboard ---
        print()
        print("  Token Budget Dashboard:")
        print("  " + "-" * 52)
        print(f"  {'Stage':<12} {'Used':>8} {'Budget':>8} {'Remaining':>10} {'Usage':>8}")
        print("  " + "-" * 52)
        total_used = 0
        total_budget = 0
        for stage, limit in STAGE_BUDGETS.items():
            used = budget["stage_tokens"].get(stage, 0)
            remaining = max(0, limit - used)
            pct = (used / limit * 100) if limit > 0 else 0
            total_used += used
            total_budget += limit
            print(f"  {stage:<12} {used:>8} {limit:>8} {remaining:>10} {pct:>7.1f}%")
        print("  " + "-" * 52)
        print(f"  {'TOTAL':<12} {total_used:>8} {total_budget:>8} "
              f"{max(0, total_budget - total_used):>10} "
              f"{total_used / total_budget * 100:>7.1f}%")

        if budget["warnings"]:
            print()
            for w in budget["warnings"]:
                print(f"  {w}")

        t.middleware.remove(token_id)
        t.middleware.remove(stage_id)

    # =================================================================
    # 3. Operation Audit Trail
    # =================================================================
    #
    # Log every tract operation with timestamps, branch context, and
    # operation details. The audit trail is queryable and structured --
    # not just strings in a log file.

    print()
    print("=" * 60)
    print("3. Operation Audit Trail")
    print("=" * 60)
    print()

    with Tract.open() as t:

        audit_log = []

        def audit_commits(ctx: MiddlewareContext):
            """Post-commit: record commit operations."""
            if ctx.commit is None:
                return
            audit_log.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "event": ctx.event,
                "operation": "commit",
                "branch": ctx.branch,
                "hash": ctx.commit.commit_hash[:8],
                "content_type": ctx.commit.content_type,
                "op": str(ctx.commit.operation),
                "tokens": ctx.commit.token_count,
                "message": (ctx.commit.message or "")[:50],
            })

        def audit_compiles(ctx: MiddlewareContext):
            """Pre-compile: record compile operations."""
            audit_log.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "event": ctx.event,
                "operation": "compile",
                "branch": ctx.branch,
                "head": ctx.head[:8],
            })

        def audit_compress(ctx: MiddlewareContext):
            """Pre-compress: record compress operations."""
            audit_log.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "event": ctx.event,
                "operation": "compress",
                "branch": ctx.branch,
                "head": ctx.head[:8],
            })

        def audit_merge(ctx: MiddlewareContext):
            """Pre-merge: record merge operations."""
            audit_log.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "event": ctx.event,
                "operation": "merge",
                "branch": ctx.branch,
                "head": ctx.head[:8],
            })

        def audit_transitions(ctx: MiddlewareContext):
            """Pre/post transition: record stage transitions."""
            audit_log.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "event": ctx.event,
                "operation": "transition",
                "branch": ctx.branch,
                "target": ctx.target or "?",
                "head": ctx.head[:8],
            })

        # Register all audit handlers
        ids = [
            t.middleware.add("post_commit", audit_commits),
            t.middleware.add("pre_compile", audit_compiles),
            t.middleware.add("pre_compress", audit_compress),
            t.middleware.add("pre_merge", audit_merge),
            t.middleware.add("pre_transition", audit_transitions),
            t.middleware.add("post_transition", audit_transitions),
        ]

        # --- Generate a variety of operations ---
        t.system("You are a project assistant.")
        t.user("Start the planning phase.")
        t.assistant("Planning phase initiated. Ready for requirements.")

        # Transition
        t.transition("implementation")
        t.user("Implement the login module.")
        t.assistant("Login module implemented with OAuth2 support.")

        # Compile
        t.compile()

        # Compress
        t.compression.compress(content="[Summary] Planning and implementation phases completed.")

        # Merge (branch back to main for another merge)
        t.branches.create("hotfix")
        t.user("Fix critical auth bypass vulnerability.")
        t.assistant("Patched auth bypass in session validation.")
        t.branches.switch("implementation")
        t.merge("hotfix")

        # --- Print audit trail ---
        print(f"  Audit trail: {len(audit_log)} entries\n")
        print(f"  {'#':<4} {'Event':<18} {'Operation':<12} {'Branch':<18} {'Details'}")
        print("  " + "-" * 75)
        for i, entry in enumerate(audit_log, 1):
            details = ""
            if entry["operation"] == "commit":
                details = (
                    f"[{entry['hash']}] {entry['content_type']}/"
                    f"{entry['op']} ({entry['tokens']}tok)"
                )
            elif entry["operation"] == "transition":
                details = f"-> {entry.get('target', '?')}"
            elif entry["operation"] == "compile":
                details = f"at HEAD {entry['head']}"
            elif entry["operation"] == "compress":
                details = f"at HEAD {entry['head']}"
            elif entry["operation"] == "merge":
                details = f"at HEAD {entry['head']}"
            print(f"  {i:<4} {entry['event']:<18} {entry['operation']:<12} "
                  f"{entry['branch']:<18} {details}")

        # --- Queryable audit: filter by operation type ---
        print()
        commit_ops = [e for e in audit_log if e["operation"] == "commit"]
        transition_ops = [e for e in audit_log if e["operation"] == "transition"]
        print(f"  Query: commit operations    = {len(commit_ops)}")
        print(f"  Query: transition operations = {len(transition_ops)}")

        # Verify audit completeness
        assert len(audit_log) > 0, "Audit trail should have entries"
        assert any(e["operation"] == "commit" for e in audit_log)
        assert any(e["operation"] == "transition" for e in audit_log)
        assert any(e["operation"] == "compile" for e in audit_log)
        assert any(e["operation"] == "compress" for e in audit_log)
        assert any(e["operation"] == "merge" for e in audit_log)
        print("  Verified: all operation types captured in audit trail")

        for mid in ids:
            t.middleware.remove(mid)

    # =================================================================
    # 4. Stage Timing
    # =================================================================
    #
    # Track how long each workflow stage takes. pre_transition records
    # the start time; post_transition records the end time. This reveals
    # bottleneck stages without instrumenting individual operations.

    print()
    print("=" * 60)
    print("4. Stage Timing")
    print("=" * 60)
    print()

    with Tract.open() as t:

        stage_timing = {
            "current_stage": "research",
            "stage_start": time.monotonic(),
            "completed": [],  # list of {stage, duration_s}
        }

        def on_pre_transition(ctx: MiddlewareContext):
            """Record end time for the current stage."""
            elapsed = time.monotonic() - stage_timing["stage_start"]
            stage_timing["completed"].append({
                "stage": stage_timing["current_stage"],
                "duration_s": round(elapsed, 4),
            })

        def on_post_transition(ctx: MiddlewareContext):
            """Record start time for the new stage."""
            stage_timing["current_stage"] = ctx.target or ctx.branch
            stage_timing["stage_start"] = time.monotonic()

        pre_id = t.middleware.add("pre_transition", on_pre_transition)
        post_id = t.middleware.add("post_transition", on_post_transition)

        # --- Research stage: simulate work ---
        t.system("You are a research analyst.")
        t.user("Investigate the cloud infrastructure market.")
        t.assistant("AWS leads with 32% share. Azure at 23%. GCP at 11%.")
        t.user("What are the growth trends?")
        t.assistant("Overall market growing 20% CAGR. Multi-cloud adoption accelerating.")
        # Small delay to make timing visible
        time.sleep(0.02)

        # --- Transition to analysis stage ---
        t.transition("analysis")
        t.user("Synthesize the research into key insights.")
        t.assistant(
            "Key insight: multi-cloud is the dominant strategy. "
            "Enterprises average 2.6 cloud providers."
        )
        time.sleep(0.01)

        # --- Transition to reporting stage ---
        t.transition("reporting")
        t.user("Create the final report.")
        t.assistant("Report: Cloud Infrastructure 2026 -- Multi-cloud dominates.")
        time.sleep(0.005)

        # --- Finalize: record the last stage ---
        # Manually close the last stage (no transition fires for it)
        elapsed = time.monotonic() - stage_timing["stage_start"]
        stage_timing["completed"].append({
            "stage": stage_timing["current_stage"],
            "duration_s": round(elapsed, 4),
        })

        # --- Print timing report ---
        total_time = sum(s["duration_s"] for s in stage_timing["completed"])
        print("  Stage Timing Report:")
        print("  " + "-" * 45)
        print(f"  {'Stage':<15} {'Duration':>10} {'% of Total':>12}")
        print("  " + "-" * 45)
        for entry in stage_timing["completed"]:
            pct = (entry["duration_s"] / total_time * 100) if total_time > 0 else 0
            print(f"  {entry['stage']:<15} {entry['duration_s']:>9.4f}s {pct:>11.1f}%")
        print("  " + "-" * 45)
        print(f"  {'TOTAL':<15} {total_time:>9.4f}s {'100.0%':>12}")

        # Identify slowest stage
        slowest = max(stage_timing["completed"], key=lambda s: s["duration_s"])
        print(f"\n  Bottleneck: '{slowest['stage']}' stage ({slowest['duration_s']:.4f}s)")

        assert len(stage_timing["completed"]) == 3, "Should have timed 3 stages"
        assert total_time > 0, "Total time should be positive"
        print("  Verified: all stages timed correctly")

        t.middleware.remove(pre_id)
        t.middleware.remove(post_id)

    # =================================================================
    # 5. Compression Efficiency Metrics
    # =================================================================
    #
    # Track pre/post compression token counts to measure how effectively
    # compression preserves information while reducing context size.
    # Uses pre_compress middleware to snapshot the before-state, then
    # compares against the after-state.

    print()
    print("=" * 60)
    print("5. Compression Efficiency Metrics")
    print("=" * 60)
    print()

    with Tract.open() as t:

        compression_metrics = {
            "events": [],  # list of {before_tokens, after_tokens, ratio, ...}
        }

        def snapshot_before_compress(ctx: MiddlewareContext):
            """Pre-compress: snapshot token count before compression."""
            compiled = ctx.tract.compile()
            compression_metrics["_pending"] = {
                "before_tokens": compiled.token_count,
                "before_messages": len(compiled.messages),
                "branch": ctx.branch,
            }

        compress_id = t.middleware.add("pre_compress", snapshot_before_compress)

        # --- Build a conversation to compress ---
        t.system("You are a customer support agent.")

        # Simulate a long support conversation
        issues = [
            ("password reset", "Navigate to Settings > Security > Reset Password."),
            ("billing inquiry", "Your current plan is Pro ($49/mo). Next billing: March 15."),
            ("feature request", "Noted: API webhook support. Added to roadmap Q2 2026."),
            ("login error", "Clear browser cache and cookies, then retry. Error 403 = expired session."),
            ("data export", "Go to Dashboard > Export > CSV. Limit: 10K rows per export."),
            ("upgrade plan", "Enterprise plan: $199/mo. Includes SSO, audit logs, priority support."),
            ("API rate limit", "Current limit: 1000 req/min. Enterprise gets 10K req/min."),
            ("integration help", "Slack integration: Settings > Integrations > Add Slack > Authorize."),
        ]

        for issue, response in issues:
            t.user(f"Customer asks about: {issue}")
            t.assistant(response)

        # Snapshot pre-compression state
        ctx_before = t.compile()
        tokens_before = ctx_before.token_count
        messages_before = len(ctx_before.messages)
        print(f"  Before compression: {messages_before} messages, {tokens_before} tokens")

        # --- Compress with manual summary ---
        result = t.compression.compress(
            content=(
                "[Support Session Summary] 8 tickets handled: "
                "password reset, billing, feature request (API webhooks, Q2), "
                "login error (403/cache), data export (CSV, 10K limit), "
                "plan upgrade (Enterprise $199/mo), API rate limits "
                "(1K std / 10K enterprise), Slack integration setup."
            ),
        )

        # Record metrics using the pending snapshot
        pending = compression_metrics.get("_pending", {})
        ctx_after = t.compile()
        tokens_after = ctx_after.token_count
        messages_after = len(ctx_after.messages)

        ratio = tokens_after / tokens_before if tokens_before > 0 else 0
        savings = tokens_before - tokens_after

        event = {
            "before_tokens": pending.get("before_tokens", tokens_before),
            "before_messages": pending.get("before_messages", messages_before),
            "after_tokens": tokens_after,
            "after_messages": messages_after,
            "ratio": round(ratio, 3),
            "savings": savings,
            "branch": pending.get("branch", "main"),
            # CompressResult fields
            "original_tokens": result.original_tokens,
            "compressed_tokens": result.compressed_tokens,
            "compression_ratio": round(result.compression_ratio, 3),
            "source_commits": len(result.source_commits),
            "summary_commits": len(result.summary_commits),
            "preserved_commits": len(result.preserved_commits),
        }
        compression_metrics["events"].append(event)

        # --- Print compression metrics ---
        print(f"  After compression:  {messages_after} messages, {tokens_after} tokens")
        print()
        print("  Compression Efficiency Report:")
        print("  " + "-" * 50)
        print(f"  Original tokens:      {event['original_tokens']:>8}")
        print(f"  Compressed tokens:    {event['compressed_tokens']:>8}")
        print(f"  Compression ratio:    {event['compression_ratio']:>8.3f}")
        print(f"  Token savings:        {event['savings']:>8}")
        print(f"  Context reduction:    {(1 - ratio) * 100:>7.1f}%")
        print(f"  Source commits:       {event['source_commits']:>8}")
        print(f"  Summary commits:      {event['summary_commits']:>8}")
        print(f"  Preserved commits:    {event['preserved_commits']:>8}")
        print(f"  Messages: {messages_before} -> {messages_after}")

        # Quality heuristic: check that the summary retained key terms
        compiled_text = " ".join((m.content or "") for m in ctx_after.messages)
        key_terms = ["password", "billing", "webhook", "enterprise"]
        retained = sum(1 for term in key_terms if term.lower() in compiled_text.lower())
        retention_pct = retained / len(key_terms) * 100
        print(f"\n  Information retention: {retained}/{len(key_terms)} key terms "
              f"({retention_pct:.0f}%)")

        assert ratio < 1.0, "Compression should reduce token count"
        assert retained >= 3, "Summary should retain most key terms"
        print("  Verified: compression reduced tokens and preserved key information")

        t.middleware.remove(compress_id)

    # =================================================================
    # Summary
    # =================================================================

    print()
    print("=" * 60)
    print("Summary: Why Middleware Beats Logging Wrappers")
    print("=" * 60)
    print()
    print("  Pattern                    Middleware Events Used")
    print("  -------------------------  -----------------------------------")
    print("  LLM Call Logging           post_commit (metadata extraction)")
    print("  Token Budget Dashboard     post_commit + post_transition")
    print("  Operation Audit Trail      post_commit, pre_compile,")
    print("                             pre_compress, pre_merge,")
    print("                             pre/post_transition")
    print("  Stage Timing               pre_transition + post_transition")
    print("  Compression Efficiency     pre_compress (snapshot before)")
    print()
    print("  Advantages over logging wrappers:")
    print("    - Automatic: fires on every operation, nothing to forget")
    print("    - Structured: MiddlewareContext gives branch, HEAD, commit")
    print("    - Composable: stack multiple monitors on the same event")
    print("    - Removable: t.middleware.remove() for clean teardown")
    print("    - No coupling: observers don't modify the operations")
    print()
    print("Done.")


# Alias for pytest discovery
test_observability = main


if __name__ == "__main__":
    main()
