"""Tests for the Registry class, custom extensibility, and Tract facade wiring."""

import types

import pytest

from tract.rules.engine import RuleEngine
from tract.rules.index import RuleIndex
from tract.rules.models import ActionResult, EvalContext, RuleEntry
from tract.rules.registries import Registry


# ---------------------------------------------------------------------------
# Custom protocol implementations for testing
# ---------------------------------------------------------------------------


class AlwaysTrueCondition:
    def evaluate(self, params, ctx):
        return True


class AlwaysFalseCondition:
    def evaluate(self, params, ctx):
        return False


class ParamCondition:
    """Returns True/False based on a 'expected' param."""

    def evaluate(self, params, ctx):
        return params.get("expected", False)


class CounterAction:
    def __init__(self):
        self.count = 0

    def execute(self, params, ctx):
        self.count += 1
        return ActionResult("custom_counter", True, {"count": self.count})


class FixedMetric:
    def __init__(self, value):
        self._value = value

    def compute(self, ctx):
        return self._value


class SimpleTrigger:
    def __init__(self, result):
        self._result = result

    def check(self, ctx):
        return self._result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_tract(registry=None):
    mock = types.SimpleNamespace()
    mock._rule_eval_depth = 0
    mock._registry = registry or Registry()
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
# Registry basics
# ===========================================================================


class TestRegistryBasics:
    def test_register_condition(self):
        reg = Registry()
        cond = AlwaysTrueCondition()
        reg.register_condition("always_true", cond)
        assert "always_true" in reg.conditions
        assert reg.conditions["always_true"] is cond

    def test_register_action(self):
        reg = Registry()
        act = CounterAction()
        reg.register_action("counter", act)
        assert "counter" in reg.actions
        assert reg.actions["counter"] is act

    def test_register_metric(self):
        reg = Registry()
        met = FixedMetric(42.0)
        reg.register_metric("custom_score", met)
        assert "custom_score" in reg.metrics
        assert reg.metrics["custom_score"] is met

    def test_register_trigger(self):
        reg = Registry()
        trig = SimpleTrigger(True)
        reg.register_trigger("custom_trigger", trig)
        assert "custom_trigger" in reg.triggers
        assert reg.triggers["custom_trigger"] is trig

    def test_properties_return_copies(self):
        reg = Registry()
        reg.register_condition("c", AlwaysTrueCondition())
        reg.register_action("a", CounterAction())
        reg.register_metric("m", FixedMetric(1.0))
        reg.register_trigger("t", SimpleTrigger(True))

        # Mutating the returned dict should not affect the registry
        conds = reg.conditions
        conds["injected"] = AlwaysFalseCondition()
        assert "injected" not in reg.conditions

        acts = reg.actions
        acts["injected"] = CounterAction()
        assert "injected" not in reg.actions

        mets = reg.metrics
        mets["injected"] = FixedMetric(0)
        assert "injected" not in reg.metrics

        trigs = reg.triggers
        trigs["injected"] = SimpleTrigger(False)
        assert "injected" not in reg.triggers


# ===========================================================================
# Custom condition in rule engine
# ===========================================================================


class TestCustomConditionInRule:
    def test_custom_condition_true_fires_rule(self):
        reg = Registry()
        reg.register_condition("always_true", AlwaysTrueCondition())
        mock = _make_mock_tract(registry=reg)

        idx = RuleIndex()
        idx.add_rule(_rule(
            "guarded",
            condition={"type": "always_true"},
            action={"type": "set_config", "key": "x", "value": 1},
        ))
        engine = RuleEngine(idx, custom_conditions=reg.conditions)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_fired == 1
        assert result.action_results[0].data["value"] == 1

    def test_custom_condition_false_blocks_rule(self):
        reg = Registry()
        reg.register_condition("always_false", AlwaysFalseCondition())
        mock = _make_mock_tract(registry=reg)

        idx = RuleIndex()
        idx.add_rule(_rule(
            "guarded",
            condition={"type": "always_false"},
            action={"type": "set_config", "key": "x", "value": 1},
        ))
        engine = RuleEngine(idx, custom_conditions=reg.conditions)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_evaluated == 1
        assert result.rules_fired == 0

    def test_custom_condition_with_params(self):
        reg = Registry()
        reg.register_condition("param_check", ParamCondition())
        mock = _make_mock_tract(registry=reg)

        idx = RuleIndex()
        idx.add_rule(_rule(
            "param_rule",
            condition={"type": "param_check", "expected": True},
            action={"type": "set_config", "key": "y", "value": 42},
        ))
        engine = RuleEngine(idx, custom_conditions=reg.conditions)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_fired == 1


# ===========================================================================
# Custom action in rule engine
# ===========================================================================


