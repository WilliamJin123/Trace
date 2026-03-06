"""Extension registries for custom conditions, actions, metrics, and triggers.

Follows the same pattern as tract's content type registry:
protocol-based registration with per-engine instances.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tract.rules.models import EvalContext


class ConditionEvaluator(Protocol):
    def evaluate(self, params: dict, ctx: EvalContext) -> bool: ...


class ActionHandler(Protocol):
    def execute(self, params: dict, ctx: EvalContext) -> object: ...


class MetricProvider(Protocol):
    def compute(self, ctx: EvalContext) -> float: ...


class TriggerSource(Protocol):
    def check(self, ctx: EvalContext) -> bool: ...


class Registry:
    """Unified registry for extensibility points.

    Per-Tract instance — not global. Custom conditions/actions flow into
    the RuleEngine via ``custom_conditions`` / ``custom_actions`` parameters.
    Custom metrics are consulted by ``_get_metric()`` in conditions.py.
    """

    def __init__(self) -> None:
        self._conditions: dict[str, ConditionEvaluator] = {}
        self._actions: dict[str, ActionHandler] = {}
        self._metrics: dict[str, MetricProvider] = {}
        self._triggers: dict[str, TriggerSource] = {}

    def register_condition(self, name: str, evaluator: ConditionEvaluator) -> None:
        """Register a custom condition evaluator."""
        self._conditions[name] = evaluator

    def register_action(self, name: str, handler: ActionHandler) -> None:
        """Register a custom action handler."""
        self._actions[name] = handler

    def register_metric(self, name: str, provider: MetricProvider) -> None:
        """Register a custom metric for threshold conditions."""
        self._metrics[name] = provider

    def register_trigger(self, name: str, source: TriggerSource) -> None:
        """Register a custom trigger source."""
        self._triggers[name] = source

    @property
    def conditions(self) -> dict[str, ConditionEvaluator]:
        return dict(self._conditions)

    @property
    def actions(self) -> dict[str, ActionHandler]:
        return dict(self._actions)

    @property
    def metrics(self) -> dict[str, MetricProvider]:
        return dict(self._metrics)

    @property
    def triggers(self) -> dict[str, TriggerSource]:
        return dict(self._triggers)
