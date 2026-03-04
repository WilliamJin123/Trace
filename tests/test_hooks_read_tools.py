"""Tests for read tools on Pending subclasses.

Tests get_state(), list_*, and get_* methods across all Pending subclasses.
Verifies that read tools return untruncated data and appear in _public_actions.
"""

from __future__ import annotations

import pytest

from tract import Tract
from tract.hooks.compress import PendingCompress
from tract.hooks.gc import PendingGC
from tract.hooks.generation import PendingGeneration
from tract.hooks.merge import PendingMerge
from tract.hooks.pending import Pending
from tract.hooks.rebase import PendingRebase
from tract.hooks.tool_result import PendingToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tract() -> Tract:
    t = Tract.open(":memory:")
    t.system("You are a helpful assistant.")
    t.user("Hello")
    t.assistant("Hi there!")
    return t


def _make_pending_compress(summaries: list[str] | None = None) -> tuple[Tract, PendingCompress]:
    t = _make_tract()
    if summaries is None:
        summaries = ["Summary of group 0.", "Summary of group 1.", "Summary of group 2."]
    pc = PendingCompress(
        operation="compress",
        tract=t,
        summaries=list(summaries),
        source_commits=["aaa", "bbb", "ccc"],
        original_tokens=500,
        estimated_tokens=100,
    )
    return t, pc


def _make_pending_merge() -> tuple[Tract, PendingMerge]:
    t = _make_tract()

    class FakeConflict:
        def __init__(self, target_hash, conflict_type, a_text, b_text):
            self.target_hash = target_hash
            self.conflict_type = conflict_type
            self.content_a_text = a_text
            self.content_b_text = b_text

    conflicts = [
        FakeConflict("hash_a", "content", "ours version A", "theirs version A"),
        FakeConflict("hash_b", "content", "ours version B", "theirs version B"),
    ]
    pm = PendingMerge(
        operation="merge",
        tract=t,
        source_branch="feature",
        target_branch="main",
        conflicts=conflicts,
        resolutions={"hash_a": "resolved content A"},
    )
    return t, pm


def _make_pending_gc() -> tuple[Tract, PendingGC]:
    t = _make_tract()
    # Use real commit hashes from the tract
    log = t.log()
    hashes = [entry.commit_hash for entry in log[:2]]
    pgc = PendingGC(
        operation="gc",
        tract=t,
        commits_to_remove=hashes,
        tokens_to_free=200,
    )
    return t, pgc


def _make_pending_rebase() -> tuple[Tract, PendingRebase]:
    t = _make_tract()
    log = t.log()
    hashes = [entry.commit_hash for entry in log[:2]]
    pr = PendingRebase(
        operation="rebase",
        tract=t,
        replay_plan=hashes,
        target_base="deadbeef" * 4,
    )
    return t, pr


def _make_pending_tool_result() -> tuple[Tract, PendingToolResult]:
    t = _make_tract()
    ptr = PendingToolResult(
        operation="tool_result",
        tract=t,
        tool_call_id="call_123",
        tool_name="web_search",
        content="Full tool result content that could be very long " * 20,
        token_count=150,
    )
    return t, ptr


def _make_pending_generation() -> tuple[Tract, PendingGeneration]:
    t = _make_tract()
    pg = PendingGeneration(
        operation="generate",
        tract=t,
        response_text="Full LLM response text that could also be very long " * 20,
    )
    return t, pg


# ===========================================================================
# Base Pending: get_state()
# ===========================================================================


