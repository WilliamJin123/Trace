"""Data Preservation

Compression is powerful but destructive. Multiple mechanisms protect
specific content from being compressed away:

  - Priority.PINNED annotation: hard protection at the engine level
  - t.directive(): PINNED by default, survives compression
  - t.configure(): set auto_compress_threshold to control triggers
  - pre_compress middleware: block compression conditionally

The layered defense:
  Layer 1: PINNED priority -> hard protection, engine level
  Layer 2: Directives -> PINNED by default, compiled into context
  Layer 3: Middleware -> programmatic guards (tag checks, thresholds)
  Layer 4: Config -> auto_compress_threshold controls triggers

Demonstrates: Priority.PINNED, t.annotate(), t.directive(),
              pre_compress middleware, BlockedError

No LLM required.
"""

from tract import Tract, Priority, DialogueContent, BlockedError


def main():
    with Tract.open() as t:

        # --- Create some conversation history ---

        print("=== Building History ===\n")

        t.register_tag("important")
        t.register_tag("credentials")

        t.system("You are a helpful assistant.")
        t.user("What is Python?")
        t.assistant("Python is a high-level programming language.")
        t.user("What about decorators?")
        t.assistant("Decorators are functions that modify other functions.")
        important = t.commit(
            DialogueContent(role="user", text="CRITICAL: Remember this API key format: sk-xxx"),
            tags=["important", "credentials"],
        )
        t.assistant("I will remember that format.")
        t.user("What about list comprehensions?")
        t.assistant("List comprehensions are concise ways to create lists.")

        print(f"  Total commits: {len(t.log())}")
        print(f"  Important commit: {important.commit_hash[:8]} (tagged: {important.tags})")

        # --- Annotate with PINNED ---

        print("\n=== Priority Annotation ===\n")

        t.annotate(important.commit_hash, Priority.PINNED, reason="credential data")

        print(f"  Pinned commit: {important.commit_hash[:8]}")
        print("  PINNED commits are preserved by the compression engine")
        print("  regardless of middleware -- it's a hard guarantee.")

        # --- Directives are PINNED by default ---

        print("\n=== Directives (PINNED by Default) ===\n")

        t.directive(
            "api-format",
            "The API key format is sk-xxx. Always validate keys against this pattern.",
        )
        print("  Directive 'api-format' committed with PINNED priority")
        print("  Directives survive compression and appear in compiled context")

        # --- Pre-compress middleware: block on tagged commits ---

        print("\n=== Pre-Compress Middleware ===\n")

        def protect_credentials(ctx):
            """Block compression when credential-tagged commits exist."""
            for ci in ctx.tract.log():
                if "credentials" in (ci.tags or []):
                    raise BlockedError(
                        "pre_compress",
                        ["Cannot compress: credential-tagged commits present"],
                    )

        cred_id = t.use("pre_compress", protect_credentials)
        print(f"  Registered pre_compress guard: {cred_id}")
        print("  When compression is attempted, handler checks for credential tags")

        # --- Pre-compress middleware: minimum history threshold ---

        print("\n=== Minimum History Guard ===\n")

        def require_min_history(ctx):
            """Require at least 20 commits before allowing compression."""
            count = len(ctx.tract.log())
            if count < 20:
                raise BlockedError(
                    "pre_compress",
                    [f"Too few commits to compress: {count} (need >= 20)"],
                )

        hist_id = t.use("pre_compress", require_min_history)
        print(f"  Registered pre_compress threshold: {hist_id}")
        print("  Compression requires at least 20 commits in the log")

        # --- Config: auto_compress_threshold ---

        print("\n=== Auto-Compress Threshold Config ===\n")

        t.configure(auto_compress_threshold=100)
        threshold = t.get_config("auto_compress_threshold")
        print(f"  auto_compress_threshold: {threshold}")
        print("  Automatic compression triggers only after 100 commits")

        # --- Layered defense summary ---

        print("\n=== Layered Defense Summary ===\n")
        print("  Layer 1: PINNED priority   -> hard protection at engine level")
        print("  Layer 2: Directives        -> PINNED by default, compiled into context")
        print("  Layer 3: Middleware         -> programmatic guards (tags, thresholds)")
        print("  Layer 4: Config            -> auto_compress_threshold controls triggers")

        # --- Show protected content in log ---

        print("\n=== Log ===\n")
        for ci in t.log():
            tags_str = f" [{', '.join(ci.tags)}]" if ci.tags else ""
            print(f"  {ci.commit_hash[:8]}  {ci.content_type:14s}{tags_str}  {ci.message[:50]}")


if __name__ == "__main__":
    main()
