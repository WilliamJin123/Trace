"""External SDK adapter protocol for tract.

Provides a pluggable adapter layer for converting tract's compiled messages
and tool definitions to/from framework-specific formats (Anthropic, LangChain,
etc.).

The default :class:`PassthroughAdapter` returns data as-is (OpenAI-compatible).
:class:`AnthropicAdapter` handles the known format differences between OpenAI
and Anthropic message formats.

Example::

    from tract.adapters import AnthropicAdapter, AdapterRegistry

    adapter = AnthropicAdapter()
    anthropic_msgs = adapter.wrap_messages(compiled.to_dicts())
    # Send to Anthropic API...
    tract_msgs = adapter.extract_messages(anthropic_response)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__: list[str] = [
    "AgentAdapter",
    "PassthroughAdapter",
    "AnthropicAdapter",
    "AdapterRegistry",
]


# ---------------------------------------------------------------------------
# AgentAdapter protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol for external SDK adapters.

    Adapters convert between tract's internal message/tool format
    (OpenAI-compatible by default) and framework-specific formats.
    """

    def wrap_messages(self, messages: list[dict]) -> Any:
        """Convert tract compiled messages to framework-specific format.

        Args:
            messages: List of message dicts in OpenAI format
                (``{"role": "...", "content": "..."}``).

        Returns:
            Framework-specific message representation.
        """
        ...

    def extract_messages(self, response: Any) -> list[dict]:
        """Extract messages from framework response back to tract format.

        Args:
            response: Framework-specific response object.

        Returns:
            List of message dicts in OpenAI format.
        """
        ...

    def adapt_tools(self, tools: list[dict]) -> Any:
        """Convert tract tool definitions to framework format.

        Args:
            tools: List of tool definition dicts in OpenAI function-calling format.

        Returns:
            Framework-specific tool definitions.
        """
        ...


# ---------------------------------------------------------------------------
# PassthroughAdapter -- default (OpenAI-compatible, no conversion)
# ---------------------------------------------------------------------------

class PassthroughAdapter:
    """Default adapter that passes data through unchanged.

    Useful as a base class and for any OpenAI-compatible framework.
    Messages and tools are returned as-is.
    """

    def wrap_messages(self, messages: list[dict]) -> list[dict]:
        """Return messages as-is (OpenAI format)."""
        return list(messages)

    def extract_messages(self, response: Any) -> list[dict]:
        """Extract messages from an OpenAI-style response.

        Handles both raw dicts and common response object shapes:
        - Dict with ``choices[0].message`` (OpenAI chat completion)
        - List of message dicts (pass-through)
        """
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            # OpenAI chat completion format
            choices = response.get("choices")
            if choices and isinstance(choices, list):
                msg = choices[0]
                if isinstance(msg, dict) and "message" in msg:
                    return [msg["message"]]
                return [msg]
            # Single message dict
            if "role" in response:
                return [response]
        return []

    def adapt_tools(self, tools: list[dict]) -> list[dict]:
        """Return tools as-is (OpenAI function-calling format)."""
        return list(tools)


# ---------------------------------------------------------------------------
# AnthropicAdapter -- converts OpenAI format to/from Anthropic format
# ---------------------------------------------------------------------------

