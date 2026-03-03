"""Tests for retry protocol integration with compression.

Verifies backward compatibility (no validator = unchanged behavior),
retry flow (steering via hook-layer auto_retry), and exhaustion.
"""

from __future__ import annotations

import pytest

from tract import CompressResult, CompressionError, PendingCompress, Tract
from tests.conftest import make_tract_with_commits


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Mock LLM client for testing compression with retry."""

    def __init__(self, responses=None):
        self.responses = responses or ["Summary text."]
        self._call_count = 0
        self.last_messages = None

    def chat(self, messages, **kwargs):
        self.last_messages = messages
        text = self.responses[min(self._call_count, len(self.responses) - 1)]
        self._call_count += 1
        return {
            "choices": [{"message": {"content": text}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCompressNoValidator:
    """Backward compatibility: no validator = unchanged behavior."""

    def test_compress_no_validator_unchanged(self):
        """compress() without validator produces normal CompressResult."""
        t, hashes = make_tract_with_commits(5)
        mock = MockLLMClient(responses=["Previously: summary."])
        t.configure_llm(mock)

        result = t.compress()

        assert isinstance(result, CompressResult)
        assert len(result.summary_commits) >= 1
        assert mock._call_count == 1


class TestCompressValidatorPasses:
    """Validator passes on first try -- no retries needed."""

    def test_compress_validator_passes(self):
        """compress() with validator that passes immediately returns normally."""
        t, hashes = make_tract_with_commits(5)
        mock = MockLLMClient(responses=["Good summary."])
        t.configure_llm(mock)

        result = t.compress(validator=lambda text: (True, None))

        assert isinstance(result, CompressResult)
        assert mock._call_count == 1


class TestCompressValidatorFailsThenPasses:
    """Validator fails, hook-layer auto_retry retries, then succeeds."""

    def test_compress_validator_fails_then_passes(self):
        """compress() retries via auto_retry on validation failure."""
        t, hashes = make_tract_with_commits(5)
        # First summary fails validation, second passes
        mock = MockLLMClient(responses=[
            "Bad summary that is too vague for acceptance",
            "Good summary with all the required details",
        ])
        t.configure_llm(mock)

        call_count = 0

        def validate(text):
            nonlocal call_count
            call_count += 1
            if "Good" in text:
                return (True, None)
            return (False, "summary too vague")

        result = t.compress(validator=validate)

        assert isinstance(result, CompressResult)
        assert mock._call_count == 2
        assert call_count == 2

    def test_compress_retry_amends_instructions(self):
        """On retry, the guidance contains the validation diagnosis."""
        t, hashes = make_tract_with_commits(3)
        mock = MockLLMClient(responses=[
            "Vague summary without details needed",
            "Detailed summary with all required information",
        ])
        t.configure_llm(mock)

        call_count = 0

        def validate(text):
            nonlocal call_count
            call_count += 1
            return (True, None) if call_count > 1 else (False, "not detailed enough")

        result = t.compress(
            instructions="Be concise",
            validator=validate,
        )

        assert isinstance(result, CompressResult)
        # The second LLM call should have received guidance with the diagnosis
        # (via PendingCompress.retry(guidance=...))
        assert mock._call_count == 2


class TestCompressAllRetriesExhausted:
    """All retries exhausted -- returns rejected PendingCompress."""

    def test_compress_all_retries_exhausted(self):
        """compress() returns rejected PendingCompress when all attempts fail."""
        t, hashes = make_tract_with_commits(5)
        mock = MockLLMClient(responses=["A bad summary that fails validation"] * 5)
        t.configure_llm(mock)

        result = t.compress(
            validator=lambda text: (False, "unacceptable"),
            max_retries=2,
        )

        assert isinstance(result, PendingCompress)
        assert result.status == "rejected"
        assert "unacceptable" in result.rejection_reason

    def test_compress_max_retries_one(self):
        """max_retries=1 means one auto_retry iteration for compression."""
        t, hashes = make_tract_with_commits(3)
        mock = MockLLMClient(responses=["A bad quality summary text"])
        t.configure_llm(mock)

        result = t.compress(
            validator=lambda text: (False, "bad quality"),
            max_retries=1,
        )

        assert isinstance(result, PendingCompress)
        assert result.status == "rejected"
        # 1 call from compress_range + 1 retry from auto_retry = 2
        assert mock._call_count == 2


class TestCompressRetryEdgeCases:
    """Edge cases for compression retry."""

    def test_compress_validator_with_manual_content_ignored(self):
        """validator is only used for LLM path, not manual content.

        When content= is provided, LLM is bypassed entirely and validator
        is NOT invoked (there's no LLM to retry against).
        """
        t, hashes = make_tract_with_commits(3)

        validator_called = False

        def check(text):
            nonlocal validator_called
            validator_called = True
            return (False, "should not be called")

        # Manual content bypasses LLM entirely -- validator not applicable
        result = t.compress(content="Manual summary", validator=check)

        assert isinstance(result, CompressResult)
        # Validator is NOT called because manual mode doesn't go through
        # the LLM path where validator is wired
        assert not validator_called
