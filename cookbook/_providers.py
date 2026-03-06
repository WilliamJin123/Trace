"""Cookbook LLM provider configuration.

Centralizes API keys, base URLs, and model IDs so any cookbook example
can swap providers by changing a single import line:

    from _providers import cerebras as llm   # <- change this
    from _providers import groq as llm       # <- to this

Then use ``llm.api_key``, ``llm.base_url``, ``llm.large``, ``llm.small``
throughout the file.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


@dataclass(frozen=True)
class Provider:
    """Frozen bag of credentials + model aliases for one provider."""

    api_key: str
    base_url: str
    large: str
    small: str


cerebras = Provider(
    api_key=os.environ.get("CEREBRAS_API_KEY", ""),
    base_url=os.environ.get("CEREBRAS_BASE_URL", ""),
    large="gpt-oss-120b",
    small="llama3.1-8b",
)

groq = Provider(
    api_key=os.environ.get("GROQ_API_KEY", ""),
    base_url=os.environ.get("GROQ_BASE_URL", ""),
    large="meta-llama/llama-4-scout-17b-16e-instruct",
    small="qwen/qwen3-32b",
)
