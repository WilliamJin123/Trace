"""Coding Workflow: design -> implementation -> validation

Multi-stage workflow using branches, transition rules, and stage configs.
Transitions enforce quality gates between stages.

Requires: LLM API key (uses Groq provider)
"""

import sys
from pathlib import Path

from tract import Tract, resolve_all_configs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _providers import groq as llm

MODEL_ID = llm.small


def main():
    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:

        print("=== Setting Up Workflow Rules ===\n")

        t.rule("stage", trigger="active",
               action={"type": "set_config", "key": "stage", "value": "design"})
        t.rule("design-temp", trigger="active",
               action={"type": "set_config", "key": "temperature", "value": 0.9})
        t.rule("design-model", trigger="active",
               action={"type": "set_config", "key": "model", "value": MODEL_ID})

        t.rule(
            "impl-gate",
            trigger="transition:implementation",
            action={
                "type": "require",
                "condition": {
                    "type": "threshold",
                    "metric": "commit_count",
                    "op": ">=",
                    "value": 6,
                },
            },
        )

        t.rule(
            "validation-gate",
            trigger="transition:validation",
            action={
                "type": "require",
                "condition": {
                    "type": "threshold",
                    "metric": "commit_count",
                    "op": ">=",
                    "value": 3,
                },
            },
        )

        print("  Design stage configs + transition gates created")

        print("\n=== Design Phase ===\n")

        t.system("You are a software architect. Be concise.")
        r = t.chat("Design a simple key-value store with get/set/delete. One paragraph.")
        print(f"  Design: {r.text[:150]}...")

        configs = resolve_all_configs(t.rule_index)
        print(f"\n  Active configs: {configs}")

        print("\n=== Transitioning to Implementation ===\n")

        result = t.transition("implementation")
        if result:
            print(f"  Transitioned to: {t.current_branch}")
        else:
            print("  Blocked -- not enough content yet")
            return

        t.rule("stage", trigger="active",
               action={"type": "set_config", "key": "stage", "value": "implementation"})
        t.rule("impl-temp", trigger="active",
               action={"type": "set_config", "key": "temperature", "value": 0.3})

        r = t.chat("Implement the key-value store in Python. Concise code only.")
        print(f"  Implementation: {r.text[:150]}...")

        configs = resolve_all_configs(t.rule_index)
        print(f"\n  Active configs: {configs}")

        print("\n=== Transitioning to Validation ===\n")

        result = t.transition("validation")
        if result:
            print(f"  Transitioned to: {t.current_branch}")
        else:
            print("  Blocked -- not enough content yet")
            return

        t.rule("stage", trigger="active",
               action={"type": "set_config", "key": "stage", "value": "validation"})
        t.rule("val-temp", trigger="active",
               action={"type": "set_config", "key": "temperature", "value": 0.1})

        r = t.chat("Write 3 test cases for the key-value store. Be brief.")
        print(f"  Validation: {r.text[:150]}...")

        print("\n=== Workflow Branches ===\n")
        for b in t.list_branches():
            marker = "*" if b.is_current else " "
            print(f"  {marker} {b.name}")


if __name__ == "__main__":
    main()
