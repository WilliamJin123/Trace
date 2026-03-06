"""Research Workflow: ingest -> organize -> synthesize

A research pipeline using metadata, tagging, and transitions. No LLM required.

Demonstrates: metadata(), tags, transition rules, branch workflow, config
"""

from tract import Tract, DialogueContent, resolve_all_configs


def main():
    with Tract.open() as t:

        print("=== Setting Up Research Workflow ===\n")

        t.rule("stage", trigger="active",
               action={"type": "set_config", "key": "stage", "value": "ingest"})
        t.rule("ingest-strategy", trigger="active",
               action={"type": "set_config", "key": "compile_strategy", "value": "full"})

        gate = lambda v: {"type": "require", "condition": {
            "type": "threshold", "metric": "commit_count", "op": ">=", "value": v}}
        t.rule("organize-gate", trigger="transition:organize", action=gate(6))
        t.rule("synthesize-gate", trigger="transition:synthesize", action=gate(3))

        print("  Workflow rules created")

        print("\n=== Ingest Phase ===\n")

        for tag in ["source", "raft", "paxos", "pbft", "synthesis", "final"]:
            t.register_tag(tag)

        t.system("Research context for: distributed systems consensus algorithms")

        sources = [
            ("Raft - leader election, log replication, safety.", ["source", "raft"]),
            ("Paxos - proposers, acceptors, learners. Proven correct.", ["source", "paxos"]),
            ("PBFT - Byzantine fault tolerance for 3f+1 nodes.", ["source", "pbft"]),
        ]
        for text, tags in sources:
            t.commit(DialogueContent(role="user", text=text), tags=tags)

        print(f"  Ingested {len(t.log())} commits")
        print(f"  Stage: {t.get_config('stage')}")

        print("\n=== Transition to Organize ===\n")

        result = t.transition("organize")
        if result:
            print(f"  Transitioned to: {t.current_branch}")
        else:
            print("  Blocked by gate")
            return

        t.rule("stage", trigger="active",
               action={"type": "set_config", "key": "stage", "value": "organize"})

        t.metadata("taxonomy", {"raft": "leader-based", "paxos": "leaderless", "pbft": "byzantine"})
        t.metadata("comparison", {"raft": "moderate", "paxos": "high", "pbft": "very_high"})

        print(f"  Added metadata entries")
        print(f"  Stage: {t.get_config('stage')}")

        print("\n=== Transition to Synthesize ===\n")

        result = t.transition("synthesize")
        if result:
            print(f"  Transitioned to: {t.current_branch}")
        else:
            print("  Blocked by gate")
            return

        t.rule("stage", trigger="active",
               action={"type": "set_config", "key": "stage", "value": "synthesize"})
        t.rule("synth-strategy", trigger="active",
               action={"type": "set_config", "key": "compile_strategy", "value": "adaptive"})

        t.commit(DialogueContent(role="assistant", text=(
            "Synthesis: Raft for understandability, Paxos for proofs, PBFT for adversarial."
        )), tags=["synthesis", "final"])

        print("\n=== Final State ===\n")

        print(f"  Current branch: {t.current_branch}")
        print(f"  Stage: {t.get_config('stage')}")
        print(f"  Compile strategy: {t.get_config('compile_strategy')}")

        print("\n  Branches:")
        for b in t.list_branches():
            marker = "*" if b.is_current else " "
            print(f"    {marker} {b.name}")

        print(f"\n  Log on synthesize ({len(t.log())} commits):")
        for ci in t.log():
            tags = f" [{', '.join(ci.tags)}]" if ci.tags else ""
            print(f"    {ci.commit_hash[:8]}  {ci.content_type:10s}{tags}  {ci.message[:40]}")


if __name__ == "__main__":
    main()
