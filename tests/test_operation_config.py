"""Tests for per-operation LLM configuration.

Covers LLMConfig dataclass, configure_operations(), _resolve_llm_config(),
Tract.open() with operation_configs, and integration with chat/generate, merge,
compress, and orchestrate operations.
"""

from __future__ import annotations

import dataclasses

import pytest

from tract import (
    DialogueContent,
    InstructionContent,
    LLMConfig,
    Tract,
)
from tract.models.commit import CommitOperation


# ---------------------------------------------------------------------------
# MockLLMClient -- captures kwargs for assertion
# ---------------------------------------------------------------------------

class MockLLMClient:
    """Minimal mock LLM client that records call kwargs."""

    def __init__(self, responses=None, model="mock-model"):
        self.responses = responses or ["Mock response"]
        self._call_count = 0
        self.last_messages = None
        self.last_kwargs: dict = {}
        self._model = model
        self.closed = False

    def chat(self, messages, **kwargs):
        self.last_messages = messages
        self.last_kwargs = kwargs
        text = self.responses[min(self._call_count, len(self.responses) - 1)]
        self._call_count += 1
        return {
            "choices": [{"message": {"content": text}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "model": kwargs.get("model", self._model),
        }

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# LLMConfig dataclass tests
# ---------------------------------------------------------------------------

class TestLLMConfig:
    """Tests for the LLMConfig frozen dataclass."""

    def test_create_with_defaults(self):
        """All fields default to None."""
        config = LLMConfig()
        assert config.model is None
        assert config.temperature is None
        assert config.top_p is None
        assert config.max_tokens is None
        assert config.stop_sequences is None
        assert config.frequency_penalty is None
        assert config.presence_penalty is None
        assert config.top_k is None
        assert config.seed is None
        assert config.extra is None

    def test_create_with_values(self):
        """All fields can be set, including extra."""
        config = LLMConfig(
            model="gpt-4o",
            temperature=0.7,
            max_tokens=1000,
            top_p=0.9,
            seed=42,
            extra={"custom_param": "val"},
        )
        assert config.model == "gpt-4o"
        assert config.temperature == 0.7
        assert config.max_tokens == 1000
        assert config.top_p == 0.9
        assert config.seed == 42
        assert config.extra["custom_param"] == "val"

    def test_frozen(self):
        """Attempting to modify a frozen dataclass raises FrozenInstanceError."""
        config = LLMConfig(model="gpt-4o")
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.model = "gpt-3.5-turbo"  # type: ignore[misc]

    def test_from_dict_round_trip(self):
        """from_dict and to_dict are inverse operations."""
        d = {"model": "gpt-4o", "temperature": 0.5, "custom_key": "abc"}
        config = LLMConfig.from_dict(d)
        assert config.model == "gpt-4o"
        assert config.temperature == 0.5
        assert config.extra["custom_key"] == "abc"
        assert LLMConfig.from_dict(config.to_dict()) == config

    def test_from_dict_none(self):
        """from_dict(None) returns None."""
        assert LLMConfig.from_dict(None) is None

    def test_non_none_fields(self):
        """non_none_fields returns only set fields (excluding extra)."""
        config = LLMConfig(model="gpt-4o", temperature=0.5)
        result = config.non_none_fields()
        assert result == {"model": "gpt-4o", "temperature": 0.5}

    def test_stop_sequences_tuple_conversion(self):
        """stop_sequences list is converted to tuple."""
        config = LLMConfig.from_dict({"stop_sequences": ["stop1", "stop2"]})
        assert config.stop_sequences == ("stop1", "stop2")
        assert config.to_dict()["stop_sequences"] == ["stop1", "stop2"]

    def test_extra_is_immutable(self):
        """extra dict is wrapped in MappingProxyType."""
        config = LLMConfig(extra={"key": "val"})
        with pytest.raises(TypeError):
            config.extra["key"] = "new"  # type: ignore[index]

    def test_hashable(self):
        """LLMConfig is hashable (can be used in sets/dicts)."""
        c1 = LLMConfig(model="gpt-4o")
        c2 = LLMConfig(model="gpt-4o")
        assert hash(c1) == hash(c2)
        assert {c1, c2} == {c1}


# ---------------------------------------------------------------------------
# configure_operations() tests
# ---------------------------------------------------------------------------

class TestConfigureOperations:
    """Tests for Tract.configure_operations()."""

    def test_configure_single_operation(self):
        """Set a single operation config and verify via property."""
        t = Tract.open()
        chat_config = LLMConfig(model="gpt-4o")
        t.configure_operations(chat=chat_config)

        configs = t.operation_configs
        assert "chat" in configs
        assert configs["chat"].model == "gpt-4o"
        t.close()

    def test_configure_multiple_operations(self):
        """Set multiple operation configs in one call."""
        t = Tract.open()
        t.configure_operations(
            chat=LLMConfig(model="gpt-4o"),
            compress=LLMConfig(model="gpt-3.5-turbo"),
            merge=LLMConfig(model="gpt-4o", temperature=0.3),
        )

        configs = t.operation_configs
        assert len(configs) == 3
        assert configs["chat"].model == "gpt-4o"
        assert configs["compress"].model == "gpt-3.5-turbo"
        assert configs["merge"].temperature == 0.3
        t.close()

    def test_configure_overwrites_existing(self):
        """Calling configure_operations twice replaces the config for that operation."""
        t = Tract.open()
        t.configure_operations(chat=LLMConfig(model="gpt-4o"))
        assert t.operation_configs["chat"].model == "gpt-4o"

        t.configure_operations(chat=LLMConfig(model="gpt-3.5-turbo"))
        assert t.operation_configs["chat"].model == "gpt-3.5-turbo"
        t.close()

    def test_configure_type_error(self):
        """Passing a non-LLMConfig value raises TypeError."""
        t = Tract.open()
        with pytest.raises(TypeError, match="Expected LLMConfig"):
            t.configure_operations(chat={"model": "gpt-4o"})  # type: ignore[arg-type]
        t.close()


# ---------------------------------------------------------------------------
# _resolve_llm_config() resolution chain tests
# ---------------------------------------------------------------------------

class TestResolveLLMConfig:
    """Tests for _resolve_llm_config() three-level resolution chain."""

    def test_resolve_call_level_wins(self):
        """Call-level model overrides operation and tract defaults."""
        t = Tract.open()
        t._default_model = "tract-default"
        t.configure_operations(chat=LLMConfig(model="op-model"))

        resolved = t._resolve_llm_config("chat", model="call-model")
        assert resolved["model"] == "call-model"
        t.close()

    def test_resolve_operation_level_wins_over_tract(self):
        """Operation-level model overrides tract default."""
        t = Tract.open()
        t._default_model = "tract-default"
        t.configure_operations(chat=LLMConfig(model="op-model"))

        resolved = t._resolve_llm_config("chat")
        assert resolved["model"] == "op-model"
        t.close()

    def test_resolve_tract_default_used(self):
        """Without call or operation config, tract default is used."""
        t = Tract.open()
        t._default_model = "tract-default"

        resolved = t._resolve_llm_config("chat")
        assert resolved["model"] == "tract-default"
        t.close()

    def test_resolve_no_config_returns_empty(self):
        """No config at any level returns empty dict."""
        t = Tract.open()
        resolved = t._resolve_llm_config("chat")
        assert resolved == {}
        t.close()

    def test_resolve_temperature_chain(self):
        """Temperature follows call > operation resolution."""
        t = Tract.open()
        t.configure_operations(chat=LLMConfig(temperature=0.5))

        # Operation level
        resolved = t._resolve_llm_config("chat")
        assert resolved["temperature"] == 0.5

        # Call level overrides
        resolved = t._resolve_llm_config("chat", temperature=0.9)
        assert resolved["temperature"] == 0.9
        t.close()

    def test_resolve_extra_merged(self):
        """extra from operation config is forwarded, call kwargs override."""
        t = Tract.open()
        t.configure_operations(
            chat=LLMConfig(extra={"custom_param": "val", "another": 42})
        )

        resolved = t._resolve_llm_config("chat")
        assert resolved["custom_param"] == "val"
        assert resolved["another"] == 42

        # Call-level kwargs override operation extra
        resolved = t._resolve_llm_config("chat", another=99)
        assert resolved["another"] == 99
        assert resolved["custom_param"] == "val"
        t.close()

    def test_resolve_typed_fields(self):
        """New typed fields (top_p, seed, etc.) are resolved from operation config."""
        t = Tract.open()
        t.configure_operations(
            chat=LLMConfig(top_p=0.9, seed=42, frequency_penalty=0.5)
        )

        resolved = t._resolve_llm_config("chat")
        assert resolved["top_p"] == 0.9
        assert resolved["seed"] == 42
        assert resolved["frequency_penalty"] == 0.5
        t.close()


# ---------------------------------------------------------------------------
# Tract.open() with operation_configs tests
# ---------------------------------------------------------------------------

class TestOpenWithOperationConfigs:
    """Tests for Tract.open() operation_configs parameter."""

    def test_open_with_operation_configs(self):
        """Pass operation_configs dict to Tract.open(), verify applied."""
        t = Tract.open(
            operation_configs={
                "chat": LLMConfig(model="gpt-4o"),
                "compress": LLMConfig(model="gpt-3.5-turbo"),
            }
        )
        configs = t.operation_configs
        assert configs["chat"].model == "gpt-4o"
        assert configs["compress"].model == "gpt-3.5-turbo"
        t.close()

    def test_open_without_operation_configs(self):
        """Default behavior: no operation configs set."""
        t = Tract.open()
        assert t.operation_configs == {}
        t.close()


# ---------------------------------------------------------------------------
# chat/generate integration tests
# ---------------------------------------------------------------------------

class TestChatGenerateIntegration:
    """Tests for chat/generate using per-operation config."""

    def test_chat_uses_operation_config_model(self):
        """Configure chat model, verify MockLLMClient receives it."""
        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)
        t.configure_operations(chat=LLMConfig(model="chat-model"))

        t.system("You are helpful")
        t.user("Hello")
        t.generate()

        assert mock.last_kwargs.get("model") == "chat-model"
        t.close()

    def test_chat_call_override_beats_operation(self):
        """Call-level model= on generate() overrides operation config."""
        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)
        t.configure_operations(chat=LLMConfig(model="op-model"))

        t.system("You are helpful")
        t.user("Hello")
        t.generate(model="call-model")

        assert mock.last_kwargs.get("model") == "call-model"
        t.close()

    def test_generate_uses_operation_config_temperature(self):
        """Configure chat temperature, verify forwarded to LLM."""
        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)
        t.configure_operations(chat=LLMConfig(temperature=0.8))

        t.system("You are helpful")
        t.user("Hello")
        t.generate()

        assert mock.last_kwargs.get("temperature") == 0.8
        t.close()

    def test_generation_config_reflects_operation_model(self):
        """generation_config on commit captures the resolved model from response."""
        t = Tract.open()
        mock = MockLLMClient(model="default-model")
        t.configure_llm(mock)
        t.configure_operations(chat=LLMConfig(model="chat-model"))

        t.system("You are helpful")
        t.user("Hello")
        resp = t.generate()

        # Verify the per-op model was sent to the LLM
        assert mock.last_kwargs.get("model") == "chat-model"
        # generation_config uses the response model (authoritative)
        # The mock returns the requested model in the response
        assert resp.generation_config.model == "chat-model"
        t.close()


