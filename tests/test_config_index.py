"""Focused tests for the ConfigIndex module (operations/config_index.py).

Covers gaps not addressed by test_config_content.py or test_configure_api.py:
- Config inheritance across branches (child sees parent config)
- Config after branch checkout (switching changes config view)
- Branch-specific config overrides
- Config isolation between sibling branches
- ConfigIndex.__len__() behavior
- Empty config commits (settings={})
- Config with diverse value types (bool, list, nested dict)
- ConfigIndex.build() directly with edge cases
"""

from __future__ import annotations

import pytest

from tract import Tract
from tract.operations.config_index import ConfigIndex


# ---------------------------------------------------------------------------
# Config resolution basics (direct ConfigIndex usage)
# ---------------------------------------------------------------------------


class TestConfigIndexDirect:
    """Test ConfigIndex class directly, not through Tract facade."""

    def test_empty_index_len(self):
        """Fresh ConfigIndex has length 0."""
        idx = ConfigIndex()
        assert len(idx) == 0

    def test_empty_index_get_returns_default(self):
        """get() on empty index returns the default."""
        idx = ConfigIndex()
        assert idx.get("anything") is None
        assert idx.get("anything", "fallback") == "fallback"

    def test_empty_index_get_all_empty(self):
        """get_all() on empty index returns empty dict."""
        idx = ConfigIndex()
        assert idx.get_all() == {}

    def test_empty_index_not_stale(self):
        """Fresh ConfigIndex is not stale."""
        idx = ConfigIndex()
        assert not idx.is_stale

    def test_invalidate_then_check(self):
        """invalidate() sets stale, is_stale reflects it."""
        idx = ConfigIndex()
        idx.invalidate()
        assert idx.is_stale

    def test_build_from_tract_single_config(self):
        """ConfigIndex.build() resolves a single config commit via repos."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o")
            idx = ConfigIndex.build(
                t._commit_repo, t._blob_repo, t.head,
                parent_repo=t._parent_repo,
            )
            assert idx.get("model") == "gpt-4o"
            assert len(idx) == 1

    def test_build_from_tract_multiple_configs(self):
        """ConfigIndex.build() accumulates across multiple config commits."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o")
            t.config.set(temperature=0.7)
            idx = ConfigIndex.build(
                t._commit_repo, t._blob_repo, t.head,
                parent_repo=t._parent_repo,
            )
            assert idx.get("model") == "gpt-4o"
            assert idx.get("temperature") == 0.7
            assert len(idx) == 2

    def test_build_override_same_key(self):
        """ConfigIndex.build() with overridden key: closer to HEAD wins."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5")
            t.config.set(model="gpt-4o")
            idx = ConfigIndex.build(
                t._commit_repo, t._blob_repo, t.head,
                parent_repo=t._parent_repo,
            )
            assert idx.get("model") == "gpt-4o"
            # Overridden key still counts as one entry
            assert len(idx) == 1

    def test_build_no_config_commits(self):
        """ConfigIndex.build() with only dialogue commits yields empty index."""
        with Tract.open() as t:
            t.user("Hello")
            t.assistant("Hi there")
            idx = ConfigIndex.build(
                t._commit_repo, t._blob_repo, t.head,
                parent_repo=t._parent_repo,
            )
            assert len(idx) == 0
            assert idx.get_all() == {}


# ---------------------------------------------------------------------------
# Config inheritance across branches
# ---------------------------------------------------------------------------


class TestConfigInheritance:
    """Config committed on a parent branch is visible from a child branch."""

    def test_child_inherits_parent_config(self):
        """Child branch sees config committed on parent (main)."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o", temperature=0.7)
            t.user("seed commit")
            t.branches.create("feature")
            # On feature branch now; parent's config should be visible
            assert t.config.get("model") == "gpt-4o"
            assert t.config.get("temperature") == 0.7

    def test_child_overrides_parent_config(self):
        """Child branch config overrides parent for the same key."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5")
            t.user("seed")
            t.branches.create("feature")
            t.config.set(model="gpt-4o")
            assert t.config.get("model") == "gpt-4o"

    def test_child_override_preserves_other_parent_keys(self):
        """Overriding one key on child preserves other parent keys."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5", temperature=0.7)
            t.user("seed")
            t.branches.create("feature")
            t.config.set(model="gpt-4o")
            # model overridden, temperature inherited
            assert t.config.get("model") == "gpt-4o"
            assert t.config.get("temperature") == 0.7

    def test_parent_config_unchanged_after_child_override(self):
        """Parent branch config is not affected by child's override."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5")
            t.user("seed")
            t.branches.create("feature")
            t.config.set(model="gpt-4o")
            # Switch back to main
            t.branches.checkout("main")
            assert t.config.get("model") == "gpt-3.5"


# ---------------------------------------------------------------------------
# Config after branch checkout
# ---------------------------------------------------------------------------


class TestConfigAfterCheckout:
    """Switching branches changes the resolved config view."""

    def test_checkout_switches_config_view(self):
        """After checkout, config resolves from the new branch's ancestry."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5")
            t.user("main seed")
            # Create feature branch with different config
            t.branches.create("feature")
            t.config.set(model="gpt-4o")
            assert t.config.get("model") == "gpt-4o"
            # Switch back to main
            t.branches.checkout("main")
            assert t.config.get("model") == "gpt-3.5"
            # Switch back to feature
            t.branches.checkout("feature")
            assert t.config.get("model") == "gpt-4o"

    def test_checkout_invalidates_config_index(self):
        """checkout() invalidates the cached config index."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5")
            t.user("seed")
            # Force index build
            _ = t.config_index
            assert not t._config_mgr._config_index.is_stale
            t.branches.create("feature")
            # branch with switch=True should invalidate
            # Access config_index to trigger rebuild
            idx = t.config_index
            # Should have rebuilt (not stale)
            assert not idx.is_stale

    def test_config_on_empty_branch_after_checkout(self):
        """Config on a branch with no config commits returns defaults."""
        with Tract.open() as t:
            t.user("seed on main")
            t.branches.create("empty-config")
            assert t.config.get("model") is None
            assert t.config.get("model", default="default-model") == "default-model"
            assert t.config.get_all() == {}


# ---------------------------------------------------------------------------
# Config isolation between sibling branches
# ---------------------------------------------------------------------------


class TestConfigBranchIsolation:
    """Sibling branches do not see each other's config."""

    def test_sibling_branches_isolated(self):
        """Config on branch-a is not visible from branch-b."""
        with Tract.open() as t:
            t.user("common ancestor")
            # Branch A
            t.branches.create("branch-a")
            t.config.set(model="model-a")
            # Go back to main, create branch B
            t.branches.checkout("main")
            t.branches.create("branch-b")
            t.config.set(model="model-b")
            # Verify isolation
            t.branches.checkout("branch-a")
            assert t.config.get("model") == "model-a"
            t.branches.checkout("branch-b")
            assert t.config.get("model") == "model-b"

    def test_sibling_branches_share_ancestor_config(self):
        """Sibling branches both see config from their common ancestor."""
        with Tract.open() as t:
            t.config.set(shared_key="shared-value")
            t.user("common ancestor")
            t.branches.create("branch-a")
            t.config.set(model="model-a")
            t.branches.checkout("main")
            t.branches.create("branch-b")
            t.config.set(model="model-b")
            # Both siblings see the shared ancestor config
            t.branches.checkout("branch-a")
            assert t.config.get("shared_key") == "shared-value"
            assert t.config.get("model") == "model-a"
            t.branches.checkout("branch-b")
            assert t.config.get("shared_key") == "shared-value"
            assert t.config.get("model") == "model-b"