class TestCustomActionInRule:
    def test_custom_action_executes(self):
        reg = Registry()
        counter = CounterAction()
        reg.register_action("custom_counter", counter)
        mock = _make_mock_tract(registry=reg)

        idx = RuleIndex()
        idx.add_rule(_rule("count_it", action={"type": "custom_counter"}))
        engine = RuleEngine(idx, custom_actions=reg.actions)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_fired == 1
        assert result.action_results[0].action_type == "custom_counter"
        assert result.action_results[0].data["count"] == 1
        assert counter.count == 1

    def test_custom_action_accumulates(self):
        reg = Registry()
        counter = CounterAction()
        reg.register_action("custom_counter", counter)
        mock = _make_mock_tract(registry=reg)

        idx = RuleIndex()
        idx.add_rule(_rule("c1", action={"type": "custom_counter"}, dag_distance=0))
        idx.add_rule(_rule("c2", action={"type": "custom_counter"}, dag_distance=1))
        engine = RuleEngine(idx, custom_actions=reg.actions)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_fired == 2
        assert counter.count == 2


# ===========================================================================
# Custom metric in threshold condition
# ===========================================================================


class TestCustomMetricInThreshold:
    def test_custom_metric_above_threshold(self):
        reg = Registry()
        reg.register_metric("custom_score", FixedMetric(42.0))
        mock = _make_mock_tract(registry=reg)

        idx = RuleIndex()
        idx.add_rule(_rule(
            "score_check",
            condition={"type": "threshold", "metric": "custom_score", "op": ">", "value": 10},
            action={"type": "set_config", "key": "scored", "value": True},
        ))
        engine = RuleEngine(idx, custom_conditions=reg.conditions)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_fired == 1
        assert result.action_results[0].data["value"] is True

    def test_custom_metric_below_threshold(self):
        reg = Registry()
        reg.register_metric("custom_score", FixedMetric(5.0))
        mock = _make_mock_tract(registry=reg)

        idx = RuleIndex()
        idx.add_rule(_rule(
            "score_check",
            condition={"type": "threshold", "metric": "custom_score", "op": ">", "value": 10},
            action={"type": "set_config", "key": "scored", "value": True},
        ))
        engine = RuleEngine(idx, custom_conditions=reg.conditions)
        ctx = _make_ctx(mock)
        result = engine.process_event("test", ctx)

        assert result.rules_evaluated == 1
        assert result.rules_fired == 0


# ===========================================================================
# Registry through Tract facade
# ===========================================================================


class TestRegistryThroughFacade:
    def test_register_condition_on_tract(self, t):
        t.register_condition("always_true", AlwaysTrueCondition())
        assert "always_true" in t._registry.conditions

    def test_register_action_on_tract(self, t):
        t.register_action("counter", CounterAction())
        assert "counter" in t._registry.actions

    def test_register_metric_on_tract(self, t):
        t.register_metric("custom_score", FixedMetric(99.0))
        assert "custom_score" in t._registry.metrics

    def test_custom_condition_fires_via_facade(self, t):
        t.register_condition("always_true", AlwaysTrueCondition())
        t.user("hello")
        t.rule(
            "test_rule",
            trigger="commit",
            condition={"type": "always_true"},
            action={"type": "set_config", "key": "fired", "value": True},
        )
        result = t._fire_rules("commit")
        config_results = [ar for ar in result.action_results if ar.action_type == "set_config"]
        assert len(config_results) == 1
        assert config_results[0].data["value"] is True

    def test_custom_metric_via_facade(self, t):
        t.register_metric("custom_score", FixedMetric(42.0))
        t.user("hello")
        t.rule(
            "check_score",
            trigger="commit",
            condition={"type": "threshold", "metric": "custom_score", "op": ">", "value": 10},
            action={"type": "set_config", "key": "above", "value": True},
        )
        result = t._fire_rules("commit")
        config_results = [ar for ar in result.action_results if ar.action_type == "set_config"]
        assert len(config_results) == 1
        assert config_results[0].data["value"] is True

    def test_register_invalidates_engine(self, t):
        """Registering a condition/action invalidates the cached engine."""
        # Access the engine to initialize it
        _ = t._rule_engine
        old_engine = t._Tract__rule_engine

        t.register_condition("new_cond", AlwaysTrueCondition())
        # Engine should be reset to None so it rebuilds with new custom conditions
        assert t._Tract__rule_engine is None

        t.register_action("new_act", CounterAction())
        assert t._Tract__rule_engine is None


# ===========================================================================
# Registry isolation between Tract instances
# ===========================================================================


class TestRegistryIsolation:
    def test_two_tracts_independent_registries(self, tmp_path):
        from tract import Tract

        t1 = Tract.open(str(tmp_path / "t1.db"))
        t2 = Tract.open(str(tmp_path / "t2.db"))
        try:
            t1.register_condition("only_in_t1", AlwaysTrueCondition())
            t2.register_metric("only_in_t2", FixedMetric(99.0))

            assert "only_in_t1" in t1._registry.conditions
            assert "only_in_t1" not in t2._registry.conditions
            assert "only_in_t2" in t2._registry.metrics
            assert "only_in_t2" not in t1._registry.metrics
        finally:
            t1.close()
            t2.close()

    def test_registries_are_not_shared_instances(self, tmp_path):
        from tract import Tract

        t1 = Tract.open(str(tmp_path / "t1.db"))
        t2 = Tract.open(str(tmp_path / "t2.db"))
        try:
            assert t1._registry is not t2._registry
        finally:
            t1.close()
            t2.close()
