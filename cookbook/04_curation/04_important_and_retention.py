"""IMPORTANT Priority and Retention Criteria

Some context is too important to lose in compression, but not important
enough to pin forever. IMPORTANT sits between NORMAL and PINNED — it tells
the compression engine to be conservative with this commit.

Add fuzzy guidance with retain= (natural language for the summarizer) and
deterministic checks with retain_match= (must appear in the summary).
Both can combine: fuzzy guides the LLM, deterministic verifies.

Demonstrates: Priority.IMPORTANT, annotate(retain=, retain_match=),
              shorthand with priority=IMPORTANT, RetentionCriteria,
              retain_match_mode="regex", the full priority spectrum
"""

from tract import Priority, Tract


def main():
    t = Tract.open()

    t.system("You are a contract review assistant.")

    # --- Style 1: Explicit annotate() with fuzzy retention ---

    print("=== Style 1: annotate() with fuzzy retain= ===\n")

    requirements = t.user(
        "The contract specifies:\n"
        "- Total value: $2.4M over 3 years\n"
        "- Payment terms: Net 30\n"
        "- Penalty clause: 5% per month late"
    )

    ann = t.annotate(
        requirements.commit_hash,
        Priority.IMPORTANT,
        retain="Preserve all dollar amounts, payment terms, and penalty percentages",
    )
    print(f"Annotated {requirements.commit_hash[:8]} as IMPORTANT")
    print(f"  Fuzzy guidance: {ann.retention.instructions}\n")

    # --- Style 2: annotate() with deterministic retain_match ---

    print("=== Style 2: annotate() with retain_match= ===\n")

    deadline = t.user("Hard deadline: delivery by 2026-06-15 or the deal is off.")

    t.annotate(
        deadline.commit_hash,
        Priority.IMPORTANT,
        retain_match=["2026-06-15"],
    )
    print(f"Annotated {deadline.commit_hash[:8]} with deterministic match")
    print(f"  Must survive compression: '2026-06-15'\n")

    # --- Style 3: Shorthand with priority + retention ---

    print("=== Style 3: Shorthand user() with priority= ===\n")

    budget = t.user(
        "Updated budget ceiling: $3.1M (was $2.4M). Board approved 2026-02-20.",
        priority=Priority.IMPORTANT,
        retain="Keep the updated budget figure and board approval date",
        retain_match=["$3.1M", "2026-02-20"],
    )
    print(f"Committed + annotated in one call: {budget.commit_hash[:8]}\n")

    # --- Style 4: Regex match mode ---

    print("=== Style 4: Regex retain_match_mode ===\n")

    dates_msg = t.user(
        "Milestone dates: Phase 1 by 2026-04-01, Phase 2 by 2026-08-15, "
        "Phase 3 by 2026-12-31."
    )
    t.annotate(
        dates_msg.commit_hash,
        Priority.IMPORTANT,
        retain_match=[r"\d{4}-\d{2}-\d{2}"],
        retain_match_mode="regex",
    )
    print(f"Annotated {dates_msg.commit_hash[:8]} with regex pattern")
    print(f"  Any YYYY-MM-DD date must survive compression\n")

    # --- The full priority spectrum ---

    print("=== Priority spectrum (SKIP < NORMAL < IMPORTANT < PINNED) ===\n")

    t.assistant("I've reviewed the contract terms. Here's my analysis...")
    noise = t.user("[debug] internal trace id: abc-123-xyz")
    t.annotate(noise.commit_hash, Priority.SKIP, reason="debug noise")

    ctx = t.compile()
    print(f"Compiled: {len(ctx.messages)} messages (SKIP hidden, everything else visible)\n")
    ctx.pprint()

    t.close()


if __name__ == "__main__":
    main()
