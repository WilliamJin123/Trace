"""Tests for LLM condition and action evaluation with mock LLM clients."""

import types

import pytest

from tract.rules.actions import LLMAction
from tract.rules.conditions import LLMCondition, evaluate_condition
from tract.rules.engine import RuleEngine
from tract.rules.index import RuleIndex
from tract.rules.models import ActionResult, EvalContext, RuleEntry


# ---------------------------------------------------------------------------
# Mock LLM clients
# ---------------------------------------------------------------------------


class MockLLMClient:
    def __init__(self, response_text):
        self._response = response_text
        self.call_count = 0

    def chat(self, messages, **kwargs):
        self.call_count += 1
        return {"choices": [{"message": {"content": self._response}}]}

    def extract_content(self, response):
        return response["choices"][0]["message"]["content"]

    def close(self):
        pass


class TrackingLLMClient:
    def __init__(self):
        self.call_count = 0

    def chat(self, messages, **kwargs):
        self.call_count += 1
        return {"choices": [{"message": {"content": "true"}}]}

    def extract_content(self, response):
        return response["choices"][0]["message"]["content"]

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_tract(llm_client=None):
    mock = types.SimpleNamespace()
    mock._rule_eval_depth = 0
    mock._llm_client = llm_client
    return mock


def _make_ctx(mock_tract, event="test", commit=None, metrics=None):
    return EvalContext(
        event=event,
        commit=commit,
        branch="main",
        head="abc123",
        tract=mock_tract,
        metrics=metrics or {"total_tokens": 100},
        rule_index=RuleIndex(),
    )


def _rule(name, trigger="test", condition=None, action=None, commit_hash="h1", dag_distance=0):
    return RuleEntry(
        name=name,
        trigger=trigger,
        condition=condition,
        action=action or {},
        commit_hash=commit_hash,
        dag_distance=dag_distance,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def t(tmp_path):
    from tract import Tract

    tract = Tract.open(str(tmp_path / "test.db"))
    yield tract
    tract.close()


# ===========================================================================
# LLMCondition unit tests
# ===========================================================================


class TestLLMCondition:
    def test_llm_condition_true(self):
        client = MockLLMClient("true")
        mock = _make_mock_tract(llm_client=client)
        ctx = _make_ctx(mock)
        cond = LLMCondition()
        result = cond.evaluate({"instruction": "Is this valid?"}, ctx)
        assert result is True
        assert client.call_count == 1

    def test_llm_condition_false(self):
        client = MockLLMClient("false")
        mock = _make_mock_tract(llm_client=client)
        ctx = _make_ctx(mock)
        cond = LLMCondition()
        result = cond.evaluate({"instruction": "Is this valid?"}, ctx)
        assert result is False
        assert client.call_count == 1

    def test_llm_condition_no_client(self):
        mock = _make_mock_tract(llm_client=None)
        ctx = _make_ctx(mock)
        cond = LLMCondition()
        result = cond.evaluate({"instruction": "anything"}, ctx)
        assert result is True  # permissive default


# ===========================================================================
# LLMAction unit tests
# ===========================================================================


class TestLLMAction:
    def test_llm_action_executes(self, t):
        t.system("You are a helpful assistant.")
        t.user("Hello world")
        t.assistant("Hi there!")

        client = MockLLMClient("Here is the summary.")
        t._llm_client = client

        action = LLMAction()
        ctx = EvalContext(
            event="test",
            commit=None,
            branch=t.current_branch or "",
            head=t.head or "",
            tract=t,
            metrics={"total_tokens": 0},
            rule_index=t.rule_index,
        )
        result = action.execute({"instruction": "Summarize this"}, ctx)
        assert result.action_type == "llm"
        assert result.success is True
        assert result.data["response"] == "Here is the summary."
        assert client.call_count == 1

    def test_llm_action_no_client(self, t):
        action = LLMAction()
        ctx = EvalContext(
            event="test",
            commit=None,
            branch=t.current_branch or "",
            head=t.head or "",
            tract=t,
            metrics={"total_tokens": 0},
            rule_index=t.rule_index,
        )
        result = action.execute({"instruction": "Summarize"}, ctx)
        assert result.action_type == "llm"
        assert result.success is False
        assert "No LLM client" in result.reason


# ===========================================================================
# LLM condition in full rule engine pipeline
# ===========================================================================


class TestLLMConditionInRule:
    def test_llm_condition_fires_rule(self):
        client = MockLLMClient("true")
        mock = _make_mock_tract(llm_client=client)

        idx = RuleIndex()
        idx.add_rule(_rule(
            "llm_guarded",
            condition={"type": "llm", "instruction": "Is this okay?"},
            action={"type": "set_config", "key": "approved", "value": True},
        ))
        engine = RuleEngine(idx)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_fired == 1
        assert result.action_results[0].data["value"] is True

    def test_llm_condition_blocks_rule(self):
        client = MockLLMClient("false")
        mock = _make_mock_tract(llm_client=client)

        idx = RuleIndex()
        idx.add_rule(_rule(
            "llm_guarded",
            condition={"type": "llm", "instruction": "Is this okay?"},
            action={"type": "set_config", "key": "approved", "value": True},
        ))
        engine = RuleEngine(idx)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_evaluated == 1
        assert result.rules_fired == 0


# ===========================================================================
# LLM condition sorting: deterministic first, LLM last
# ===========================================================================


class TestLLMConditionSorting:
    def test_llm_condition_sorted_last(self):
        """In gate category, deterministic conditions evaluate before LLM ones."""
        tracker = TrackingLLMClient()
        mock = _make_mock_tract(llm_client=tracker)

        idx = RuleIndex()
        # LLM gate at distance 0
        idx.add_rule(_rule(
            "llm_gate",
            condition={"type": "llm", "instruction": "check?"},
            action={"type": "require", "condition": None},
            dag_distance=0,
        ))
        # Deterministic gate at distance 0
        idx.add_rule(_rule(
            "det_gate",
            condition={"type": "threshold", "metric": "total_tokens", "op": "<", "value": 500},
            action={"type": "require", "condition": None},
            dag_distance=0,
        ))
        engine = RuleEngine(idx)
        ctx = _make_ctx(mock, metrics={"total_tokens": 100})
        result = engine.process_event("test", ctx)

        # Both should fire; deterministic first, then LLM
        assert result.rules_evaluated == 2
        assert result.rules_fired == 2
        # LLM was called (sorted last but still evaluated)
        assert tracker.call_count == 1

    def test_short_circuit_skips_llm(self):
        """A deterministic gate that blocks prevents the LLM condition from evaluating."""
        tracker = TrackingLLMClient()
        mock = _make_mock_tract(llm_client=tracker)

        idx = RuleIndex()
        # LLM gate (should be sorted after the deterministic block)
        idx.add_rule(_rule(
            "llm_gate",
            condition={"type": "llm", "instruction": "expensive check"},
            action={"type": "require", "condition": None},
            dag_distance=0,
        ))
        # Deterministic block (sorted first, will short-circuit)
        idx.add_rule(_rule(
            "blocker",
            action={"type": "block", "reason": "always blocked"},
            dag_distance=0,
        ))
        engine = RuleEngine(idx)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        # The block fires first, pipeline stops
        assert result.blocked
        assert result.rules_fired == 1
        # LLM was never called because the deterministic block short-circuited
        assert tracker.call_count == 0