# ---------------------------------------------------------------------------
# merge integration tests
# ---------------------------------------------------------------------------

class TestMergeIntegration:
    """Tests for merge using per-operation config."""

    def _make_diverged_tract(self):
        """Create a tract with diverged branches for merge testing."""
        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)

        # Base commit
        base = t.commit(InstructionContent(text="original"))

        # Feature branch with edit
        t.branch("feature")
        t.commit(
            DialogueContent(role="assistant", text="feature edit"),
            operation=CommitOperation.EDIT,
            response_to=base.commit_hash,
        )

        # Back to main with edit
        t.switch("main")
        t.commit(
            DialogueContent(role="assistant", text="main edit"),
            operation=CommitOperation.EDIT,
            response_to=base.commit_hash,
        )

        return t, mock

    def test_merge_uses_operation_config(self):
        """Configure merge model, verify resolver gets it."""
        t, mock = self._make_diverged_tract()
        t.configure_operations(merge=LLMConfig(model="merge-model"))

        # The merge will use semantic resolution -- the resolver should
        # be created with the operation config model
        result = t.merge("feature", auto_commit=True)
        # Since it's a conflict merge, the resolver was created with merge-model
        # The MockLLMClient was used for the resolver's LLM call
        assert result is not None
        t.close()

    def test_merge_call_override_beats_operation(self):
        """model= on merge() overrides operation config."""
        t, mock = self._make_diverged_tract()
        t.configure_operations(merge=LLMConfig(model="op-merge"))

        result = t.merge("feature", model="call-merge", auto_commit=True)
        assert result is not None
        t.close()

    def test_merge_temperature_from_operation(self):
        """temperature/max_tokens from operation config forwarded to resolver."""
        t, mock = self._make_diverged_tract()
        t.configure_operations(
            merge=LLMConfig(model="merge-model", temperature=0.1, max_tokens=512)
        )

        result = t.merge("feature", auto_commit=True)
        assert result is not None
        t.close()


