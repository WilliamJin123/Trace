"""Production Monitoring -- instrument tract agents for reliability.

Patterns for monitoring, metrics, alerting, and debugging in production.
All examples run locally without external dependencies.

Patterns shown:
  1. Step-by-Step Token Tracking   -- per-step token usage via step_usages
  2. Middleware-Based Audit Trail   -- complete operation audit via hooks
  3. Health Dashboard               -- DAG validation with alerting thresholds
  4. Budget Dashboard               -- track budget across workflow stages
  5. Error Rate Monitoring          -- tool failure rates and circuit-breaking
  6. Context Growth Alerting        -- detect runaway context before it hurts

Demonstrates: LoopResult.step_usages, LoopResult.budget_exhausted,
              t.use(), t.health(), t.status(), LoopConfig.step_budget,
              on_tool_result callback, middleware pre_commit/post_commit/
              pre_compile/pre_compress, BlockedError

No external dependencies required.
"""

import time
from datetime import datetime, timezone
from typing import Any

from tract import BlockedError, Tract, TractConfig, TokenBudgetConfig
from tract.loop import LoopConfig, LoopResult, run_loop


# ---------------------------------------------------------------------------
# Shared mock LLM for patterns that need run_loop
# ---------------------------------------------------------------------------

class _MockLLM:
    """Mock LLM client with configurable per-step token usage."""

    def __init__(
        self,
        responses: list[str] | None = None,
        prompt_tokens: int = 300,
        completion_tokens: int = 100,
        tool_calls: list[list[dict]] | None = None,
    ):
        self._responses = responses or []
        self._prompt = prompt_tokens
        self._completion = completion_tokens
        self._tool_calls = tool_calls or []
        self._step = 0

    def chat(self, messages: list[dict], **kwargs: Any) -> dict:
        step = self._step
        self._step += 1

        content = (
            self._responses[step]
            if step < len(self._responses)
            else f"Step {step + 1} response."
        )

        msg: dict[str, Any] = {"role": "assistant", "content": content}

        if step < len(self._tool_calls) and self._tool_calls[step]:
            msg["tool_calls"] = [
                {
                    "id": f"call_{step}_{i}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc.get("args", "{}")},
                }
                for i, tc in enumerate(self._tool_calls[step])
            ]

        # Vary token counts per step to make tracking interesting
        scale = 1.0 + step * 0.3
        return {
            "choices": [{"message": msg}],
            "usage": {
                "prompt_tokens": int(self._prompt * scale),
                "completion_tokens": int(self._completion * scale),
                "total_tokens": int((self._prompt + self._completion) * scale),
            },
        }

    def close(self) -> None:
        pass


# ===================================================================
# Pattern 1: Step-by-Step Token Tracking
# ===================================================================

def token_tracking():
    """Track per-step token usage and identify cost hotspots."""

    print("=" * 60)
    print("1. Step-by-Step Token Tracking")
    print("=" * 60)
    print()

    # Mock LLM with increasing token usage per step (simulates growing context)
    mock = _MockLLM(
        responses=[
            "Starting analysis of the dataset...",
            "Found 3 anomalies in the revenue data.",
            "Cross-referencing with customer churn metrics.",
            "Generating executive summary with recommendations.",
        ],
        prompt_tokens=400,
        completion_tokens=150,
    )

    with Tract.open(llm_client=mock) as t:
        t.system("You are a data analyst.")

        config = LoopConfig(
            max_steps=4,
            stop_on_no_tool_call=False,
        )

        result = run_loop(t, task="Analyze Q4 metrics.", config=config)

        # --- Per-step breakdown from step_usages ---
        print(f"  {'Step':>4}  {'Prompt':>8}  {'Completion':>10}  {'Total':>8}  {'Cumulative':>10}")
        print(f"  {'-' * 48}")

        cumulative = 0
        ALERT_THRESHOLD = 1000  # alert if any single step exceeds this

        alerts = []
        for i, usage in enumerate(result.step_usages):
            cumulative += usage.total_tokens
            flag = " << ALERT" if usage.total_tokens > ALERT_THRESHOLD else ""
            if flag:
                alerts.append(i + 1)
            print(
                f"  {i + 1:>4}  {usage.prompt_tokens:>8}  "
                f"{usage.completion_tokens:>10}  {usage.total_tokens:>8}  "
                f"{cumulative:>10}{flag}"
            )

        print()
        result.pprint()

        if alerts:
            print(f"  ALERTS: steps {alerts} exceeded {ALERT_THRESHOLD}-token threshold")
        else:
            print(f"  No alerts (all steps under {ALERT_THRESHOLD} tokens)")

        # Verify data is present and sane
        assert result.steps == 4, f"Expected 4 steps, got {result.steps}"
        assert result.total_tokens > 0, "Should have recorded token usage"
        assert len(result.step_usages) == 4, "Should have 4 step usages"

    print()
    print("PASSED")


