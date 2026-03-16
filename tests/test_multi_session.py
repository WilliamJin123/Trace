"""Tests for multi-session story: snapshot/restore and external SDK adapters."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

import pytest

from tract import Tract
from tract.adapters import (
    AdapterRegistry,
    AgentAdapter,
    AnthropicAdapter,
    PassthroughAdapter,
)
from tract.models.content import DialogueContent, InstructionContent
from tract.profiles import WorkflowProfile
from tract.session import Session
from tract.templates import DirectiveTemplate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tract(**kwargs: Any) -> Tract:
    """Open an in-memory tract for testing."""
    return Tract.open(":memory:", **kwargs)


# ===========================================================================
# snapshot_state tests
# ===========================================================================


class TestSnapshotState:
    """Tests for Tract.snapshot_state()."""

    def test_snapshot_captures_empty_state(self) -> None:
        with _make_tract() as t:
            snap = t.snapshot_state()
            assert "middleware" in snap
            assert "gates" in snap
            assert "maintainers" in snap
            assert "profiles" in snap
            assert "templates" in snap
            assert "config" in snap
            assert "operation_configs" in snap

    def test_snapshot_captures_profiles(self) -> None:
        with _make_tract() as t:
            snap = t.snapshot_state()
            # Should have default built-in profiles
            profile_names = [p["name"] for p in snap["profiles"]]
            assert "coding" in profile_names
            assert "research" in profile_names

    def test_snapshot_captures_templates(self) -> None:
        with _make_tract() as t:
            snap = t.snapshot_state()
            template_names = [tp["name"] for tp in snap["templates"]]
            assert "review_protocol" in template_names

    def test_snapshot_captures_custom_profile(self) -> None:
        with _make_tract() as t:
            custom = WorkflowProfile(
                name="test_custom",
                description="Test profile",
                config={"temperature": 0.5},
            )
            t._profile_registry["test_custom"] = custom
            snap = t.snapshot_state()
            profile_names = [p["name"] for p in snap["profiles"]]
            assert "test_custom" in profile_names

    def test_snapshot_captures_custom_template(self) -> None:
        with _make_tract() as t:
            custom = DirectiveTemplate(
                name="test_tmpl",
                description="Test template",
                content="Hello {name}",
                parameters={"name": "Name to greet"},
            )
            t._template_registry["test_tmpl"] = custom
            snap = t.snapshot_state()
            template_names = [tp["name"] for tp in snap["templates"]]
            assert "test_tmpl" in template_names

    def test_snapshot_captures_config(self) -> None:
        with _make_tract() as t:
            t.commit(InstructionContent(text="init"))
            t.configure(temperature=0.7, compile_strategy="adaptive")
            snap = t.snapshot_state()
            assert snap["config"].get("temperature") == 0.7
            assert snap["config"].get("compile_strategy") == "adaptive"

    def test_snapshot_captures_middleware(self) -> None:
        with _make_tract() as t:
            handler_id = t.use("pre_commit", lambda ctx: None)
            snap = t.snapshot_state()
            assert len(snap["middleware"]) == 1
            mw = snap["middleware"][0]
            assert mw["handler_id"] == handler_id
            assert mw["event"] == "pre_commit"

    def test_snapshot_is_json_serializable(self) -> None:
        with _make_tract() as t:
            t.commit(InstructionContent(text="init"))
            t.configure(temperature=0.5)
            snap = t.snapshot_state()
            # Should not raise
            json_str = json.dumps(snap, default=str)
            assert isinstance(json_str, str)
            roundtripped = json.loads(json_str)
            assert roundtripped["config"]["temperature"] == 0.5


# ===========================================================================
# restore_state tests
# ===========================================================================


class TestRestoreState:
    """Tests for Tract.restore_state()."""

    def test_restore_profiles(self) -> None:
        with _make_tract() as t:
            custom = WorkflowProfile(
                name="restored_profile",
                description="A restored profile",
                config={"temperature": 0.9},
            )
            snap = {"profiles": [custom.to_spec()]}
            report = t.restore_state(snap)
            assert "profile:restored_profile" in report["restored"]
            assert "restored_profile" in t._profile_registry

    def test_restore_templates(self) -> None:
        with _make_tract() as t:
            custom = DirectiveTemplate(
                name="restored_tmpl",
                description="A restored template",
                content="Do {thing}",
                parameters={"thing": "What to do"},
            )
            snap = {"templates": [custom.to_spec()]}
            report = t.restore_state(snap)
            assert "template:restored_tmpl" in report["restored"]
            assert "restored_tmpl" in t._template_registry

    def test_restore_config(self) -> None:
        with _make_tract() as t:
            t.commit(InstructionContent(text="init"))
            snap = {"config": {"temperature": 0.42}}
            report = t.restore_state(snap)
            assert any("config:" in r for r in report["restored"])
            assert t.get_all_configs().get("temperature") == 0.42

    def test_restore_skips_gates(self) -> None:
        with _make_tract() as t:
            snap = {
                "gates": [
                    {"name": "test-gate", "check": "Has 3 findings", "event": "pre_transition"}
                ]
            }
            report = t.restore_state(snap)
            assert any("gate:test-gate" in s for s in report["skipped"])

    def test_restore_skips_maintainers(self) -> None:
        with _make_tract() as t:
            snap = {
                "maintainers": [
                    {"name": "test-maint", "instructions": "Cleanup", "event": "post_commit"}
                ]
            }
            report = t.restore_state(snap)
            assert any("maintainer:test-maint" in s for s in report["skipped"])

    def test_restore_skips_middleware(self) -> None:
        with _make_tract() as t:
            snap = {
                "middleware": [
                    {"handler_id": "abc123", "event": "pre_commit", "handler_type": "function"}
                ]
            }
            report = t.restore_state(snap)
            assert any("middleware:" in s for s in report["skipped"])

    def test_restore_reports_errors(self) -> None:
        with _make_tract() as t:
            # Profile with missing required 'name' key
            snap = {"profiles": [{"description": "broken"}]}
            report = t.restore_state(snap)
            assert len(report["errors"]) > 0

    def test_restore_report_structure(self) -> None:
        with _make_tract() as t:
            report = t.restore_state({})
            assert "restored" in report
            assert "skipped" in report
            assert "errors" in report
            assert isinstance(report["restored"], list)
            assert isinstance(report["skipped"], list)
            assert isinstance(report["errors"], list)


# ===========================================================================
# save_state / load_state file round-trip tests
# ===========================================================================


class TestSaveLoadState:
    """Tests for Tract.save_state() and Tract.load_state() file I/O."""

    def test_save_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "test.state.json")
            with _make_tract() as t:
                t.commit(InstructionContent(text="init"))
                t.configure(temperature=0.55)
                # Add a custom profile
                custom = WorkflowProfile(
                    name="roundtrip_profile",
                    description="Round-trip test",
                )
                t._profile_registry["roundtrip_profile"] = custom
                saved_path = t.save_state(path=state_path)
                assert saved_path == state_path
                assert os.path.isfile(state_path)

            # Load into a new tract
            with _make_tract() as t2:
                t2.commit(InstructionContent(text="init"))
                report = t2.load_state(path=state_path)
                assert any("profile:roundtrip_profile" in r for r in report["restored"])
                assert any("config:" in r for r in report["restored"])
                assert "roundtrip_profile" in t2._profile_registry

    def test_save_state_memory_db_requires_path(self) -> None:
        with _make_tract() as t:
            with pytest.raises(ValueError, match="memory"):
                t.save_state()

    def test_load_state_memory_db_requires_path(self) -> None:
        with _make_tract() as t:
            with pytest.raises(ValueError, match="memory"):
                t.load_state()

    def test_load_state_file_not_found(self) -> None:
        with _make_tract() as t:
            with pytest.raises(FileNotFoundError):
                t.load_state(path="/nonexistent/path/state.json")

    def test_save_state_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "sub", "dir", "state.json")
            with _make_tract() as t:
                t.save_state(path=nested_path)
                assert os.path.isfile(nested_path)

    def test_saved_file_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "state.json")
            with _make_tract() as t:
                t.save_state(path=state_path)
            with open(state_path, "r") as f:
                data = json.load(f)
            assert "profiles" in data
            assert "templates" in data
            assert "config" in data

    def test_save_with_db_path_auto_derives_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            with Tract.open(db_path) as t:
                t.commit(InstructionContent(text="init"))
                saved = t.save_state()
                assert saved == db_path + ".state.json"
                assert os.path.isfile(saved)


# ===========================================================================
# PassthroughAdapter tests
# ===========================================================================


class TestPassthroughAdapter:
    """Tests for PassthroughAdapter."""

    def test_wrap_messages_passthrough(self) -> None:
        adapter = PassthroughAdapter()
        msgs = [{"role": "user", "content": "Hello"}]
        result = adapter.wrap_messages(msgs)
        assert result == msgs
        # Should be a copy, not the same list
        assert result is not msgs

    def test_extract_messages_from_openai_response(self) -> None:
        adapter = PassthroughAdapter()
        response = {
            "choices": [{"message": {"role": "assistant", "content": "Hi"}}]
        }
        result = adapter.extract_messages(response)
        assert result == [{"role": "assistant", "content": "Hi"}]

    def test_extract_messages_from_list(self) -> None:
        adapter = PassthroughAdapter()
        msgs = [{"role": "assistant", "content": "Hi"}]
        result = adapter.extract_messages(msgs)
        assert result == msgs

    def test_extract_messages_from_single_dict(self) -> None:
        adapter = PassthroughAdapter()
        msg = {"role": "assistant", "content": "Hi"}
        result = adapter.extract_messages(msg)
        assert result == [msg]

    def test_extract_messages_empty(self) -> None:
        adapter = PassthroughAdapter()
        result = adapter.extract_messages(42)
        assert result == []

    def test_adapt_tools_passthrough(self) -> None:
        adapter = PassthroughAdapter()
        tools = [{"type": "function", "function": {"name": "test"}}]
        result = adapter.adapt_tools(tools)
        assert result == tools
        assert result is not tools

    def test_satisfies_protocol(self) -> None:
        adapter = PassthroughAdapter()
        assert isinstance(adapter, AgentAdapter)


# ===========================================================================
# AnthropicAdapter tests
# ===========================================================================


class TestAnthropicAdapter:
    """Tests for AnthropicAdapter."""

    def test_wrap_messages_extracts_system(self) -> None:
        adapter = AnthropicAdapter()
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system, anthropic_msgs = adapter.wrap_messages(msgs)
        assert system == "You are helpful."
        assert len(anthropic_msgs) == 1
        assert anthropic_msgs[0]["role"] == "user"

    def test_wrap_messages_multiple_system(self) -> None:
        adapter = AnthropicAdapter()
        msgs = [
            {"role": "system", "content": "First."},
            {"role": "system", "content": "Second."},
            {"role": "user", "content": "Hello"},
        ]
        system, anthropic_msgs = adapter.wrap_messages(msgs)
        assert "First." in system
        assert "Second." in system
        assert len(anthropic_msgs) == 1

    def test_wrap_messages_converts_to_content_blocks(self) -> None:
        adapter = AnthropicAdapter()
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        system, anthropic_msgs = adapter.wrap_messages(msgs)
        assert system == ""
        assert len(anthropic_msgs) == 2
        assert anthropic_msgs[0]["content"] == [{"type": "text", "text": "Hello"}]
        assert anthropic_msgs[1]["content"] == [{"type": "text", "text": "Hi there"}]

    def test_wrap_messages_no_system(self) -> None:
        adapter = AnthropicAdapter()
        msgs = [{"role": "user", "content": "Hello"}]
        system, anthropic_msgs = adapter.wrap_messages(msgs)
        assert system == ""
        assert len(anthropic_msgs) == 1

    def test_extract_messages_from_anthropic_response(self) -> None:
        adapter = AnthropicAdapter()
        response = {
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello from Claude"}],
        }
        result = adapter.extract_messages(response)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Hello from Claude"

    def test_extract_messages_from_legacy_response(self) -> None:
        adapter = AnthropicAdapter()
        response = {"completion": "Hello from Claude"}
        result = adapter.extract_messages(response)
        assert len(result) == 1
        assert result[0]["content"] == "Hello from Claude"

    def test_extract_messages_from_content_block_list(self) -> None:
        adapter = AnthropicAdapter()
        response = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
        ]
        result = adapter.extract_messages(response)
        assert len(result) == 1
        assert "Part 1" in result[0]["content"]
        assert "Part 2" in result[0]["content"]

    def test_adapt_tools_openai_to_anthropic(self) -> None:
        adapter = AnthropicAdapter()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ]
        result = adapter.adapt_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get current weather"
        assert "input_schema" in result[0]
        assert result[0]["input_schema"]["type"] == "object"

    def test_adapt_tools_flat_format(self) -> None:
        """Tool dicts without wrapping 'function' key."""
        adapter = AnthropicAdapter()
        tools = [
            {
                "name": "search",
                "description": "Search docs",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
        result = adapter.adapt_tools(tools)
        assert result[0]["name"] == "search"
        assert result[0]["input_schema"]["type"] == "object"

    def test_satisfies_protocol(self) -> None:
        adapter = AnthropicAdapter()
        assert isinstance(adapter, AgentAdapter)


# ===========================================================================
# AdapterRegistry tests
# ===========================================================================


class TestAdapterRegistry:
    """Tests for AdapterRegistry."""

    def test_default_adapters(self) -> None:
        registry = AdapterRegistry()
        names = registry.list_adapters()
        assert "passthrough" in names
        assert "anthropic" in names

    def test_get_passthrough(self) -> None:
        registry = AdapterRegistry()
        adapter = registry.get("passthrough")
        assert isinstance(adapter, PassthroughAdapter)

    def test_get_anthropic(self) -> None:
        registry = AdapterRegistry()
        adapter = registry.get("anthropic")
        assert isinstance(adapter, AnthropicAdapter)

    def test_get_unknown_raises(self) -> None:
        registry = AdapterRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get("nonexistent")

    def test_register_custom(self) -> None:
        registry = AdapterRegistry()

        class CustomAdapter:
            def wrap_messages(self, messages: list[dict]) -> Any:
                return messages

            def extract_messages(self, response: Any) -> list[dict]:
                return []

            def adapt_tools(self, tools: list[dict]) -> Any:
                return tools

        registry.register("custom", CustomAdapter())
        assert "custom" in registry.list_adapters()
        adapter = registry.get("custom")
        assert isinstance(adapter, AgentAdapter)

    def test_register_non_protocol_raises(self) -> None:
        registry = AdapterRegistry()
        with pytest.raises(TypeError, match="AgentAdapter protocol"):
            registry.register("bad", object())  # type: ignore[arg-type]

    def test_list_adapters_sorted(self) -> None:
        registry = AdapterRegistry()
        names = registry.list_adapters()
        assert names == sorted(names)


# ===========================================================================
# Session adapter wiring tests
# ===========================================================================


class TestSessionAdapterWiring:
    """Tests for adapter propagation through Session."""

    def test_session_stores_adapter(self) -> None:
        adapter = PassthroughAdapter()
        session = Session.open(adapter=adapter)
        try:
            assert session.adapter is adapter
        finally:
            session.close()

    def test_session_propagates_adapter_to_tract(self) -> None:
        adapter = AnthropicAdapter()
        session = Session.open(adapter=adapter)
        try:
            t = session.create_tract(display_name="test")
            assert t.adapter is adapter
        finally:
            session.close()

    def test_session_no_adapter_by_default(self) -> None:
        session = Session.open()
        try:
            t = session.create_tract(display_name="test")
            assert t.adapter is None
        finally:
            session.close()

    def test_tract_adapter_property(self) -> None:
        with _make_tract() as t:
            assert t.adapter is None
            adapter = PassthroughAdapter()
            t.adapter = adapter
            assert t.adapter is adapter