class TestGetState:
    """Tests for Pending.get_state() on the base class."""

    def test_get_state_in_public_actions(self):
        t = _make_tract()
        p = Pending(operation="test", tract=t)
        assert "get_state" in p._public_actions

    def test_get_state_returns_dict(self):
        t = _make_tract()
        p = Pending(operation="test", tract=t)
        state = p.get_state()
        assert isinstance(state, dict)
        assert state["operation"] == "test"
        assert state["status"] == "pending"
        assert "available_actions" in state
        assert "get_state" in state["available_actions"]

    def test_get_state_no_truncation(self):
        """get_state() must NOT truncate strings > 500 chars."""
        t, pc = _make_pending_compress()
        long_summary = "x" * 1000
        pc.summaries = [long_summary]
        state = pc.get_state()
        # The full string must be present, not clipped
        summaries = state["fields"]["summaries"]
        assert summaries[0] == long_summary
        assert len(summaries[0]) == 1000

    def test_get_state_no_list_truncation(self):
        """get_state() must NOT truncate lists > 5 items."""
        t, pc = _make_pending_compress()
        pc.summaries = [f"summary {i}" for i in range(10)]
        state = pc.get_state()
        summaries = state["fields"]["summaries"]
        assert isinstance(summaries, list)
        assert len(summaries) == 10

    def test_get_state_vs_to_dict_list_truncation(self):
        """Contrast: to_dict() truncates lists > 5 items, get_state() does not."""
        t, pc = _make_pending_compress()
        pc.summaries = [f"summary {i}" for i in range(8)]
        # to_dict truncates lists > 5
        d = pc.to_dict()
        truncated = d["fields"]["summaries"]
        assert isinstance(truncated, dict)
        assert truncated["_truncated"] is True
        assert truncated["_total"] == 8
        assert len(truncated["items"]) == 3
        # get_state does not truncate
        state = pc.get_state()
        assert isinstance(state["fields"]["summaries"], list)
        assert len(state["fields"]["summaries"]) == 8

    def test_get_state_via_execute_tool(self):
        """get_state() is callable via execute_tool() dispatch."""
        t, pc = _make_pending_compress()
        result = pc.execute_tool("get_state")
        assert isinstance(result, dict)
        assert result["operation"] == "compress"


# ===========================================================================
# PendingCompress: list_summaries(), get_summary()
# ===========================================================================


class TestCompressReadTools:
    def test_public_actions_include_read_tools(self):
        _, pc = _make_pending_compress()
        assert "list_summaries" in pc._public_actions
        assert "get_summary" in pc._public_actions
        assert "get_guidance" in pc._public_actions
        assert "get_state" in pc._public_actions

    def test_list_summaries(self):
        _, pc = _make_pending_compress()
        result = pc.list_summaries()
        assert len(result) == 3
        for i, entry in enumerate(result):
            assert entry["index"] == i
            assert "char_count" in entry
            assert "preview" in entry

    def test_list_summaries_preview_truncates_long(self):
        _, pc = _make_pending_compress(["a" * 200])
        result = pc.list_summaries()
        assert result[0]["preview"].endswith("...")
        assert len(result[0]["preview"]) == 83  # 80 + "..."

    def test_list_summaries_preview_short_no_truncation(self):
        _, pc = _make_pending_compress(["short"])
        result = pc.list_summaries()
        assert result[0]["preview"] == "short"

    def test_get_summary(self):
        _, pc = _make_pending_compress()
        assert pc.get_summary(0) == "Summary of group 0."
        assert pc.get_summary(2) == "Summary of group 2."

    def test_get_summary_untruncated(self):
        long_text = "z" * 2000
        _, pc = _make_pending_compress([long_text])
        assert pc.get_summary(0) == long_text
        assert len(pc.get_summary(0)) == 2000

    def test_get_summary_out_of_range(self):
        _, pc = _make_pending_compress()
        with pytest.raises(IndexError):
            pc.get_summary(99)

    def test_get_summary_via_execute_tool(self):
        _, pc = _make_pending_compress()
        result = pc.execute_tool("get_summary", {"index": 1})
        assert result == "Summary of group 1."

    def test_list_summaries_via_execute_tool(self):
        _, pc = _make_pending_compress()
        result = pc.execute_tool("list_summaries")
        assert len(result) == 3

    def test_get_guidance_none(self):
        _, pc = _make_pending_compress()
        result = pc.get_guidance()
        assert result == {"guidance": None, "guidance_source": None}

    def test_get_guidance_with_value(self):
        _, pc = _make_pending_compress()
        pc.guidance = "Focus on key facts"
        pc.guidance_source = "user"
        result = pc.get_guidance()
        assert result == {"guidance": "Focus on key facts", "guidance_source": "user"}

    def test_read_tools_in_to_tools(self):
        """Read tools must appear in to_tools() output."""
        _, pc = _make_pending_compress()
        tools = pc.to_tools()
        tool_names = {t["function"]["name"] for t in tools}
        assert "list_summaries" in tool_names
        assert "get_summary" in tool_names
        assert "get_guidance" in tool_names
        assert "get_state" in tool_names