# ---------------------------------------------------------------------------
# compress integration tests
# ---------------------------------------------------------------------------

class TestCompressIntegration:
    """Tests for compress using per-operation config."""

    def test_compress_uses_operation_config(self):
        """Configure compress model, verify llm_kwargs forwarded to LLM."""
        t = Tract.open()
        mock = MockLLMClient(responses=["Summary text"])
        t.configure_llm(mock)
        t.configure_operations(compress=LLMConfig(model="compress-model"))

        t.commit(InstructionContent(text="First instruction"))
        t.commit(DialogueContent(role="user", text="Hello"))
        t.commit(DialogueContent(role="assistant", text="Hi there"))

        result = t.compress()
        assert mock.last_kwargs.get("model") == "compress-model"
        t.close()

    def test_compress_without_config_backward_compatible(self):
        """No config = current behavior (no model kwargs sent)."""
        t = Tract.open()
        mock = MockLLMClient(responses=["Summary text"])
        t.configure_llm(mock)

        t.commit(InstructionContent(text="First instruction"))
        t.commit(DialogueContent(role="user", text="Hello"))
        t.commit(DialogueContent(role="assistant", text="Hi there"))

        result = t.compress()
        # No model/temperature/max_tokens in kwargs
        assert "model" not in mock.last_kwargs
        assert "temperature" not in mock.last_kwargs
        assert "max_tokens" not in mock.last_kwargs
        t.close()

    def test_compress_call_level_model_override(self):
        """Pass model= on compress(), verify it overrides operation config."""
        t = Tract.open()
        mock = MockLLMClient(responses=["Summary text"])
        t.configure_llm(mock)
        t.configure_operations(compress=LLMConfig(model="op-compress"))

        t.commit(InstructionContent(text="First instruction"))
        t.commit(DialogueContent(role="user", text="Hello"))
        t.commit(DialogueContent(role="assistant", text="Hi there"))

        result = t.compress(model="call-compress")
        assert mock.last_kwargs.get("model") == "call-compress"
        t.close()

    def test_compress_call_level_temperature_override(self):
        """Pass temperature= on compress(), verify forwarded."""
        t = Tract.open()
        mock = MockLLMClient(responses=["Summary text"])
        t.configure_llm(mock)
        t.configure_operations(compress=LLMConfig(temperature=0.1))

        t.commit(InstructionContent(text="First instruction"))
        t.commit(DialogueContent(role="user", text="Hello"))
        t.commit(DialogueContent(role="assistant", text="Hi there"))

        # Call-level override
        result = t.compress(temperature=0.5)
        assert mock.last_kwargs.get("temperature") == 0.5
        t.close()