# ===================================================================
# Pattern 2: Middleware-Based Audit Trail
# ===================================================================

def audit_trail():
    """Build audit trail via middleware hooks."""

    print()
    print("=" * 60)
    print("2. Middleware-Based Audit Trail")
    print("=" * 60)
    print()

    audit_log: list[dict] = []

    with Tract.open() as t:

        # --- Register audit middleware for multiple events ---

        def audit_commit(ctx):
            audit_log.append({
                "event": "commit",
                "time": datetime.now(timezone.utc).isoformat(),
                "branch": ctx.branch,
                "hash": ctx.commit.commit_hash[:8] if ctx.commit else "pending",
                "content_type": ctx.commit.content_type if ctx.commit else "unknown",
            })

        def audit_compile(ctx):
            audit_log.append({
                "event": "compile",
                "time": datetime.now(timezone.utc).isoformat(),
                "branch": ctx.branch,
            })

        def audit_compress(ctx):
            audit_log.append({
                "event": "compress",
                "time": datetime.now(timezone.utc).isoformat(),
                "branch": ctx.branch,
            })

        t.use("post_commit", audit_commit)
        t.use("pre_compile", audit_compile)
        t.use("pre_compress", audit_compress)

        # --- Perform operations ---
        t.system("You are a financial analyst.")
        t.user("Review Q3 earnings.")
        t.assistant("Q3 revenue was $4.2M, up 18% YoY.")
        t.user("Compare with Q2.")
        t.assistant("Q2 was $3.8M, so Q3 grew 10.5% QoQ.")

        # Compile triggers pre_compile middleware
        ctx = t.compile()

        # Compress triggers pre_compress middleware
        t.compress(content="Q2: $3.8M, Q3: $4.2M (+18% YoY, +10.5% QoQ).")

        # --- Display audit trail ---
        print(f"  {'#':>3}  {'Event':<10}  {'Branch':<10}  {'Details'}")
        print(f"  {'-' * 50}")
        for i, entry in enumerate(audit_log):
            detail = ""
            if entry["event"] == "commit":
                detail = f"type={entry['content_type']}, hash={entry['hash']}"
            print(f"  {i + 1:>3}  {entry['event']:<10}  {entry['branch']:<10}  {detail}")

        print()
        print(f"  Total audit entries: {len(audit_log)}")

        # Verify: should have commits + compile + compress
        commit_events = [e for e in audit_log if e["event"] == "commit"]
        compile_events = [e for e in audit_log if e["event"] == "compile"]
        compress_events = [e for e in audit_log if e["event"] == "compress"]

        assert len(commit_events) >= 5, f"Expected >=5 commit events, got {len(commit_events)}"
        assert len(compile_events) >= 1, "Expected at least 1 compile event"
        assert len(compress_events) >= 1, "Expected at least 1 compress event"

    print()
    print("PASSED")


# ===================================================================
# Pattern 3: Health Dashboard
# ===================================================================