# ===========================================================================
# PendingMerge: list_conflicts(), get_conflict(), get_resolution()
# ===========================================================================


class TestMergeReadTools:
    def test_public_actions_include_read_tools(self):
        _, pm = _make_pending_merge()
        assert "list_conflicts" in pm._public_actions
        assert "get_conflict" in pm._public_actions
        assert "get_resolution" in pm._public_actions
        assert "get_guidance" in pm._public_actions
        assert "get_state" in pm._public_actions

    def test_list_conflicts(self):
        _, pm = _make_pending_merge()
        result = pm.list_conflicts()
        assert len(result) == 2
        # First conflict is resolved
        assert result[0]["key"] == "hash_a"
        assert result[0]["resolved"] is True
        assert result[0]["conflict_type"] == "content"
        # Second is not resolved
        assert result[1]["key"] == "hash_b"
        assert result[1]["resolved"] is False

    def test_get_conflict(self):
        _, pm = _make_pending_merge()
        result = pm.get_conflict(0)
        assert result["key"] == "hash_a"
        assert result["content_a"] == "ours version A"
        assert result["content_b"] == "theirs version A"
        assert result["resolution"] == "resolved content A"

    def test_get_conflict_unresolved(self):
        _, pm = _make_pending_merge()
        result = pm.get_conflict(1)
        assert result["key"] == "hash_b"
        assert "resolution" not in result

    def test_get_conflict_out_of_range(self):
        _, pm = _make_pending_merge()
        with pytest.raises(IndexError):
            pm.get_conflict(99)

    def test_get_resolution(self):
        _, pm = _make_pending_merge()
        assert pm.get_resolution("hash_a") == "resolved content A"

    def test_get_resolution_missing_key(self):
        _, pm = _make_pending_merge()
        with pytest.raises(KeyError):
            pm.get_resolution("nonexistent")

    def test_get_guidance(self):
        _, pm = _make_pending_merge()
        pm.guidance = "Prefer the incoming version"
        pm.guidance_source = "user"
        result = pm.get_guidance()
        assert result == {"guidance": "Prefer the incoming version", "guidance_source": "user"}

    def test_read_tools_in_to_tools(self):
        _, pm = _make_pending_merge()
        tools = pm.to_tools()
        tool_names = {t["function"]["name"] for t in tools}
        assert "list_conflicts" in tool_names
        assert "get_conflict" in tool_names
        assert "get_resolution" in tool_names
        assert "get_guidance" in tool_names

    def test_list_conflicts_via_execute_tool(self):
        _, pm = _make_pending_merge()
        result = pm.execute_tool("list_conflicts")
        assert len(result) == 2

    def test_get_resolution_via_execute_tool(self):
        _, pm = _make_pending_merge()
        result = pm.execute_tool("get_resolution", {"key": "hash_a"})
        assert result == "resolved content A"


# ===========================================================================
# PendingGC: list_candidates()
# ===========================================================================


class TestGCReadTools:
    def test_public_actions_include_read_tools(self):
        _, pgc = _make_pending_gc()
        assert "list_candidates" in pgc._public_actions
        assert "get_state" in pgc._public_actions

    def test_list_candidates(self):
        _, pgc = _make_pending_gc()
        result = pgc.list_candidates()
        assert len(result) == 2
        for entry in result:
            assert "hash" in entry
            assert "short_hash" in entry
            assert len(entry["short_hash"]) == 8
            # Real commit hashes should resolve message/role
            assert "message" in entry or "role" in entry

    def test_list_candidates_via_execute_tool(self):
        _, pgc = _make_pending_gc()
        result = pgc.execute_tool("list_candidates")
        assert isinstance(result, list)

    def test_list_candidates_in_to_tools(self):
        _, pgc = _make_pending_gc()
        tools = pgc.to_tools()
        tool_names = {t["function"]["name"] for t in tools}
        assert "list_candidates" in tool_names


# ===========================================================================
# PendingRebase: list_commits()
# ===========================================================================