class AnthropicAdapter:
    """Adapter for converting between OpenAI and Anthropic message formats.

    Handles the known format differences:

    - **System messages**: Anthropic uses a separate ``system`` parameter
      rather than a message with ``role="system"``.  :meth:`wrap_messages`
      extracts system messages and returns a tuple ``(system_text, messages)``.
    - **Content blocks**: Anthropic uses ``[{"type": "text", "text": "..."}]``
      content blocks rather than plain strings.
    - **Tool definitions**: Anthropic uses ``input_schema`` instead of
      ``parameters``, and has a top-level ``name``/``description`` (no
      wrapping ``function`` key).
    """

    def wrap_messages(
        self, messages: list[dict]
    ) -> tuple[str, list[dict]]:
        """Convert OpenAI-format messages to Anthropic format.

        Extracts system messages into a separate string.  Non-system
        messages get their content converted to Anthropic content blocks.

        Returns:
            A tuple of ``(system_text, anthropic_messages)`` where
            ``system_text`` is the concatenated system messages (or empty
            string) and ``anthropic_messages`` is the list of non-system
            messages in Anthropic content-block format.
        """
        system_parts: list[str] = []
        anthropic_messages: list[dict] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    # Already in content blocks format
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            system_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            system_parts.append(block)
                continue

            # Convert content to Anthropic content blocks
            if isinstance(content, str):
                anthropic_content = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                # Already in blocks format, pass through
                anthropic_content = content
            else:
                anthropic_content = [{"type": "text", "text": str(content)}]

            anthropic_messages.append({
                "role": role,
                "content": anthropic_content,
            })

        system_text = "\n\n".join(system_parts)
        return system_text, anthropic_messages

    def extract_messages(self, response: Any) -> list[dict]:
        """Extract messages from an Anthropic-style response.

        Handles both raw dicts and common Anthropic response shapes:
        - Dict with ``content`` list of blocks (Anthropic Messages API)
        - Dict with ``completion`` string (legacy Anthropic API)

        Returns:
            List of message dicts in OpenAI format.
        """
        if isinstance(response, list):
            # List of content blocks
            text_parts = []
            for block in response:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            if text_parts:
                return [{"role": "assistant", "content": "\n".join(text_parts)}]
            return []

        if isinstance(response, dict):
            # Anthropic Messages API format
            content = response.get("content")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                if text_parts:
                    return [{"role": response.get("role", "assistant"), "content": "\n".join(text_parts)}]
                return []

            # Legacy format
            completion = response.get("completion")
            if completion:
                return [{"role": "assistant", "content": completion}]

            # Single message passthrough
            if "role" in response and "content" in response:
                return [response]

        return []

    def adapt_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI function-calling tool defs to Anthropic format.

        OpenAI format::

            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": { ... }
                }
            }

        Anthropic format::

            {
                "name": "...",
                "description": "...",
                "input_schema": { ... }
            }
        """
        anthropic_tools: list[dict] = []
        for tool in tools:
            func = tool.get("function", tool)
            anthropic_tool = {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            }
            anthropic_tools.append(anthropic_tool)
        return anthropic_tools


# ---------------------------------------------------------------------------
# AdapterRegistry -- named adapter lookup
# ---------------------------------------------------------------------------

class AdapterRegistry:
    """Registry for named agent adapters.

    Pre-registered adapters:
    - ``"passthrough"``: :class:`PassthroughAdapter`
    - ``"anthropic"``: :class:`AnthropicAdapter`

    Example::

        registry = AdapterRegistry()
        adapter = registry.get("anthropic")
        system, msgs = adapter.wrap_messages(compiled.to_dicts())
    """

    def __init__(self) -> None:
        self._adapters: dict[str, AgentAdapter] = {
            "passthrough": PassthroughAdapter(),
            "anthropic": AnthropicAdapter(),
        }

    def register(self, name: str, adapter: AgentAdapter) -> None:
        """Register an adapter by name.

        Args:
            name: Unique name for the adapter.
            adapter: An object satisfying the :class:`AgentAdapter` protocol.

        Raises:
            TypeError: If adapter does not satisfy AgentAdapter protocol.
        """
        if not isinstance(adapter, AgentAdapter):
            raise TypeError(
                f"Adapter must satisfy AgentAdapter protocol. "
                f"Got {type(adapter).__name__} which is missing required methods."
            )
        self._adapters[name] = adapter

    def get(self, name: str) -> AgentAdapter:
        """Get an adapter by name.

        Args:
            name: The adapter name.

        Returns:
            The adapter instance.

        Raises:
            KeyError: If no adapter with that name is registered.
        """
        if name not in self._adapters:
            available = ", ".join(sorted(self._adapters.keys()))
            raise KeyError(f"Adapter '{name}' not found. Available: {available}")
        return self._adapters[name]

    def list_adapters(self) -> list[str]:
        """Return names of all registered adapters."""
        return sorted(self._adapters.keys())
