"""Default context compiler for Trace.

Converts a commit chain into LLM-ready structured messages.
Handles edit resolution, priority filtering, time-travel compilation,
type-to-role mapping, and same-role message aggregation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from tract.models.annotations import DEFAULT_TYPE_PRIORITIES, Priority
from tract.models.content import BUILTIN_TYPE_HINTS
from tract.protocols import CompiledContext, Message

if TYPE_CHECKING:
    from tract.protocols import TokenCounter
    from tract.storage.repositories import (
        AnnotationRepository,
        BlobRepository,
        CommitRepository,
    )
    from tract.storage.schema import CommitRow

logger = logging.getLogger(__name__)


def _normalize_dt(dt: datetime) -> datetime:
    """Strip timezone info for comparison (SQLite stores naive datetimes)."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


class DefaultContextCompiler:
    """Default implementation of the ContextCompiler protocol.

    Walks the commit chain from head to root, resolves edits, filters
    by priority, maps content types to LLM roles, and produces a
    structured message list.

    Note on token counts:
    - Per-commit token_count in the database reflects raw content tokens.
    - CompiledContext.token_count reflects the formatted output including
      message overhead (per-message tokens, response primer, etc.).
    """

    def __init__(
        self,
        commit_repo: CommitRepository,
        blob_repo: BlobRepository,
        annotation_repo: AnnotationRepository,
        token_counter: TokenCounter,
        type_to_role_map: dict[str, str] | None = None,
    ) -> None:
        self._commit_repo = commit_repo
        self._blob_repo = blob_repo
        self._annotation_repo = annotation_repo
        self._token_counter = token_counter
        self._type_to_role_override = type_to_role_map or {}

    def compile(
        self,
        tract_id: str,
        head_hash: str,
        *,
        as_of: datetime | None = None,
        up_to: str | None = None,
        include_edit_annotations: bool = False,
    ) -> CompiledContext:
        """Compile commits into structured messages for LLM consumption.

        Args:
            tract_id: Tract identifier (used for annotation lookups).
            head_hash: Hash of the HEAD commit to start walking from.
            as_of: Only include commits created at or before this datetime.
            up_to: Only include commits up to and including this commit hash.
            include_edit_annotations: If True, append '[edited]' marker to
                content that was replaced by an edit.

        Returns:
            CompiledContext with messages, token count, and metadata.

        Raises:
            ValueError: If both as_of and up_to are provided.
        """
        if as_of is not None and up_to is not None:
            raise ValueError("Cannot specify both as_of and up_to; use one or the other.")

        # Step 1: Walk commit chain (head -> root), then reverse to root -> head
        commits = self._walk_chain(head_hash, as_of=as_of, up_to=up_to)

        if not commits:
            return CompiledContext(messages=[], token_count=0, commit_count=0, token_source="")

        # Step 2: Build edit resolution map
        edit_map = self._build_edit_map(commits, as_of=as_of)

        # Step 3: Build priority map
        priority_map = self._build_priority_map(commits, as_of=as_of)

        # Step 4: Build effective commit list
        effective_commits = self._build_effective_commits(commits, edit_map, priority_map)

        # Step 5-6: Map to messages
        messages = self._build_messages(effective_commits, edit_map, include_edit_annotations)

        # Step 7: Aggregate same-role consecutive messages
        messages = self._aggregate_messages(messages)

        # Step 8: Count tokens on compiled output
        messages_dicts = [
            {"role": m.role, "content": m.content}
            if m.name is None
            else {"role": m.role, "content": m.content, "name": m.name}
            for m in messages
        ]
        token_count = self._token_counter.count_messages(messages_dicts)

        encoding_name = getattr(self._token_counter, "encoding_name", "unknown")
        token_source = f"tiktoken:{encoding_name}" if encoding_name != "unknown" else ""

        return CompiledContext(
            messages=messages,
            token_count=token_count,
            commit_count=len(effective_commits),
            token_source=token_source,
        )

    def _walk_chain(
        self,
        head_hash: str,
        *,
        as_of: datetime | None = None,
        up_to: str | None = None,
    ) -> list[CommitRow]:
        """Walk parent chain from head to root, apply time filters, return root-to-head order."""
        ancestors = self._commit_repo.get_ancestors(head_hash)
        # ancestors is head-first (newest first), reverse to root-first
        commits = list(reversed(ancestors))

        # Apply up_to filter: include only up to and including the specified hash
        if up_to is not None:
            filtered = []
            for c in commits:
                filtered.append(c)
                if c.commit_hash == up_to:
                    break
            commits = filtered

        # Apply as_of filter: include only commits at or before the datetime
        if as_of is not None:
            as_of_naive = _normalize_dt(as_of)
            commits = [c for c in commits if _normalize_dt(c.created_at) <= as_of_naive]

        return commits

    def _build_edit_map(
        self,
        commits: list[CommitRow],
        *,
        as_of: datetime | None = None,
    ) -> dict[str, CommitRow]:
        """Build map of reply_to -> latest edit commit.

        If multiple edits target the same commit, the latest one (by created_at) wins.
        """
        from tract.models.commit import CommitOperation

        edit_map: dict[str, CommitRow] = {}
        for c in commits:
            if c.operation == CommitOperation.EDIT and c.reply_to is not None:
                # Only include edits within the as_of boundary
                if as_of is not None and _normalize_dt(c.created_at) > _normalize_dt(as_of):
                    continue
                existing = edit_map.get(c.reply_to)
                if existing is None or c.created_at > existing.created_at:
                    edit_map[c.reply_to] = c
        return edit_map

    def _build_priority_map(
        self,
        commits: list[CommitRow],
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Priority]:
        """Build map of commit_hash -> effective priority.

        Uses annotations if available, otherwise falls back to
        DEFAULT_TYPE_PRIORITIES based on content_type.
        """
        commit_hashes = [c.commit_hash for c in commits]
        annotations = self._annotation_repo.batch_get_latest(commit_hashes)

        priority_map: dict[str, Priority] = {}
        for c in commits:
            annotation = annotations.get(c.commit_hash)
            if annotation is not None:
                # If as_of is set, only consider annotations within that boundary
                if as_of is not None and _normalize_dt(annotation.created_at) > _normalize_dt(as_of):
                    annotation = None

            if annotation is not None:
                priority_map[c.commit_hash] = annotation.priority
            else:
                priority_map[c.commit_hash] = DEFAULT_TYPE_PRIORITIES.get(
                    c.content_type, Priority.NORMAL
                )

        return priority_map

    def _build_effective_commits(
        self,
        commits: list[CommitRow],
        edit_map: dict[str, CommitRow],
        priority_map: dict[str, Priority],
    ) -> list[CommitRow]:
        """Build the effective commit list after edit resolution and priority filtering."""
        from tract.models.commit import CommitOperation

        effective: list[CommitRow] = []
        for c in commits:
            # Skip EDIT commits (they are substitutions, not standalone messages)
            if c.operation == CommitOperation.EDIT:
                continue
            # Skip commits with SKIP priority
            if priority_map.get(c.commit_hash) == Priority.SKIP:
                continue
            # Include the commit (possibly with substituted content via edit_map)
            effective.append(c)

        return effective

    def build_message_for_commit(self, commit_row: CommitRow) -> Message:
        """Build a single Message from a commit's blob content.

        Loads the blob, parses JSON, maps content_type to role,
        extracts text. This is the single-commit equivalent of the
        loop body in _build_messages().

        Args:
            commit_row: The source commit row (after edit resolution).

        Returns:
            Message with role, content, and optional name.
        """
        blob = self._blob_repo.get(commit_row.content_hash)
        if blob is None:
            logger.warning("Blob not found for commit %s", commit_row.commit_hash)
            return Message(role="system", content="[missing content]")

        content_data = json.loads(blob.payload_json)
        content_type = content_data.get("content_type", "unknown")
        role = self._map_role(content_type, content_data)
        text = self._extract_message_text(content_type, content_data)
        name = content_data.get("name") if content_type == "dialogue" else None
        return Message(role=role, content=text, name=name)

    def _build_messages(
        self,
        effective_commits: list[CommitRow],
        edit_map: dict[str, CommitRow],
        include_edit_annotations: bool,
    ) -> list[Message]:
        """Convert effective commits to Message objects."""
        messages: list[Message] = []

        for c in effective_commits:
            # Determine which commit's content to use
            source_commit = edit_map.get(c.commit_hash, c)

            msg = self.build_message_for_commit(source_commit)

            # Add edit annotation if requested
            if include_edit_annotations and c.commit_hash in edit_map:
                msg = Message(role=msg.role, content=msg.content + " [edited]", name=msg.name)

            messages.append(msg)

        return messages

    def _map_role(self, content_type: str, content_data: dict) -> str:
        """Map content type to LLM message role.

        Priority order:
        1. type_to_role_map override
        2. DialogueContent: use the role field from content itself
        3. ToolIOContent: always "tool"
        4. BUILTIN_TYPE_HINTS default_role
        5. Fallback: "assistant"
        """
        # Check override map first
        if content_type in self._type_to_role_override:
            return self._type_to_role_override[content_type]

        # Special case: DialogueContent uses its own role field
        if content_type == "dialogue":
            return content_data.get("role", "user")

        # Special case: ToolIOContent always maps to "tool"
        if content_type == "tool_io":
            return "tool"

        # Use builtin type hints
        hints = BUILTIN_TYPE_HINTS.get(content_type)
        if hints is not None:
            return hints.default_role

        return "assistant"

    def _extract_message_text(self, content_type: str, content_data: dict) -> str:
        """Extract the display text from parsed content data."""
        if content_type == "tool_io":
            tool_name = content_data.get("tool_name", "unknown")
            direction = content_data.get("direction", "call")
            payload = content_data.get("payload", {})
            status = content_data.get("status")
            header = f"Tool {direction}: {tool_name}"
            if status:
                header += f" ({status})"
            return f"{header}\n{json.dumps(payload, indent=2)}"

        if content_type == "freeform":
            return json.dumps(content_data.get("payload", {}), indent=2)

        # For types with 'text' field
        if "text" in content_data:
            return content_data["text"]

        # ArtifactContent uses 'content' field
        if "content" in content_data:
            return content_data["content"]

        return json.dumps(content_data)

    def _aggregate_messages(self, messages: list[Message]) -> list[Message]:
        """Aggregate consecutive same-role messages by concatenating content.

        Does NOT aggregate across role boundaries.
        """
        if not messages:
            return messages

        aggregated: list[Message] = []
        current = messages[0]

        for msg in messages[1:]:
            if msg.role == current.role:
                # Concatenate with double newline
                new_content = current.content + "\n\n" + msg.content
                # Use name from first message in the group
                current = Message(role=current.role, content=new_content, name=current.name)
            else:
                aggregated.append(current)
                current = msg

        aggregated.append(current)
        return aggregated