def health_dashboard():
    """Build a health dashboard from t.health() + metrics."""

    print()
    print("=" * 60)
    print("3. Health Dashboard")
    print("=" * 60)
    print()

    with Tract.open() as t:
        # Build up a tract with multiple branches and operations
        t.system("You are a project manager.")
        t.user("Initialize project tracker.")
        t.assistant("Project tracker ready.")

        # Create branches for different workstreams
        t.branch("feature-auth", switch=True)
        t.user("Implement OAuth2 login flow.")
        t.assistant("OAuth2 flow implemented with PKCE.")
        t.switch("main")

        t.branch("feature-api", switch=True)
        t.user("Design REST API endpoints.")
        t.assistant("12 endpoints designed following OpenAPI 3.0 spec.")
        t.switch("main")

        # Merge one branch
        t.merge("feature-auth")

        # Add more commits on main
        t.user("Review overall architecture.")
        t.assistant("Architecture review complete. All components aligned.")

        # --- Run health check ---
        report = t.health()

        # --- Dashboard display ---
        status_icon = "OK" if report.healthy else "ISSUES"
        print(f"  Health Status:     [{status_icon}]")
        print(f"  Commit Count:      {report.commit_count}")
        print(f"  Branch Count:      {report.branch_count}")
        print(f"  Orphan Commits:    {report.orphan_count}")
        print(f"  Missing Blobs:     {len(report.missing_blobs)}")
        print(f"  Missing Parents:   {len(report.missing_parents)}")
        print(f"  Unreachable:       {len(report.unreachable_commits)}")
        print(f"  Warnings:          {len(report.warnings)}")

        # --- Alerting thresholds ---
        alerts = []
        if not report.healthy:
            alerts.append("CRITICAL: DAG integrity check failed")
        if report.orphan_count > 10:
            alerts.append(f"WARNING: {report.orphan_count} orphan commits (>10 threshold)")
        if len(report.missing_blobs) > 0:
            alerts.append(f"CRITICAL: {len(report.missing_blobs)} missing blobs")
        if report.commit_count > 1000:
            alerts.append(f"INFO: {report.commit_count} commits -- consider GC")

        print()
        if alerts:
            print("  Alerts:")
            for a in alerts:
                print(f"    - {a}")
        else:
            print("  Alerts: None -- all thresholds within limits")

        # --- Summary line ---
        print()
        print(f"  Summary: {report.summary()}")

        # Verify health
        assert report.healthy, "Tract should be healthy"
        assert report.commit_count > 0, "Should have commits"
        assert report.branch_count >= 2, "Should have at least 2 branches"
        assert len(report.missing_blobs) == 0, "No missing blobs expected"

    print()
    print("PASSED")


# ===================================================================
# Pattern 4: Budget Dashboard
# ===================================================================

