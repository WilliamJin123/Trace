"""Base Pending class for the hook system.

Every hookable operation produces a Pending -- a mutable container
with methods to approve, reject, modify, or retry the planned operation.
Subclasses add operation-specific fields and methods.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tract.tract import Tract


class PendingStatus(str, Enum):
    """Status of a pending operation.

    Uses ``str, Enum`` dual inheritance for Python 3.10+ compatibility
    while keeping string comparison and serialization working.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PASSED_THROUGH = "passed_through"

    def __repr__(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


def _is_hex_hash(s: str) -> bool:
    """Check if a string looks like a commit hash (32+ hex chars)."""
    return len(s) >= 32 and all(c in "0123456789abcdef" for c in s)


def _resolve_hash(hash_str: str, tract: Any) -> str:
    """Resolve a commit hash to 'shorthash -- message' using tract storage.

    Falls back to just the short hash if lookup fails.
    """
    short = hash_str[:8]
    try:
        row = tract._commit_repo.get(hash_str)
        if row and row.message:
            return f"{short} -- {row.message}"
    except Exception:
        pass
    return short


def _format_value_for_display(value: Any, *, tract: Any = None) -> str:
    """Format a value for Rich table display."""
    if value is None:
        return "[dim]None[/dim]"
    if isinstance(value, str):
        if _is_hex_hash(value):
            return _resolve_hash(value, tract) if tract else value[:8]
        return value
    if isinstance(value, list):
        if len(value) == 0:
            return "(empty)"
        # All hashes: one per line with messages
        if all(isinstance(v, str) and _is_hex_hash(v) for v in value):
            if tract:
                return "\n".join(_resolve_hash(v, tract) for v in value)
            return ", ".join(v[:8] for v in value)
        # Single item: unwrap
        if len(value) == 1:
            return _format_value_for_display(value[0], tract=tract)
        # Multiple strings: one per line
        if all(isinstance(v, str) for v in value):
            lines = []
            for i, v in enumerate(value):
                lines.append(f"[{i}] {v}")
            return "\n".join(lines)
        # Mixed types
        return ", ".join(_format_value_for_display(v, tract=tract) for v in value)
    if isinstance(value, dict):
        if len(value) == 0:
            return "{}"
        items = [f"{k}: {_format_value_for_display(v, tract=tract)}" for k, v in value.items()]
        return "\n".join(items)
    if isinstance(value, set):
        if len(value) == 0:
            return "(empty)"
        return ", ".join(_format_value_for_display(v, tract=tract) for v in sorted(value, key=str))
    return repr(value)


@dataclass(repr=False)
class Pending:
    """Base class for all hookable pending operations.

    Fields:
        operation: Name of the hookable operation (e.g. "compress", "gc").
        pending_id: Unique identifier for this pending instance (auto-generated).
        created_at: When this pending was created (UTC).
        tract: The Tract instance that created this pending (full SDK access).
        status: Current status -- "pending", "approved", or "rejected".
        triggered_by: Optional provenance string (e.g. "trigger:auto_compress").
        rejection_reason: Human-readable reason if status is "rejected".

    Internal:
        _execute_fn: Closure set by the creating operation to finalize the work.
        _public_actions: Whitelist of method names allowed via agent dispatch.
    """

    operation: str
    tract: Tract
    pending_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: PendingStatus = PendingStatus.PENDING
    triggered_by: str | None = None
    rejection_reason: str | None = None

    # Internal -- set by the creating operation, not by users
    _execute_fn: Callable[..., Any] | None = field(default=None, repr=False)

    # Result stored by approve() for uniform retrieval
    _result: Any = field(default=None, repr=False)

    # Subclasses override this with their allowed action names.
    # Frozen by default; use register_action() for dynamic extension.
    _public_actions: frozenset[str] = field(
        default_factory=lambda: frozenset({"approve", "reject", "pass_through", "get_state"}), repr=False
    )

    # -- Status guards --------------------------------------------------

    def _require_pending(self) -> None:
        """Raise if this pending has already been resolved."""
        if self.status != PendingStatus.PENDING:
            raise RuntimeError(
                f"Cannot modify a {self.operation} pending with status "
                f"{self.status!r}. Only 'pending' items can be approved or rejected."
            )

    def register_action(self, name: str) -> None:
        """Register an additional public action for agent dispatch.

        Creates a new frozenset with the added action name. This is the
        safe way to extend the whitelist at runtime.

        Args:
            name: Method name to add to the allowed actions.

        Raises:
            ValueError: If name starts with '_'.
            AttributeError: If no method with this name exists.
        """
        if name.startswith("_"):
            raise ValueError(f"Cannot register private method {name!r}.")
        if not hasattr(self, name):
            raise AttributeError(
                f"{type(self).__name__} has no method {name!r}."
            )
        self._public_actions = self._public_actions | frozenset({name})

    # -- Core methods (subclasses should override) -----------------------

    def approve(self) -> Any:
        """Approve and execute the pending operation.

        Subclasses should override this to add operation-specific logic.
        The base implementation sets status, calls _execute_fn, and stores
        the result in ``_result`` for uniform retrieval.

        Returns:
            The result of executing the operation.

        Raises:
            RuntimeError: If status is not "pending".
            RuntimeError: If no _execute_fn has been set.
        """
        self._require_pending()
        if self._execute_fn is None:
            raise RuntimeError(
                f"Cannot approve: no execute function set. "
                f"This {type(self).__name__} was not created by a Tract operation."
            )
        self.status = PendingStatus.APPROVED
        self._result = self._execute_fn(self)
        return self._result

    def reject(self, reason: str = "") -> None:
        """Reject the pending operation.

        Subclasses should override this to add operation-specific logic.
        The base implementation sets status and stores the reason.

        Args:
            reason: Human-readable explanation for the rejection.

        Raises:
            RuntimeError: If status is not "pending".
        """
        self._require_pending()
        self.status = PendingStatus.REJECTED
        self.rejection_reason = reason

    def pass_through(self) -> None:
        """Signal that this handler is done but not making a decision.

        The next handler in the stack will fire. If no more handlers
        remain, the pending is auto-approved (nobody objected).

        Raises:
            RuntimeError: If status is not "pending".
        """
        self._require_pending()
        self.status = PendingStatus.PASSED_THROUGH

    # -- Agent interface (auto-generated from subclass methods) ----------

    def get_state(self) -> dict:
        """Return full pending state without truncation.

        Unlike to_dict() which truncates large values for initial context,
        this returns all fields at full length. Use in multi-turn flows
        to re-inspect state after mutations.

        Returns:
            A JSON-serializable dict with operation, pending_id, status,
            fields, and available_actions.
        """
        import dataclasses

        from tract.hooks.introspection import _serialize_value

        fields: dict[str, Any] = {}
        skip_fields = {
            "operation", "pending_id", "status", "tract",
            "triggered_by", "rejection_reason", "created_at",
        }
        for f in dataclasses.fields(self):
            if f.name.startswith("_"):
                continue
            if f.name in skip_fields:
                continue
            value = getattr(self, f.name)
            fields[f.name] = _serialize_value(value)

        # Include dynamic fields dict if present (for dynamic operations)
        if hasattr(self, "fields") and isinstance(getattr(self, "fields"), dict):
            for k, v in self.fields.items():
                fields[k] = _serialize_value(v)

        return {
            "operation": self.operation,
            "pending_id": self.pending_id,
            "status": str(self.status),
            "fields": fields,
            "available_actions": sorted(self._public_actions),
        }

    def to_dict(self) -> dict:
        """Serialize this Pending to a structured dict for LLM consumption.

        Returns a dict with keys: operation, pending_id, status, fields,
        available_actions. Fields are all public (non-underscore) dataclass
        fields excluding identity/status metadata.

        Returns:
            A JSON-serializable dict describing this Pending.
        """
        from tract.hooks.introspection import pending_to_dict

        return pending_to_dict(self)

    def to_tools(self) -> list[dict]:
        """Generate JSON Schema tool definitions for available actions.

        Produces a list of tool definitions compatible with OpenAI/Anthropic
        function calling format, one per method in _public_actions.

        Returns:
            List of tool definition dicts.
        """
        from tract.hooks.introspection import pending_to_tools

        return pending_to_tools(self)

    def describe_api(self) -> str:
        """Generate human/LLM-readable API description.

        Returns a markdown-formatted string listing the Pending's fields
        and available actions with their signatures and docstrings.

        Returns:
            Markdown string describing the API.
        """
        from tract.hooks.introspection import pending_describe_api

        return pending_describe_api(self)

    # -- Dispatch methods -----------------------------------------------

    def apply_decision(self, decision: dict) -> Any:
        """Apply a structured decision dict from an LLM.

        The decision dict must have an "action" key naming the method
        to call, and optionally an "args" key with a dict of arguments.

        Example::

            pending.apply_decision({"action": "approve"})
            pending.apply_decision({"action": "reject", "args": {"reason": "bad quality"}})

        Args:
            decision: Dict with "action" (str) and optional "args" (dict).

        Returns:
            Whatever the dispatched method returns.

        Raises:
            ValueError: If action is not in _public_actions or starts with '_'.
            KeyError: If "action" key is missing from decision.
        """
        action = decision["action"]
        args = decision.get("args", {})
        return self.execute_tool(action, args)

    def execute_tool(self, name: str, args: dict | None = None) -> Any:
        """Execute a named action on this pending, guarded by whitelist.

        Args:
            name: Method name to call.
            args: Keyword arguments to pass to the method.

        Returns:
            Whatever the method returns.

        Raises:
            ValueError: If name starts with '_' or is not in _public_actions.
            AttributeError: If the method does not exist.
        """
        if args is None:
            args = {}

        if name.startswith("_"):
            raise ValueError(
                f"Cannot execute private method {name!r}. "
                f"Allowed actions: {sorted(self._public_actions)}"
            )
        if name not in self._public_actions:
            raise ValueError(
                f"Action {name!r} is not in the allowed actions for "
                f"{type(self).__name__}. "
                f"Allowed: {sorted(self._public_actions)}"
            )

        method = getattr(self, name)
        return method(**args)

    # -- Display --------------------------------------------------------

    def __repr__(self):
        status = self.status.value if hasattr(self.status, 'value') else str(self.status)
        return f"<{type(self).__name__}: {self.operation}, {status}, id={self.pending_id[:8]}>"

    def pprint(self, *, compact: bool = False) -> None:
        """Pretty-print this Pending using Rich.

        Two modes:

        * ``pprint()`` — full output: header, fields table,
          operation-specific details, and available actions.
        * ``pprint(compact=True)`` — single colored line (for listings).

        Args:
            compact: If True, show a single colored line instead of full output.
        """
        import dataclasses
        import sys

        from rich.console import Console
        from rich.table import Table

        # Force UTF-8 output so LLM-generated Unicode (e.g. non-breaking
        # hyphens) doesn't crash on Windows cp1252 consoles.
        # closefd=False prevents closing stdout when the wrapper is GC'd.
        # Fall back to default Console when fileno() is unavailable (pytest).
        try:
            out = open(sys.stdout.fileno(), "w", encoding="utf-8", errors="replace", closefd=False)
            console = Console(file=out)
        except (io.UnsupportedOperation, OSError):
            console = Console()

        # Status color mapping (shared by compact and full modes)
        status_color = {
            PendingStatus.PENDING: "yellow",
            PendingStatus.APPROVED: "green",
            PendingStatus.REJECTED: "red",
            PendingStatus.PASSED_THROUGH: "cyan",
        }.get(self.status, "white")

        # -- Compact: single colored line -----------------------------------
        if compact:
            detail = self._compact_detail()
            parts = [
                f"[bold]{type(self).__name__}[/bold]",
                f"[bright_cyan]{self.pending_id[:8]}[/bright_cyan]",
                f"[bold]{self.operation}[/bold]",
                f"[{status_color}]{self.status}[/{status_color}]",
            ]
            if detail:
                parts.append(detail)
            console.print("  ".join(parts))
            return

        # -- Full mode ------------------------------------------------------

        # Header
        console.print(
            f"[bold]{type(self).__name__}[/bold]  "
            f"id=[bright_cyan]{self.pending_id}[/bright_cyan]"
        )
        console.print(
            f"  operation: [bold]{self.operation}[/bold]  "
            f"status: [{status_color}]{self.status}[/{status_color}]"
        )
        if self.triggered_by:
            console.print(f"  triggered_by: [italic bright_magenta]{self.triggered_by}[/italic bright_magenta]")
        if self.rejection_reason:
            console.print(f"  rejection_reason: [red]{self.rejection_reason}[/red]")

        # Created timestamp
        if self.created_at:
            self._print_created_at(console)

        # Fields table
        skip_fields = {
            "operation", "pending_id", "status", "tract",
            "triggered_by", "rejection_reason", "created_at",
        }
        table = Table(title="Fields", show_header=True, header_style="bold")
        table.add_column("Field", style="cyan")
        table.add_column("Value")

        for f in dataclasses.fields(self):
            if f.name.startswith("_"):
                continue
            if f.name in skip_fields:
                continue
            value = getattr(self, f.name)
            table.add_row(f.name, _format_value_for_display(value, tract=self.tract))

        console.print(table)

        # Subclass-specific details (token ratio, branch info, etc.)
        self._pprint_details(console)

        # Available actions
        actions = sorted(self._public_actions)
        console.print(f"  [bold]Available actions:[/bold] {', '.join(actions)}")

    def _compact_detail(self) -> str:
        """Return a short detail string for compact pprint mode.

        Subclasses override this to provide operation-specific summaries.
        Returns empty string by default.
        """
        return ""

    def _print_created_at(self, console) -> None:
        """Print the created_at timestamp with relative time."""
        now = datetime.now(timezone.utc)
        delta = now - self.created_at
        seconds = int(delta.total_seconds())
        if seconds < 60:
            rel = f"{seconds}s ago"
        elif seconds < 3600:
            rel = f"{seconds // 60}m ago"
        elif seconds < 86400:
            rel = f"{seconds // 3600}h ago"
        else:
            rel = self.created_at.strftime("%Y-%m-%d %H:%M UTC")
        console.print(f"  created: [dim]{rel}[/dim]")

    def _pprint_details(self, console) -> None:
        """Hook for subclasses to add operation-specific display details.

        Called by pprint() after the header and before available actions.
        Override in subclasses to show concise, operation-specific info
        (e.g. token ratio, branch names, conflict count).

        Args:
            console: The Rich Console instance to print to.
        """
        pass

    def consult(
        self,
        instruction: str,
        *,
        system_prompt: str | None = None,
        max_turns: int = 1,
    ) -> dict:
        """Ask an LLM to decide on this pending operation.

        The agent equivalent of :meth:`review`. Serializes the pending
        state via :meth:`to_dict`, generates tool schemas via
        :meth:`to_tools`, sends them to the configured LLM client, and
        dispatches the response via :meth:`apply_decision`.

        Loops up to *max_turns* times or until the pending is resolved
        (approved/rejected). Each turn is one LLM call that returns a
        tool call, which is dispatched and fed back as context for the
        next turn.

        Args:
            instruction: What the agent should do (e.g. "Approve this
                compression" or "Review the summaries for quality").
            system_prompt: Optional system prompt override. Defaults to
                a generic context-management agent prompt.
            max_turns: Maximum LLM round-trips (default 1). Use >1 for
                multi-step flows (e.g. edit then approve).

        Returns:
            The last decision dict ``{"action": ..., "args": ...}``
            dispatched, or ``{"action": "no_tool_call", "args": {}}``
            if the LLM responded with text instead of a tool call.

        Raises:
            RuntimeError: If no LLM client is configured on the Tract.
        """
        import json as _json

        if not self.tract._has_llm_client():
            raise RuntimeError(
                "Cannot consult: no LLM client configured. "
                "Pass api_key= to Tract.open() or call configure_llm()."
            )

        client = self.tract._llm_client
        tools = self.to_tools()

        default_system = (
            "You are a context management agent. You receive the state of "
            "a pending operation and must decide what to do using the "
            "provided tools. Always call exactly one tool per response."
        )

        messages: list[dict] = [
            {"role": "system", "content": system_prompt or default_system},
            {
                "role": "user",
                "content": (
                    f"{instruction}\n\n"
                    f"Current state:\n{_json.dumps(self.to_dict(), indent=2)}"
                ),
            },
        ]

        last_decision: dict = {"action": "no_tool_call", "args": {}}

        for _turn in range(max_turns):
            if self.status != PendingStatus.PENDING:
                break

            raw = client.chat(messages, tools=tools)
            choice = raw["choices"][0]["message"]
            tc_list = choice.get("tool_calls", [])

            if not tc_list:
                # LLM responded with text, not a tool call
                break

            tc = tc_list[0]
            last_decision = {
                "action": tc["function"]["name"],
                "args": _json.loads(tc["function"].get("arguments", "{}")),
            }

            result = self.apply_decision(last_decision)

            # Feed result back for multi-turn flows
            if self.status == PendingStatus.PENDING and _turn < max_turns - 1:
                messages.append(choice)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": f"Action applied. Result: {result}",
                })

        return last_decision

    def review(self, *, prompt_fn: Callable[[str], str] | None = None) -> None:
        """Interactive review flow: pprint then prompt for approve/reject.

        Convenience method for CLI usage. Displays the Pending state
        and waits for user input. Subclasses can override for
        operation-specific flows.

        Args:
            prompt_fn: Optional callback for reading user input.
                Receives a prompt string, returns the user's response.
                Defaults to :func:`input` for standard CLI usage.
                Pass a custom function for testing or non-TTY contexts.
        """
        _prompt = prompt_fn or input
        self.pprint()
        # Interactive prompt
        while self.status == PendingStatus.PENDING:
            choice = _prompt("\n[approve/reject/skip] > ").strip().lower()
            if choice == "approve":
                self.approve()
                print(f"Approved {self.operation}.")
            elif choice == "reject":
                reason = _prompt("Reason: ").strip()
                self.reject(reason)
                print(f"Rejected {self.operation}.")
            elif choice == "skip":
                print("Skipped (still pending).")
                break
            else:
                print("Enter 'approve', 'reject', or 'skip'.")
