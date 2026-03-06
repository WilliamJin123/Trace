"""Config Rules

Config rules use trigger="active" and action type "set_config" to create
a key-value configuration layer. They work like CSS specificity:

  - Every active set_config rule contributes a key-value pair
  - When multiple rules set the same key, closest to HEAD wins
  - Override a config by committing a new rule with the same name
  - Query one key with get_config(), all keys with resolve_all_configs()

Demonstrates: active trigger, set_config action, DAG precedence,
              config override, resolve_all_configs
"""

from tract import Tract, resolve_all_configs


def main():
    with Tract.open() as t:

        # --- Basic config ---

        print("=== Basic Config Rules ===\n")

        t.rule("model", trigger="active",
               action={"type": "set_config", "key": "model", "value": "gpt-4o"})
        t.rule("temperature", trigger="active",
               action={"type": "set_config", "key": "temperature", "value": 0.7})
        t.rule("max-tokens", trigger="active",
               action={"type": "set_config", "key": "max_tokens", "value": 4096})

        print(f"  model:       {t.get_config('model')}")
        print(f"  temperature: {t.get_config('temperature')}")
        print(f"  max_tokens:  {t.get_config('max_tokens')}")

        # --- DAG precedence ---

        print("\n=== DAG Precedence (closer to HEAD wins) ===\n")

        # Add some conversation between config rules
        t.user("Hello, world!")
        t.assistant("Hi there!")

        # Override model -- same name, new value
        t.rule("model", trigger="active",
               action={"type": "set_config", "key": "model", "value": "claude-sonnet"})

        print(f"  model (overridden): {t.get_config('model')}")
        print(f"  temperature (unchanged): {t.get_config('temperature')}")

        # --- Resolve all configs ---

        print("\n=== All Active Configs ===\n")

        all_configs = resolve_all_configs(t.rule_index)
        for key, value in sorted(all_configs.items()):
            print(f"  {key:20s} = {value}")

        # --- Default values ---

        print("\n=== Default Values ===\n")

        print(f"  missing key:  {t.get_config('nonexistent')}")
        print(f"  with default: {t.get_config('nonexistent', 'fallback')}")

        # --- Config with complex values ---

        print("\n=== Complex Config Values ===\n")

        t.rule("stop-sequences", trigger="active",
               action={"type": "set_config", "key": "stop",
                        "value": ["END", "DONE", "---"]})
        t.rule("safety-settings", trigger="active",
               action={"type": "set_config", "key": "safety",
                        "value": {"block_harmful": True, "log_flags": True}})

        print(f"  stop:   {t.get_config('stop')}")
        print(f"  safety: {t.get_config('safety')}")

        # --- Config in the log ---

        print("\n=== Config rules are visible in the log ===\n")

        all_configs = resolve_all_configs(t.rule_index)
        print(f"  Total unique config keys: {len(all_configs)}")

        for ci in t.log():
            if ci.content_type == "rule":
                print(f"  {ci.commit_hash[:8]}  {ci.message}")


if __name__ == "__main__":
    main()