def budget_dashboard():
    """Track remaining budget across workflow stages."""

    print()
    print("=" * 60)
    print("4. Budget Dashboard")
    print("=" * 60)
    print()

    # Track per-stage token consumption by measuring tokens added within
    # each stage.  We snapshot token_count at the START of each stage so
    # that compression (which shrinks the overall count) doesn't confuse
    # the per-stage accounting.
    stage_budgets = {
        "research": 2000,
        "analysis": 1500,
        "synthesis": 1000,
    }

    stage_usage: dict[str, dict] = {}

    config = TractConfig(token_budget=TokenBudgetConfig(max_tokens=5000))
    with Tract.open(config=config) as t:
        t.system("You are a market research agent.")

        # --- Stage: Research ---
        t.configure(compile_strategy="full")
        research_start = t.status().token_count

        research_items = [
            "Competitor A launched new AI product at $99/mo, targeting SMB.",
            "Industry report: SaaS market growing 22% YoY, AI features key differentiator.",
            "Customer survey: 68% want better analytics, 45% want AI recommendations.",
            "Competitor B acquired data company for $50M, expanding platform.",
        ]
        for item in research_items:
            t.user(item, message=item[:60] + "...")
            t.assistant(f"Noted: {item[:40]}...", message=f"Ack research finding")

        research_end = t.status().token_count
        research_tokens = research_end - research_start
        stage_usage["research"] = {
            "tokens": research_tokens,
            "budget": stage_budgets["research"],
            "remaining": stage_budgets["research"] - research_tokens,
        }

        # Compress research before analysis (frees context for next stages)
        t.compress(content=(
            "Research findings: Competitor A launched AI ($99/mo SMB). "
            "SaaS +22% YoY. Customers want analytics (68%) and AI (45%). "
            "Competitor B acquired data co for $50M."
        ))

        # --- Stage: Analysis ---
        t.transition("analysis")
        analysis_start = t.status().token_count

        t.user(
            "Analyze competitive positioning based on research. Key factors: "
            "pricing, feature set, market momentum, customer satisfaction.",
            message="Analyze competitive positioning",
        )
        t.assistant(
            "Competitive analysis: We lead in customer satisfaction (NPS 52 vs "
            "industry 38). Pricing competitive at $79/mo. Feature gap in AI -- "
            "Competitor A has 6-month head start. Market momentum strong with "
            "15% QoQ growth vs industry 5.5%.",
            message="Competitive analysis complete",
        )

        analysis_end = t.status().token_count
        analysis_tokens = analysis_end - analysis_start
        stage_usage["analysis"] = {
            "tokens": analysis_tokens,
            "budget": stage_budgets["analysis"],
            "remaining": stage_budgets["analysis"] - analysis_tokens,
        }

        # --- Stage: Synthesis ---
        t.transition("synthesis")
        synthesis_start = t.status().token_count

        t.user("Synthesize findings into executive brief.", message="Synthesize")
        t.assistant(
            "Executive Brief: Strong position with NPS lead. Accelerate AI "
            "roadmap to close 6-month gap. Pricing holds. Watch Competitor B "
            "data acquisition for platform expansion threat.",
            message="Executive brief",
        )

        synthesis_end = t.status().token_count
        synthesis_tokens = synthesis_end - synthesis_start
        stage_usage["synthesis"] = {
            "tokens": synthesis_tokens,
            "budget": stage_budgets["synthesis"],
            "remaining": stage_budgets["synthesis"] - synthesis_tokens,
        }

        # --- Dashboard display ---
        total_budget = sum(stage_budgets.values())
        total_stage_used = sum(info["tokens"] for info in stage_usage.values())
        final_context = t.status().token_count

        print(f"  {'Stage':<12}  {'Budget':>8}  {'Added':>8}  {'Remaining':>10}  {'Status'}")
        print(f"  {'-' * 55}")
        for stage_name, info in stage_usage.items():
            pct = info['tokens'] / info['budget'] * 100 if info['budget'] > 0 else 0
            status = "OK" if pct < 80 else ("WARNING" if pct < 100 else "OVER")
            print(
                f"  {stage_name:<12}  {info['budget']:>8}  {info['tokens']:>8}  "
                f"{info['remaining']:>10}  {status} ({pct:.0f}%)"
            )

        print(f"  {'-' * 55}")
        print(
            f"  {'TOTAL':<12}  {total_budget:>8}  {total_stage_used:>8}  "
            f"{total_budget - total_stage_used:>10}"
        )
        print()
        print(f"  Tokens added across stages: {total_stage_used}")
        print(f"  Final context size: {final_context} tokens "
              f"(smaller due to compression)")
        print(f"  Overall budget utilization: "
              f"{total_stage_used / total_budget:.0%}")

        # Verify budget tracking works
        assert total_stage_used > 0, "Should have used tokens across stages"
        assert total_stage_used < total_budget, "Should be under total budget"
        # Each stage should have added tokens
        for name, info in stage_usage.items():
            assert info["tokens"] > 0, f"Stage {name} should have added tokens"

    print()
    print("PASSED")


# ===================================================================
# Pattern 5: Error Rate Monitoring
# ===================================================================

