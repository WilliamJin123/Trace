"""Tests for LoopConfig enhancements: step_budget and tool_validator."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tract import Tract
from tract.loop import LoopConfig, LoopResult, run_loop


# ---------------------------------------------------------------------------
# Helpers: mock LLM client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Mock LLM that returns pre-configured responses in sequence."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self._call_count = 0

    def chat(self, messages, *, model=None, temperature=None, max_tokens=None, **kw):
        resp = self._responses[min(self._call_count, len(self._responses) - 1)]
        self._call_count += 1
        return resp

    def extract_content(self, response):
        return response["choices"][0]["message"]["content"]

    def close(self):
        pass


def _make_text_response(text: str, tokens: int = 100) -> dict:
    """Build an OpenAI-style response dict with usage data."""
    return {
        "choices": [{"message": {"content": text, "tool_calls": None}}],
        "usage": {
            "prompt_tokens": tokens // 2,
            "completion_tokens": tokens - tokens // 2,
            "total_tokens": tokens,
        },
    }


def _make_tool_response(tool_name: str, args: dict[str, Any], tokens: int = 100) -> dict:
    """Build an OpenAI-style response with a tool call and usage data."""
    return {
        "choices": [{"message": {
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args),
                },
                "type": "function",
            }],
        }}],
        "usage": {
            "prompt_tokens": tokens // 2,
            "completion_tokens": tokens - tokens // 2,
            "total_tokens": tokens,
        },
    }


# ---------------------------------------------------------------------------
# step_budget tests
# ---------------------------------------------------------------------------


class TestStepBudget:
    def test_stops_when_budget_exceeded(self, tmp_path):
        """Loop should stop gracefully when token budget is exhausted."""
        client = MockLLMClient([
            _make_text_response("step 1", tokens=600),
            _make_text_response("step 2", tokens=600),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(t, config=LoopConfig(
            step_budget=500,
            stop_on_no_tool_call=False,
            max_steps=10,
        ), llm_client=client)
        assert result.status == "completed"
        assert result.budget_exhausted
        assert result.steps == 1  # stopped after first step exceeds budget

    def test_no_budget_runs_normally(self, tmp_path):
        """Loop runs to completion without budget constraint."""
        client = MockLLMClient([_make_text_response("done", tokens=1000)])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(t, config=LoopConfig(step_budget=None), llm_client=client)
        assert result.status == "completed"
        assert not result.budget_exhausted

    def test_budget_allows_completion_under_limit(self, tmp_path):
        """Loop completes normally when under budget."""
        client = MockLLMClient([_make_text_response("done", tokens=50)])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(t, config=LoopConfig(step_budget=1000), llm_client=client)
        assert result.status == "completed"
        assert not result.budget_exhausted

    def test_budget_check_accumulates_across_steps(self, tmp_path):
        """Budget tracks cumulative usage across multiple steps."""
        client = MockLLMClient([
            _make_text_response("step 1", tokens=300),
            _make_text_response("step 2", tokens=300),
            _make_text_response("step 3", tokens=300),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(t, config=LoopConfig(
            step_budget=500,
            stop_on_no_tool_call=False,
            max_steps=10,
        ), llm_client=client)
        assert result.status == "completed"
        assert result.budget_exhausted
        # Step 1: 300 tokens (under 500), Step 2: 600 tokens (over 500)
        assert result.steps == 2

    def test_budget_reason_contains_token_counts(self, tmp_path):
        """Budget exhaustion reason includes actual/limit token counts."""
        client = MockLLMClient([
            _make_text_response("step 1", tokens=600),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(t, config=LoopConfig(
            step_budget=500,
            stop_on_no_tool_call=False,
            max_steps=10,
        ), llm_client=client)
        assert "600" in result.reason
        assert "500" in result.reason


# ---------------------------------------------------------------------------
# tool_validator tests
# ---------------------------------------------------------------------------


class TestToolValidator:
    def test_rejects_invalid_tool_call(self, tmp_path):
        """Tool validator blocks invalid tool arguments."""
        def validator(name, args):
            if name == "dangerous_tool":
                return False, "Tool not allowed"
            return True, None

        client = MockLLMClient([
            _make_tool_response("dangerous_tool", {"x": 1}),
            _make_text_response("ok"),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(
            t,
            config=LoopConfig(tool_validator=validator),
            llm_client=client,
            tools=[{
                "type": "function",
                "function": {"name": "dangerous_tool", "parameters": {}},
            }],
        )
        # Tool was rejected, then LLM responded with text
        assert result.steps == 2

    def test_allows_valid_tool_call(self, tmp_path):
        """Tool validator allows valid tool arguments."""
        def validator(name, args):
            return True, None

        client = MockLLMClient([
            _make_tool_response("safe_tool", {"x": 1}),
            _make_text_response("done"),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(
            t,
            config=LoopConfig(tool_validator=validator),
            llm_client=client,
            tools=[{
                "type": "function",
                "function": {"name": "safe_tool", "parameters": {}},
            }],
            tool_handlers={"safe_tool": lambda x: f"result: {x}"},
        )
        assert result.status == "completed"

    def test_no_validator_allows_all(self, tmp_path):
        """Without validator, all tools pass through."""
        client = MockLLMClient([
            _make_tool_response("any_tool", {}),
            _make_text_response("done"),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        result = run_loop(
            t,
            config=LoopConfig(tool_validator=None),
            llm_client=client,
            tools=[{
                "type": "function",
                "function": {"name": "any_tool", "parameters": {}},
            }],
            tool_handlers={"any_tool": lambda: "ok"},
        )
        assert result.status == "completed"

    def test_validator_receives_correct_args(self, tmp_path):
        """Validator receives the tool name and parsed arguments."""
        calls: list[tuple[str, dict]] = []

        def validator(name, args):
            calls.append((name, args))
            return True, None

        client = MockLLMClient([
            _make_tool_response("my_tool", {"key": "value", "num": 42}),
            _make_text_response("done"),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        run_loop(
            t,
            config=LoopConfig(tool_validator=validator),
            llm_client=client,
            tools=[{
                "type": "function",
                "function": {"name": "my_tool", "parameters": {}},
            }],
            tool_handlers={"my_tool": lambda **kw: "ok"},
        )
        assert len(calls) == 1
        assert calls[0][0] == "my_tool"
        assert calls[0][1] == {"key": "value", "num": 42}

    def test_validator_error_committed_as_tool_result(self, tmp_path):
        """Rejected tool call is committed as an error result."""
        def validator(name, args):
            return False, "Argument 'path' is forbidden"

        tool_results: list[tuple[str, str, str]] = []

        client = MockLLMClient([
            _make_tool_response("file_write", {"path": "/etc/passwd"}),
            _make_text_response("ok"),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        run_loop(
            t,
            config=LoopConfig(tool_validator=validator),
            llm_client=client,
            tools=[{
                "type": "function",
                "function": {"name": "file_write", "parameters": {}},
            }],
            on_tool_result=lambda name, output, status: tool_results.append(
                (name, output, status)
            ),
        )
        assert len(tool_results) == 1
        assert tool_results[0][0] == "file_write"
        assert "Argument 'path' is forbidden" in tool_results[0][1]
        assert tool_results[0][2] == "error"

    def test_validator_default_error_message(self, tmp_path):
        """Rejected tool with None error message gets default text."""
        def validator(name, args):
            return False, None

        tool_results: list[tuple[str, str, str]] = []

        client = MockLLMClient([
            _make_tool_response("bad_tool", {}),
            _make_text_response("ok"),
        ])
        t = Tract.open(str(tmp_path / "test.db"))
        t.system("Test")
        run_loop(
            t,
            config=LoopConfig(tool_validator=validator),
            llm_client=client,
            tools=[{
                "type": "function",
                "function": {"name": "bad_tool", "parameters": {}},
            }],
            on_tool_result=lambda name, output, status: tool_results.append(
                (name, output, status)
            ),
        )
        assert "invalid arguments" in tool_results[0][1]


# ---------------------------------------------------------------------------
# LoopResult.budget_exhausted property
# ---------------------------------------------------------------------------


class TestLoopResultBudgetExhausted:
    def test_budget_exhausted_false_for_normal(self):
        r = LoopResult("completed", "LLM finished (no tool calls)", 1, 0)
        assert not r.budget_exhausted

    def test_budget_exhausted_true(self):
        r = LoopResult("completed", "Token budget exhausted (1000/500)", 1, 0)
        assert r.budget_exhausted

    def test_budget_exhausted_false_for_error(self):
        r = LoopResult("error", "budget something", 1, 0)
        assert not r.budget_exhausted

    def test_budget_exhausted_false_for_none_reason(self):
        r = LoopResult("completed", None, 1, 0)
        assert not r.budget_exhausted

    def test_budget_exhausted_false_for_max_steps(self):
        r = LoopResult("max_steps", "Reached max steps (50)", 50, 0)
        assert not r.budget_exhausted

    def test_budget_exhausted_false_for_blocked(self):
        r = LoopResult("blocked", "Token budget exceeded", 1, 0)
        assert not r.budget_exhausted
