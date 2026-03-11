"""Context Portability -- export, share, and import context across tracts

Tract's export_state()/load_state() let you serialize an entire context DAG
as portable JSON.  No other LLM framework can do this: your full commit
history, metadata, priorities, and branch info travel as a single dict that
round-trips cleanly into any fresh tract.

Patterns shown:
  1. Basic Export/Import        -- round-trip a tract's state through JSON
  2. JSON File Persistence      -- save state to a .json file, reload later
  3. Cross-Agent Context Transfer -- two agents share context via export/import
  4. Selective Export (metadata-only) -- lightweight export without blob content
  5. Branch Export               -- export a specific branch's context
  6. Export After Compression    -- compressed context stays compact after export

Demonstrates: t.export_state(), t.load_state(), t.compile(), t.branch(),
              t.switch(), t.compress(content=), t.annotate(), json.dump/load,
              Tract.open()

No LLM required.
"""

import json
import os
import tempfile

from tract import Tract, Priority


def main():
    # =================================================================
    # 1. Basic Export/Import
    # =================================================================
    #
    # Export a tract's full state as a JSON-serializable dict, then
    # import it into a completely new tract.  The compiled context in
    # the target should contain all the original content.

    print("=" * 60)
    print("1. Basic Export/Import")
    print("=" * 60)
    print()

    with Tract.open() as source:
        source.system("You are a data analyst.")
        source.user("Analyze Q4 revenue trends")
        source.assistant("Revenue grew 12% QoQ driven by enterprise expansion.")
        state = source.export_state()

    # Import into a completely new tract
    with Tract.open() as target:
        loaded = target.load_state(state)
        compiled = target.compile()
        text = compiled.to_text()
        assert "data analyst" in text
        assert "revenue" in text.lower()
        print(f"  Exported {len(state['commits'])} commits, loaded {loaded}")
        print(f"  Compiled: {len(compiled.messages)} messages, ~{compiled.token_count} tokens")
        print(f"  State keys: {sorted(state.keys())}")

    print("\n  Basic export/import: PASSED")

    # =================================================================
    # 2. JSON File Persistence
    # =================================================================
    #
    # Save the exported state to a JSON file on disk, then load it
    # in a fresh session.  This is the simplest way to share context
    # between processes, machines, or teams.

    print()
    print("=" * 60)
    print("2. JSON File Persistence")
    print("=" * 60)
    print()

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
    os.close(tmp_fd)

    try:
        # Session 1: build context and save to file
        with Tract.open() as t:
            t.system("You are an API design reviewer.")
            t.user("Review the /users endpoint schema.")
            t.assistant(
                "The /users endpoint should return paginated results with "
                "cursor-based pagination. Add a 'next_cursor' field."
            )
            t.user("What about error responses?")
            t.assistant(
                "Use RFC 7807 Problem Details: type, title, status, detail, instance."
            )

            state = t.export_state()

        # Write to disk
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        file_size = os.path.getsize(tmp_path)
        print(f"  Saved to file: {file_size:,} bytes")
        print(f"  Contains {len(state['commits'])} commits")

        # Session 2: load from file into a fresh tract
        with open(tmp_path, "r", encoding="utf-8") as f:
            loaded_state = json.load(f)

        with Tract.open() as t2:
            loaded_count = t2.load_state(loaded_state)
            ctx = t2.compile()
            text = ctx.to_text()
            assert "RFC 7807" in text
            assert "cursor-based pagination" in text
            print(f"  Loaded {loaded_count} commits from file")
            print(f"  Compiled: {len(ctx.messages)} messages, ~{ctx.token_count} tokens")
            print(f"  Content verified: RFC 7807, cursor-based pagination")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    print("\n  JSON file persistence: PASSED")

    # =================================================================
    # 3. Cross-Agent Context Transfer
    # =================================================================
    #
    # Two agents in different sessions share context.  Agent A builds
    # up research context, exports it, and Agent B imports it to
    # continue the work with full history.

    print()
    print("=" * 60)
    print("3. Cross-Agent Context Transfer")
    print("=" * 60)
    print()

    # Agent A: research phase
    with Tract.open() as agent_a:
        agent_a.system("You are a research assistant specializing in ML.")
        agent_a.user("Survey recent advances in context window management.")
        agent_a.assistant(
            "Key papers:\n"
            "1. Landmark Attention -- O(n) context via sparse retrieval\n"
            "2. Ring Attention -- distributed context across devices\n"
            "3. StreamingLLM -- attention sinks for infinite context"
        )
        agent_a.user("Which approach is most practical for production?")
        agent_a.assistant(
            "Ring Attention requires multi-GPU setups. "
            "StreamingLLM is simplest for single-GPU production deployment."
        )

        # Export Agent A's full context
        handoff = agent_a.export_state()
        a_count = len(handoff["commits"])

    # Agent B: continue with Agent A's context
    with Tract.open() as agent_b:
        # Agent B has its own system prompt
        agent_b.system("You are a technical writer.")

        # Import Agent A's research
        imported = agent_b.load_state(handoff)
        print(f"  Agent A produced {a_count} commits")
        print(f"  Agent B imported {imported} commits")

        # Agent B continues the work
        agent_b.user("Write a summary of the StreamingLLM approach.")
        agent_b.assistant(
            "StreamingLLM maintains a small attention sink window, "
            "enabling theoretically infinite context with fixed memory."
        )

        ctx = agent_b.compile()
        text = ctx.to_text()

        # Agent B has both its own and Agent A's context
        assert "research assistant" in text or "ML" in text.lower()
        assert "StreamingLLM" in text
        assert "technical writer" in text
        print(f"  Agent B compiled: {len(ctx.messages)} messages, ~{ctx.token_count} tokens")
        print(f"  Contains Agent A's research + Agent B's additions")

    print("\n  Cross-agent context transfer: PASSED")

    # =================================================================
    # 4. Selective Export (metadata-only)
    # =================================================================
    #
    # Export with include_blobs=False for a lightweight snapshot that
    # captures commit structure (hashes, types, messages, timestamps)
    # without the full content payloads.  Useful for auditing,
    # dashboards, or quick state inspection.

    print()
    print("=" * 60)
    print("4. Selective Export (metadata-only)")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a financial advisor.")
        t.user("What are the risks of concentrated stock positions?")
        t.assistant(
            "Key risks: single-stock volatility, lack of diversification, "
            "liquidity risk during market stress. Recommend max 10% allocation."
        )
        t.user("How should I diversify?")
        t.assistant(
            "Consider: broad market ETFs (VTI/VXUS), bond allocation (BND), "
            "and systematic rebalancing quarterly."
        )

        # Full export (with blobs)
        full_state = t.export_state(include_blobs=True)

        # Metadata-only export (no blobs)
        meta_state = t.export_state(include_blobs=False)

    full_size = len(json.dumps(full_state))
    meta_size = len(json.dumps(meta_state))
    print(f"  Full export size:     {full_size:,} bytes ({len(full_state['commits'])} commits)")
    print(f"  Metadata-only size:   {meta_size:,} bytes ({len(meta_state['commits'])} commits)")
    print(f"  Size reduction:       {(1 - meta_size / full_size) * 100:.0f}%")

    # Metadata export has structure but no payloads
    for entry in meta_state["commits"]:
        assert "hash" in entry
        assert "content_type" in entry
        assert "payload" not in entry  # no blob content
        assert "content_hash" in entry  # hash reference preserved
    print(f"  Metadata entries have: hash, content_type, content_hash, message")
    print(f"  Metadata entries lack: payload (blob content)")

    # Attempting to load metadata-only export loads zero commits
    # because load_state skips entries without payload
    with Tract.open() as t2:
        loaded = t2.load_state(meta_state)
        assert loaded == 0, "Metadata-only export should not load any commits"
        print(f"  load_state on metadata-only: {loaded} commits (expected 0)")

    print("\n  Selective export (metadata-only): PASSED")

    # =================================================================
    # 5. Branch Export
    # =================================================================
    #
    # Switch to a specific branch and export only that branch's
    # context.  export_state() walks from the current HEAD, so
    # switching branches before export gives you branch-specific state.

    print()
    print("=" * 60)
    print("5. Branch Export")
    print("=" * 60)
    print()

    with Tract.open() as t:
        # Main branch: shared context
        t.system("You are a project planner.")
        t.user("Plan the Q1 roadmap.")
        t.assistant("Q1 roadmap: Auth system, API v2, Dashboard redesign.")

        # Create a feature branch with additional work
        t.branch("feature/auth")
        t.user("Detail the auth system plan.")
        t.assistant(
            "Auth plan: OAuth2 + PKCE, JWT with refresh rotation, "
            "RBAC with 4 roles (admin, editor, viewer, guest)."
        )
        t.user("What about SSO?")
        t.assistant("SSO via SAML 2.0 for enterprise customers.")

        # Export from the feature branch
        feature_state = t.export_state()
        feature_commits = len(feature_state["commits"])
        feature_branch = feature_state["branch"]

        # Switch to main and export
        t.switch("main")
        main_state = t.export_state()
        main_commits = len(main_state["commits"])
        main_branch = main_state["branch"]

    print(f"  Main branch export:    {main_commits} commits (branch: {main_branch})")
    print(f"  Feature branch export: {feature_commits} commits (branch: {feature_branch})")
    assert feature_commits > main_commits, "Feature branch should have more commits"
    assert feature_branch == "feature/auth"
    assert main_branch == "main"

    # Verify feature-specific content is only in feature export
    feature_text = json.dumps(feature_state)
    main_text = json.dumps(main_state)
    assert "SAML 2.0" in feature_text
    assert "SAML 2.0" not in main_text
    print(f"  Feature-only content ('SAML 2.0'): present in feature, absent from main")

    # Import feature branch into a new tract
    with Tract.open() as t2:
        loaded = t2.load_state(feature_state)
        ctx = t2.compile()
        text = ctx.to_text()
        assert "SAML 2.0" in text
        assert "Q1 roadmap" in text  # shared ancestor content is included
        print(f"  Imported feature branch: {loaded} commits")
        print(f"  Compiled: {len(ctx.messages)} messages (includes shared + feature)")

    print("\n  Branch export: PASSED")

    # =================================================================
    # 6. Export After Compression
    # =================================================================
    #
    # After compressing a tract (manually, without LLM), the exported
    # state reflects the compressed DAG.  This verifies that
    # export_state faithfully captures the post-compression state.

    print()
    print("=" * 60)
    print("6. Export After Compression")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a code reviewer.")

        # Build up a multi-turn conversation
        for i in range(5):
            t.user(f"Review function_{i}: handles data transformation step {i}.")
            t.assistant(
                f"Function_{i} review: logic is correct but add error handling "
                f"for edge case {i}. Consider extracting validation into a helper."
            )

        pre_compress_state = t.export_state()
        pre_count = len(pre_compress_state["commits"])
        pre_ctx = t.compile()
        pre_tokens = pre_ctx.token_count

        # Manual compression: replace the 10 review messages with a summary
        t.compress(
            content=(
                "Code review summary: All 5 functions reviewed. Common themes: "
                "add error handling for edge cases, extract validation helpers. "
                "All logic correct, style consistent."
            )
        )

        post_compress_state = t.export_state()
        post_count = len(post_compress_state["commits"])
        post_ctx = t.compile()
        post_tokens = post_ctx.token_count

    print(f"  Before compression: {pre_count} commits, ~{pre_tokens} tokens")
    print(f"  After compression:  {post_count} commits, ~{post_tokens} tokens")
    assert post_tokens < pre_tokens, "Compressed context should use fewer tokens"
    print(f"  Token reduction:    {pre_tokens - post_tokens} tokens saved")

    # Import the compressed state into a fresh tract
    with Tract.open() as t2:
        loaded = t2.load_state(post_compress_state)
        ctx = t2.compile()
        text = ctx.to_text()
        assert "code review" in text.lower() or "Code review summary" in text
        print(f"  Imported compressed state: {loaded} commits")
        print(f"  Compiled: {len(ctx.messages)} messages, ~{ctx.token_count} tokens")
        # The imported context should be compact
        assert ctx.token_count <= pre_tokens
        print(f"  Verified: imported state preserves compression")

    print("\n  Export after compression: PASSED")

    # =================================================================
    # Summary
    # =================================================================

    print()
    print("=" * 60)
    print("Summary: Context Portability Patterns")
    print("=" * 60)
    print()
    print("  Pattern                     Key API")
    print("  --------------------------  ----------------------------------")
    print("  Basic Export/Import         export_state() -> load_state()")
    print("  JSON File Persistence       json.dump(state) -> json.load()")
    print("  Cross-Agent Transfer        export from A, load into B")
    print("  Metadata-Only Export        export_state(include_blobs=False)")
    print("  Branch Export               switch() then export_state()")
    print("  Export After Compression    compress() then export_state()")
    print()
    print("  No other LLM framework can serialize its entire context DAG")
    print("  as portable JSON.  Tract's export/import makes context a")
    print("  first-class, transferable resource.")
    print()
    print("Done.")


# Alias for pytest discovery
test_context_portability = main


if __name__ == "__main__":
    main()
