"""Tests for t.configure() API, get_config(), well-known key validation, and enforcement.

Covers:
- t.configure(model="gpt-4o") stores config in DAG
- t.get_config("model") returns "gpt-4o"
- t.get_all_configs() returns all settings
- DAG precedence: later configure() overrides earlier
- Well-known key type validation (temperature="hot" raises ValueError)
- Unknown keys pass through
- None values unset a key (get_config returns default)
- max_commit_tokens enforcement: commit exceeding limit raises BlockedError
"""

from __future__ import annotations

import pytest

from tract import (
    BlockedError,
    DialogueContent,
    InstructionContent,
    Tract,
)


# ---------------------------------------------------------------------------
# Basic configure and get
# ---------------------------------------------------------------------------


class TestConfigureBasic:
    """t.configure() stores settings, t.get_config() retrieves them."""

    def test_configure_model(self):
        """t.configure(model='gpt-4o') stores model in DAG."""
        with Tract.open() as t:
            info = t.configure(model="gpt-4o")
            assert info is not None
            assert info.content_type == "config"
            assert t.get_config("model") == "gpt-4o"

    def test_configure_multiple_keys(self):
        """t.configure() stores multiple keys at once."""
        with Tract.open() as t:
            t.configure(model="gpt-4o", temperature=0.7, max_tokens=1000)
            assert t.get_config("model") == "gpt-4o"
            assert t.get_config("temperature") == 0.7
            assert t.get_config("max_tokens") == 1000

    def test_configure_returns_commit_info(self):
        """t.configure() returns a CommitInfo object."""
        with Tract.open() as t:
            info = t.configure(model="gpt-4o")
            assert info.commit_hash is not None
            assert info.content_type == "config"

    def test_configure_message_auto_generated(self):
        """t.configure() generates a commit message mentioning keys."""
        with Tract.open() as t:
            info = t.configure(model="gpt-4o")
            assert "model" in info.message

    def test_get_config_missing_key(self):
        """get_config for missing key returns None."""
        with Tract.open() as t:
            assert t.get_config("nonexistent") is None

    def test_get_config_with_default(self):
        """get_config for missing key returns provided default."""
        with Tract.open() as t:
            assert t.get_config("nonexistent", default="fallback") == "fallback"


# ---------------------------------------------------------------------------
# get_all_configs()
# ---------------------------------------------------------------------------


class TestGetAllConfigs:
    """t.get_all_configs() returns all resolved settings."""

    def test_get_all_configs_basic(self):
        """get_all_configs returns dict of all settings."""
        with Tract.open() as t:
            t.configure(model="gpt-4o", temperature=0.7)
            result = t.get_all_configs()
            assert result == {"model": "gpt-4o", "temperature": 0.7}

    def test_get_all_configs_empty(self):
        """get_all_configs on empty tract returns empty dict."""
        with Tract.open() as t:
            assert t.get_all_configs() == {}

    def test_get_all_configs_merged_across_commits(self):
        """get_all_configs merges settings from multiple configure() calls."""
        with Tract.open() as t:
            t.configure(model="gpt-4o")
            t.configure(temperature=0.7)
            result = t.get_all_configs()
            assert result == {"model": "gpt-4o", "temperature": 0.7}


# ---------------------------------------------------------------------------
# DAG precedence
# ---------------------------------------------------------------------------


class TestConfigurePrecedence:
    """Later configure() calls override earlier ones."""

    def test_later_overrides_earlier(self):
        """Second configure(model=...) overrides the first."""
        with Tract.open() as t:
            t.configure(model="gpt-3.5")
            t.configure(model="gpt-4o")
            assert t.get_config("model") == "gpt-4o"

    def test_partial_override_preserves_other_keys(self):
        """Overriding one key preserves other keys."""
        with Tract.open() as t:
            t.configure(model="gpt-3.5", temperature=0.7)
            t.configure(model="gpt-4o")
            assert t.get_config("model") == "gpt-4o"
            assert t.get_config("temperature") == 0.7

    def test_multiple_overrides(self):
        """Three sequential overrides, last wins."""
        with Tract.open() as t:
            t.configure(model="v1")
            t.configure(model="v2")
            t.configure(model="v3")
            assert t.get_config("model") == "v3"


# ---------------------------------------------------------------------------
# Well-known key type validation
# ---------------------------------------------------------------------------