def error_rate_monitoring():
    """Monitor tool error rates and circuit-break on high failure."""

    print()
    print("=" * 60)
    print("5. Error Rate Monitoring")
    print("=" * 60)
    print()

    # Track tool results via on_tool_result callback
    tool_stats: dict[str, dict] = {}

    def track_tool_result(tool_name: str, output: str, status: str) -> None:
        if tool_name not in tool_stats:
            tool_stats[tool_name] = {"success": 0, "error": 0, "total": 0}
        tool_stats[tool_name]["total"] += 1
        tool_stats[tool_name][status] += 1

    # Mock LLM that calls tools across multiple steps
    tool_sequence = [
        [{"name": "search_db"}],
        [{"name": "search_db"}, {"name": "fetch_url"}],
        [{"name": "fetch_url"}],
        [{"name": "calculate"}],
        [],  # no tool calls -> loop stops
    ]
    mock = _MockLLM(
        responses=[
            "Let me search the database...",
            "Searching more and fetching a URL...",
            "Fetching another URL...",
            "Running calculation...",
            "Analysis complete.",
        ],
        tool_calls=tool_sequence,
    )

    # Tool handlers: search_db succeeds, fetch_url fails intermittently,
    # calculate always succeeds
    call_count = {"fetch_url": 0}

    def search_db(**kwargs: Any) -> str:
        return "Found 42 matching records."

    def fetch_url(**kwargs: Any) -> str:
        call_count["fetch_url"] += 1
        if call_count["fetch_url"] % 2 == 0:
            raise ConnectionError("HTTP 503 Service Unavailable")
        return "Page content: quarterly earnings report."

    def calculate(**kwargs: Any) -> str:
        return "Result: $4.2M revenue, 18% growth."

    with Tract.open(llm_client=mock) as t:
        t.system("You are a research analyst.")

        config = LoopConfig(max_steps=5, stop_on_no_tool_call=True)

        result = run_loop(
            t,
            task="Analyze market data.",
            config=config,
            tool_handlers={
                "search_db": search_db,
                "fetch_url": fetch_url,
                "calculate": calculate,
            },
            on_tool_result=track_tool_result,
        )

        # --- Display error rates ---
        CIRCUIT_BREAK_THRESHOLD = 0.50  # 50% error rate

        print(f"  {'Tool':<15}  {'Total':>6}  {'OK':>4}  {'Fail':>5}  {'Error Rate':>10}  {'Status'}")
        print(f"  {'-' * 60}")

        problematic_tools = []
        for name, stats in sorted(tool_stats.items()):
            total = stats["total"]
            errors = stats["error"]
            rate = errors / total if total > 0 else 0.0
            status = "CIRCUIT-BREAK" if rate >= CIRCUIT_BREAK_THRESHOLD else "OK"
            if rate >= CIRCUIT_BREAK_THRESHOLD:
                problematic_tools.append(name)
            print(
                f"  {name:<15}  {total:>6}  {stats['success']:>4}  "
                f"{errors:>5}  {rate:>9.0%}  {status}"
            )

        print()
        result.pprint()

        if problematic_tools:
            print(f"  ACTION: disable/investigate: {', '.join(problematic_tools)}")
        else:
            print("  All tools within acceptable error rates.")

        # Verify tracking captured data
        assert len(tool_stats) > 0, "Should have tracked tool results"
        assert result.tool_calls > 0, "Should have executed tool calls"

    print()
    print("PASSED")


# ===================================================================
# Pattern 6: Context Growth Alerting
# ===================================================================