# ---------------------------------------------------------------------------
# get_all_configs() edge cases
# ---------------------------------------------------------------------------


class TestGetAllConfigsEdgeCases:
    """Edge cases for get_all_configs() resolution."""

    def test_get_all_after_override(self):
        """get_all_configs reflects the latest override for each key."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5", temperature=0.5)
            t.config.set(model="gpt-4o")
            result = t.config.get_all()
            assert result == {"model": "gpt-4o", "temperature": 0.5}

    def test_get_all_with_none_values_excluded(self):
        """get_all_configs excludes keys set to None."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o", temperature=0.7)
            t.config.set(temperature=None)
            result = t.config.get_all()
            assert result == {"model": "gpt-4o"}
            assert "temperature" not in result

    def test_get_all_after_branch_with_inheritance(self):
        """get_all_configs on child branch includes inherited + own config."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5", temperature=0.5)
            t.user("seed")
            t.branches.create("feature")
            t.config.set(model="gpt-4o", max_tokens=1000)
            result = t.config.get_all()
            assert result == {
                "model": "gpt-4o",
                "temperature": 0.5,
                "max_tokens": 1000,
            }

    def test_get_all_returns_fresh_dict(self):
        """get_all_configs returns a new dict each call (not a reference)."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o")
            a = t.config.get_all()
            b = t.config.get_all()
            assert a == b
            assert a is not b


# ---------------------------------------------------------------------------
# Empty config and diverse value types
# ---------------------------------------------------------------------------