class TestWellKnownKeyValidation:
    """Well-known config keys are type-checked."""

    def test_model_accepts_string(self):
        """model key accepts str."""
        with Tract.open() as t:
            t.configure(model="gpt-4o")  # should not raise

    def test_model_rejects_int(self):
        """model key rejects non-str."""
        with Tract.open() as t:
            with pytest.raises(ValueError, match="model.*expects"):
                t.configure(model=42)

    def test_temperature_accepts_float(self):
        """temperature key accepts float."""
        with Tract.open() as t:
            t.configure(temperature=0.7)  # should not raise

    def test_temperature_accepts_int(self):
        """temperature key accepts int (int|float)."""
        with Tract.open() as t:
            t.configure(temperature=1)  # should not raise

    def test_temperature_rejects_string(self):
        """temperature key rejects str."""
        with Tract.open() as t:
            with pytest.raises(ValueError, match="temperature.*expects"):
                t.configure(temperature="hot")

    def test_max_tokens_accepts_int(self):
        """max_tokens key accepts int."""
        with Tract.open() as t:
            t.configure(max_tokens=1000)  # should not raise

    def test_max_tokens_rejects_float(self):
        """max_tokens key rejects float."""
        with Tract.open() as t:
            with pytest.raises(ValueError, match="max_tokens.*expects"):
                t.configure(max_tokens=10.5)

    def test_max_commit_tokens_accepts_int(self):
        """max_commit_tokens key accepts int."""
        with Tract.open() as t:
            t.configure(max_commit_tokens=500)  # should not raise

    def test_compact_tools_accepts_dict(self):
        """compact_tools key accepts dict."""
        with Tract.open() as t:
            t.configure(compact_tools={"search": 500})  # should not raise

    def test_compact_tools_rejects_list(self):
        """compact_tools key rejects non-dict."""
        with Tract.open() as t:
            with pytest.raises(ValueError, match="compact_tools.*expects"):
                t.configure(compact_tools=["search", 500])

    def test_compile_strategy_accepts_string(self):
        """compile_strategy key accepts str."""
        with Tract.open() as t:
            t.configure(compile_strategy="adaptive")  # should not raise

    def test_compile_strategy_k_accepts_int(self):
        """compile_strategy_k key accepts int."""
        with Tract.open() as t:
            t.configure(compile_strategy_k=5)  # should not raise

    def test_handoff_summary_k_accepts_int(self):
        """handoff_summary_k key accepts int."""
        with Tract.open() as t:
            t.configure(handoff_summary_k=3)  # should not raise

    def test_auto_compress_threshold_rejects_string(self):
        """auto_compress_threshold rejects str."""
        with Tract.open() as t:
            with pytest.raises(ValueError, match="auto_compress_threshold.*expects"):
                t.configure(auto_compress_threshold="high")


# ---------------------------------------------------------------------------
# Unknown keys pass through
# ---------------------------------------------------------------------------


class TestUnknownKeys:
    """Unknown config keys pass through without validation."""

    def test_unknown_key_stored(self):
        """Unknown keys are stored and retrievable."""
        with Tract.open() as t:
            t.configure(my_custom_setting="custom_value")
            assert t.get_config("my_custom_setting") == "custom_value"

    def test_unknown_key_any_type(self):
        """Unknown keys accept any type."""
        with Tract.open() as t:
            t.configure(custom_list=[1, 2, 3])
            assert t.get_config("custom_list") == [1, 2, 3]

    def test_unknown_key_in_get_all(self):
        """Unknown keys appear in get_all_configs()."""
        with Tract.open() as t:
            t.configure(model="gpt-4o", custom="value")
            result = t.get_all_configs()
            assert result["custom"] == "value"
            assert result["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# None values unset a key
# ---------------------------------------------------------------------------


class TestConfigureNoneUnset:
    """None values unset a key."""

    def test_none_unsets_key(self):
        """Setting key to None returns default on get."""
        with Tract.open() as t:
            t.configure(model="gpt-4o")
            assert t.get_config("model") == "gpt-4o"
            t.configure(model=None)
            assert t.get_config("model") is None

    def test_none_returns_custom_default(self):
        """After unsetting, get_config returns provided default."""
        with Tract.open() as t:
            t.configure(model="gpt-4o")
            t.configure(model=None)
            assert t.get_config("model", default="fallback") == "fallback"

    def test_none_value_type_not_validated(self):
        """None is accepted for well-known keys (unset semantics, no type check)."""
        with Tract.open() as t:
            # model expects str, but None is the unset sentinel
            t.configure(model=None)  # should not raise ValueError


# ---------------------------------------------------------------------------
# max_commit_tokens enforcement
# ---------------------------------------------------------------------------


class TestMaxCommitTokensEnforcement:
    """max_commit_tokens config blocks oversized commits via BlockedError."""

    def test_commit_exceeding_limit_blocked(self):
        """Commit with tokens > max_commit_tokens raises BlockedError."""
        with Tract.open() as t:
            t.configure(max_commit_tokens=5)
            # A long text should exceed 5 tokens
            long_text = "This is a very long message that certainly exceeds five tokens in any tokenizer"
            with pytest.raises(BlockedError, match="max_commit_tokens"):
                t.user(long_text)

    def test_commit_within_limit_allowed(self):
        """Commit with tokens <= max_commit_tokens succeeds."""
        with Tract.open() as t:
            t.configure(max_commit_tokens=10000)
            info = t.user("Hi")
            assert info is not None

    def test_max_commit_tokens_not_set_no_enforcement(self):
        """Without max_commit_tokens config, no enforcement."""
        with Tract.open() as t:
            # No config set -- should always succeed
            info = t.user("This is a message of arbitrary length with many words")
            assert info is not None

    def test_max_commit_tokens_unset_removes_enforcement(self):
        """Unsetting max_commit_tokens removes enforcement."""
        with Tract.open() as t:
            t.configure(max_commit_tokens=5)
            # This should be blocked
            with pytest.raises(BlockedError):
                t.user("This is definitely more than five tokens long")
            # Unset the limit
            t.configure(max_commit_tokens=None)
            # Now it should succeed
            info = t.user("This is definitely more than five tokens long")
            assert info is not None