class TestRebaseReadTools:
    def test_public_actions_include_read_tools(self):
        _, pr = _make_pending_rebase()
        assert "list_commits" in pr._public_actions
        assert "get_state" in pr._public_actions

    def test_list_commits(self):
        _, pr = _make_pending_rebase()
        result = pr.list_commits()
        assert len(result) == 2
        for entry in result:
            assert "hash" in entry
            assert "short_hash" in entry
            assert len(entry["short_hash"]) == 8

    def test_list_commits_via_execute_tool(self):
        _, pr = _make_pending_rebase()
        result = pr.execute_tool("list_commits")
        assert isinstance(result, list)

    def test_list_commits_in_to_tools(self):
        _, pr = _make_pending_rebase()
        tools = pr.to_tools()
        tool_names = {t["function"]["name"] for t in tools}
        assert "list_commits" in tool_names


# ===========================================================================
# PendingToolResult: get_result()
# ===========================================================================


class TestToolResultReadTools:
    def test_public_actions_include_read_tools(self):
        _, ptr = _make_pending_tool_result()
        assert "get_result" in ptr._public_actions
        assert "get_state" in ptr._public_actions

    def test_get_result(self):
        _, ptr = _make_pending_tool_result()
        result = ptr.get_result()
        assert result == ptr.content
        assert "Full tool result content" in result

    def test_get_result_untruncated(self):
        _, ptr = _make_pending_tool_result()
        # Content is ~1000 chars, must not be clipped
        assert len(ptr.get_result()) > 500

    def test_get_result_reflects_edits(self):
        _, ptr = _make_pending_tool_result()
        ptr.edit_result("edited content")
        assert ptr.get_result() == "edited content"

    def test_get_result_via_execute_tool(self):
        _, ptr = _make_pending_tool_result()
        result = ptr.execute_tool("get_result")
        assert result == ptr.content

    def test_get_result_in_to_tools(self):
        _, ptr = _make_pending_tool_result()
        tools = ptr.to_tools()
        tool_names = {t["function"]["name"] for t in tools}
        assert "get_result" in tool_names


# ===========================================================================
# PendingGeneration: get_response()
# ===========================================================================


class TestGenerationReadTools:
    def test_public_actions_include_read_tools(self):
        _, pg = _make_pending_generation()
        assert "get_response" in pg._public_actions
        assert "get_state" in pg._public_actions

    def test_get_response(self):
        _, pg = _make_pending_generation()
        result = pg.get_response()
        assert result == pg.response_text
        assert "Full LLM response text" in result

    def test_get_response_untruncated(self):
        _, pg = _make_pending_generation()
        assert len(pg.get_response()) > 500

    def test_get_response_via_execute_tool(self):
        _, pg = _make_pending_generation()
        result = pg.execute_tool("get_response")
        assert result == pg.response_text

    def test_get_response_in_to_tools(self):
        _, pg = _make_pending_generation()
        tools = pg.to_tools()
        tool_names = {t["function"]["name"] for t in tools}
        assert "get_response" in tool_names


# ===========================================================================
# Cross-cutting: describe_api() includes read tools
# ===========================================================================


class TestDescribeApiIncludesReadTools:
    def test_compress_describe_api(self):
        _, pc = _make_pending_compress()
        api = pc.describe_api()
        assert "list_summaries" in api
        assert "get_summary" in api
        assert "get_guidance" in api
        assert "get_state" in api

    def test_merge_describe_api(self):
        _, pm = _make_pending_merge()
        api = pm.describe_api()
        assert "list_conflicts" in api
        assert "get_conflict" in api
        assert "get_resolution" in api
        assert "get_guidance" in api

    def test_gc_describe_api(self):
        _, pgc = _make_pending_gc()
        api = pgc.describe_api()
        assert "list_candidates" in api

    def test_rebase_describe_api(self):
        _, pr = _make_pending_rebase()
        api = pr.describe_api()
        assert "list_commits" in api

    def test_tool_result_describe_api(self):
        _, ptr = _make_pending_tool_result()
        api = ptr.describe_api()
        assert "get_result" in api

    def test_generation_describe_api(self):
        _, pg = _make_pending_generation()
        api = pg.describe_api()
        assert "get_response" in api