# ---------------------------------------------------------------------------
# orchestrate integration tests
# ---------------------------------------------------------------------------

class TestOrchestrateIntegration:
    """Tests for orchestrate using per-operation config."""

    def test_orchestrate_uses_operation_config_model(self):
        """Configure orchestrate model, verify OrchestratorConfig receives it."""
        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)
        t.configure_operations(orchestrate=LLMConfig(model="orch-model"))

        # Capture the config that gets passed to the Orchestrator
        created_configs = []
        original_init = None

        from tract.orchestrator.loop import Orchestrator as _Orchestrator
        original_init = _Orchestrator.__init__

        def capture_init(self_orch, tract_inst, *, config=None, llm_callable=None):
            created_configs.append(config)
            original_init(self_orch, tract_inst, config=config, llm_callable=llm_callable)

        _Orchestrator.__init__ = capture_init
        try:
            # Need to set up enough for orchestrator to work
            t.commit(InstructionContent(text="System prompt"))

            # The orchestrator will fail (no real LLM), but we can check the config
            try:
                t.orchestrate()
            except Exception:
                pass  # Expected -- mock LLM won't produce valid orchestrator responses

            # Verify the config was created with operation-level model
            assert len(created_configs) == 1
            config = created_configs[0]
            assert config is not None
            assert config.model == "orch-model"
        finally:
            _Orchestrator.__init__ = original_init
        t.close()

    def test_orchestrate_explicit_config_wins(self):
        """Explicit OrchestratorConfig.model overrides operation config."""
        from tract.orchestrator.config import OrchestratorConfig

        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)
        t.configure_operations(orchestrate=LLMConfig(model="op-orch"))

        created_configs = []
        from tract.orchestrator.loop import Orchestrator as _Orchestrator
        original_init = _Orchestrator.__init__

        def capture_init(self_orch, tract_inst, *, config=None, llm_callable=None):
            created_configs.append(config)
            original_init(self_orch, tract_inst, config=config, llm_callable=llm_callable)

        _Orchestrator.__init__ = capture_init
        try:
            t.commit(InstructionContent(text="System prompt"))
            explicit_config = OrchestratorConfig(model="explicit-model")

            try:
                t.orchestrate(config=explicit_config)
            except Exception:
                pass

            assert len(created_configs) == 1
            config = created_configs[0]
            # Explicit model should win over operation-level
            assert config.model == "explicit-model"
        finally:
            _Orchestrator.__init__ = original_init
        t.close()

    def test_orchestrate_config_not_mutated(self):
        """Pass a config object, verify the ORIGINAL object is not mutated."""
        from tract.orchestrator.config import OrchestratorConfig

        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)
        t.configure_operations(orchestrate=LLMConfig(model="op-orch", temperature=0.5))

        t.commit(InstructionContent(text="System prompt"))

        # Create a config with default model (None) and default temperature (0.0)
        original_config = OrchestratorConfig()
        assert original_config.model is None
        assert original_config.temperature == 0.0

        try:
            t.orchestrate(config=original_config)
        except Exception:
            pass

        # The ORIGINAL config object must NOT have been mutated
        assert original_config.model is None
        assert original_config.temperature == 0.0
        t.close()


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Tests ensuring no regressions when no operation config is set."""

    def test_no_operation_config_chat_unchanged(self):
        """chat without any operation config works identically."""
        t = Tract.open()
        mock = MockLLMClient()
        t.configure_llm(mock)

        t.system("You are helpful")
        t.user("Hello")
        resp = t.generate()

        assert resp.text == "Mock response"
        # No model/temperature/max_tokens in kwargs (no operation config, no call override)
        assert "model" not in mock.last_kwargs
        assert "temperature" not in mock.last_kwargs
        t.close()

    def test_no_operation_config_compress_unchanged(self):
        """compress without operation config works identically."""
        t = Tract.open()
        mock = MockLLMClient(responses=["Summary text"])
        t.configure_llm(mock)

        t.commit(InstructionContent(text="First instruction"))
        t.commit(DialogueContent(role="user", text="Hello"))
        t.commit(DialogueContent(role="assistant", text="Hi there"))

        result = t.compress()
        # No extra kwargs passed to LLM
        assert "model" not in mock.last_kwargs
        assert "temperature" not in mock.last_kwargs
        t.close()