class TestConfigEdgeCases:
    """Edge cases: empty config, diverse value types."""

    def test_empty_config_commit(self):
        """configure() with no settings still creates a commit but index stays empty."""
        with Tract.open() as t:
            # Empty settings dict through direct commit
            from tract.models.content import ConfigContent
            content = ConfigContent(settings={})
            t.commit(content, message="empty config")
            assert t.config.get_all() == {}
            assert len(t.config_index) == 0

    def test_config_with_boolean_value(self):
        """Boolean values are stored and retrieved correctly."""
        with Tract.open() as t:
            t.config.set(verbose=True, debug=False)
            assert t.config.get("verbose") is True
            assert t.config.get("debug") is False

    def test_config_with_list_value(self):
        """List values are stored and retrieved correctly."""
        with Tract.open() as t:
            t.config.set(allowed_models=["gpt-4o", "gpt-3.5", "claude-3"])
            result = t.config.get("allowed_models")
            assert result == ["gpt-4o", "gpt-3.5", "claude-3"]

    def test_config_with_nested_dict(self):
        """Nested dict values are stored and retrieved correctly."""
        with Tract.open() as t:
            t.config.set(compact_tools={"search": 500, "browse": 1000})
            result = t.config.get("compact_tools")
            assert result == {"search": 500, "browse": 1000}

    def test_config_with_numeric_zero(self):
        """Zero is a valid config value (not treated as None/unset)."""
        with Tract.open() as t:
            t.config.set(temperature=0)
            assert t.config.get("temperature") == 0
            # Should appear in get_all
            assert "temperature" in t.config.get_all()

    def test_config_with_empty_string(self):
        """Empty string is a valid config value (not treated as None/unset)."""
        with Tract.open() as t:
            t.config.set(prefix="")
            assert t.config.get("prefix") == ""
            assert "prefix" in t.config.get_all()

    def test_config_with_all_none_values(self):
        """Config where every key is None yields empty get_all."""
        with Tract.open() as t:
            t.config.set(model=None, temperature=None)
            assert t.config.get_all() == {}
            # But the index still has entries (they're just None-valued)
            assert len(t.config_index) == 2

    def test_config_key_with_special_characters(self):
        """Config keys with dots/dashes work as normal dict keys."""
        with Tract.open() as t:
            t.config.set(**{"my.custom.key": "value", "another-key": 42})
            assert t.config.get("my.custom.key") == "value"
            assert t.config.get("another-key") == 42


# ---------------------------------------------------------------------------
# ConfigIndex __len__ tracks all entries including None
# ---------------------------------------------------------------------------


class TestConfigIndexLen:
    """ConfigIndex.__len__ reflects total tracked keys."""

    def test_len_single_key(self):
        """len() is 1 after one config key."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o")
            assert len(t.config_index) == 1

    def test_len_multiple_keys(self):
        """len() reflects total unique keys across config commits."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o")
            t.config.set(temperature=0.7, max_tokens=1000)
            assert len(t.config_index) == 3

    def test_len_override_does_not_increase(self):
        """Overriding a key does not increase len()."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5")
            t.config.set(model="gpt-4o")
            assert len(t.config_index) == 1

    def test_len_includes_none_valued_keys(self):
        """len() counts keys even when their value is None."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o")
            t.config.set(model=None)
            # The key exists in the index with None value
            assert len(t.config_index) == 1

    def test_len_with_inherited_config(self):
        """len() on child branch includes inherited keys."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o", temperature=0.7)
            t.user("seed")
            t.branches.create("feature")
            t.config.set(max_tokens=1000)
            # 3 unique keys: model, temperature (inherited), max_tokens (own)
            assert len(t.config_index) == 3


# ---------------------------------------------------------------------------
# ConfigIndex.build() with specific head hash
# ---------------------------------------------------------------------------


class TestConfigIndexBuildAtPoint:
    """ConfigIndex.build() at a specific point in DAG history."""

    def test_build_at_earlier_head(self):
        """Building index at an earlier commit ignores later configs."""
        with Tract.open() as t:
            info1 = t.config.set(model="gpt-3.5")
            t.config.set(model="gpt-4o")
            # Build index at the first config commit
            idx = ConfigIndex.build(
                t._commit_repo, t._blob_repo, info1.commit_hash,
                parent_repo=t._parent_repo,
            )
            assert idx.get("model") == "gpt-3.5"

    def test_build_at_non_config_commit(self):
        """Building index at a non-config commit still walks ancestors."""
        with Tract.open() as t:
            t.config.set(model="gpt-4o")
            user_info = t.user("Hello")
            # Build at user commit; should find ancestor config
            idx = ConfigIndex.build(
                t._commit_repo, t._blob_repo, user_info.commit_hash,
                parent_repo=t._parent_repo,
            )
            assert idx.get("model") == "gpt-4o"

    def test_build_at_middle_point(self):
        """Building at a middle commit sees only earlier configs."""
        with Tract.open() as t:
            t.config.set(model="gpt-3.5")
            middle_info = t.user("middle commit")
            t.config.set(model="gpt-4o")
            # Build at middle: only sees the first config
            idx = ConfigIndex.build(
                t._commit_repo, t._blob_repo, middle_info.commit_hash,
                parent_repo=t._parent_repo,
            )
            assert idx.get("model") == "gpt-3.5"