def context_growth_alerting():
    """Alert when context growth rate exceeds expectations."""

    print()
    print("=" * 60)
    print("6. Context Growth Alerting")
    print("=" * 60)
    print()

    MAX_CONTEXT = 2000  # token ceiling
    GROWTH_ALERT_PCT = 30  # alert if single exchange adds >30% of ceiling

    with Tract.open() as t:
        t.system("You are a technical architect.")

        growth_log: list[dict] = []
        prev_tokens = t.compile().token_count

        # Simulate a conversation with varying message sizes
        exchanges = [
            (
                "Review the authentication system.",
                "Auth uses JWT with 24h expiry and refresh token rotation.",
            ),
            (
                "What about the database layer?",
                "PostgreSQL with connection pooling (min=5, max=20). "
                "Read replicas for analytics queries. Migrations via Alembic.",
            ),
            (
                "Describe the full caching architecture including Redis cluster setup, "
                "eviction policies, TTL strategies per data type, cache warming on deploy, "
                "monitoring setup with Prometheus exporters, failover configuration, "
                "and the circuit breaker pattern for cache miss cascades.",
                "Caching: 3-node Redis Cluster with hash slots. Eviction: allkeys-lru for "
                "sessions, volatile-ttl for features. TTLs: sessions 30min, feature flags "
                "5min, user profiles 1h, product catalog 4h. Cache warming: background job "
                "on deploy populates top-1000 SKUs and active sessions. Monitoring: "
                "redis_exporter to Prometheus, Grafana dashboards for hit rate, memory, "
                "evictions. Circuit breaker: 5 failures in 10s trips breaker, half-open "
                "after 30s, full recovery after 3 successful probes. Failover: Sentinel "
                "with 2/3 quorum, automatic promotion, client-side retry with exponential "
                "backoff (100ms base, 3 retries, 2x multiplier).",
            ),
            (
                "Summarize API rate limiting.",
                "Rate limiting: token bucket at 100 req/s per API key, "
                "sliding window for burst protection.",
            ),
            (
                "Detail the entire CI/CD pipeline from commit to production including "
                "pre-commit hooks, unit tests, integration tests, security scanning, "
                "container building, staging deployment, canary analysis, and rollback.",
                "CI/CD: Pre-commit (ruff, mypy, secrets scan). PR: unit tests (pytest, "
                "500+ tests, 94% coverage), integration tests (testcontainers for Postgres "
                "and Redis), SAST (Semgrep), DAST (ZAP). Build: multi-stage Docker (slim "
                "base, 180MB final). Deploy: ArgoCD GitOps to staging first, 30min soak "
                "test with synthetic traffic. Canary: Istio 5%->25%->50%->100% over 2h. "
                "Metrics gates: error rate <0.1%, p99 <200ms, CPU <70%. Rollback: automatic "
                "on gate failure, manual via ArgoCD. Post-deploy: smoke tests, Datadog "
                "monitors, PagerDuty alerts.",
            ),
        ]

        alerts = []
        for i, (user_msg, asst_msg) in enumerate(exchanges):
            t.user(user_msg)
            t.assistant(asst_msg)

            ctx = t.compile()
            current_tokens = ctx.token_count
            delta = current_tokens - prev_tokens
            growth_pct = (delta / MAX_CONTEXT * 100) if MAX_CONTEXT > 0 else 0
            utilization = current_tokens / MAX_CONTEXT * 100

            entry = {
                "exchange": i + 1,
                "tokens": current_tokens,
                "delta": delta,
                "growth_pct": growth_pct,
                "utilization": utilization,
            }
            growth_log.append(entry)

            if growth_pct > GROWTH_ALERT_PCT:
                alerts.append(entry)

            prev_tokens = current_tokens

        # --- Display growth table ---
        print(
            f"  {'#':>3}  {'Tokens':>8}  {'Delta':>7}  "
            f"{'Growth%':>8}  {'Util%':>7}  {'Alert'}"
        )
        print(f"  {'-' * 52}")
        for entry in growth_log:
            flag = " << ALERT" if entry["growth_pct"] > GROWTH_ALERT_PCT else ""
            print(
                f"  {entry['exchange']:>3}  {entry['tokens']:>8}  "
                f"+{entry['delta']:>6}  {entry['growth_pct']:>7.1f}%  "
                f"{entry['utilization']:>6.1f}%{flag}"
            )

        print()
        final = growth_log[-1]
        print(f"  Final context: {final['tokens']} / {MAX_CONTEXT} tokens "
              f"({final['utilization']:.0f}%)")

        if alerts:
            print(f"  ALERTS: {len(alerts)} exchange(s) exceeded "
                  f"{GROWTH_ALERT_PCT}% growth threshold")
            for a in alerts:
                print(f"    - Exchange {a['exchange']}: +{a['delta']} tokens "
                      f"({a['growth_pct']:.1f}% of ceiling)")
            print()
            print("  Recommendation: compress or switch to adaptive strategy "
                  "before context exceeds ceiling.")
        else:
            print(f"  No alerts (all exchanges under {GROWTH_ALERT_PCT}% growth)")

        # Verify tracking
        assert len(growth_log) == 5, "Should track all 5 exchanges"
        assert growth_log[-1]["tokens"] > growth_log[0]["tokens"], "Context should grow"

    print()
    print("PASSED")


# ===================================================================
# Main
# ===================================================================

def main():
    token_tracking()
    audit_trail()
    health_dashboard()
    budget_dashboard()
    error_rate_monitoring()
    context_growth_alerting()

    print()
    print("=" * 60)
    print("Summary: Production Monitoring Patterns")
    print("=" * 60)
    print()
    print("  Pattern                     Tract Primitives Used")
    print("  --------------------------  -----------------------------------------")
    print("  Token tracking              LoopResult.step_usages, total_tokens")
    print("  Audit trail                 t.use() on post_commit/pre_compile/pre_compress")
    print("  Health dashboard            t.health() -> HealthReport")
    print("  Budget dashboard            t.status(), t.transition(), TokenBudgetConfig")
    print("  Error rate monitoring       on_tool_result callback, tool_handlers")
    print("  Context growth alerting     t.compile().token_count, threshold math")
    print()
    print("  Key principle: instrument with middleware and callbacks,")
    print("  not wrapper functions. Tract's event system gives you")
    print("  structured data at every operation boundary.")
    print()
    print("Done.")


# Alias for pytest discovery
test_production_monitoring = main


if __name__ == "__main__":
    main()


# --- See also ---
# Budget management:     optimization/01_budget_management.py
# Observability:         config_and_middleware/06_observability.py
# Graceful degradation:  error_handling/02_graceful_degradation.py
