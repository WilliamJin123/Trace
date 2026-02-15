"""Compile cache manager for Tract.

Owns the LRU snapshot cache and all incremental patching logic.
Extracted from tract.py to keep the facade class focused on orchestration.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

from tract.engine.compiler import DefaultContextCompiler
from tract.models.annotations import Priority
from tract.protocols import CompiledContext, CompileSnapshot, Message, TokenCounter

if TYPE_CHECKING:
    from tract.models.commit import CommitInfo
    from tract.protocols import ContextCompiler
    from tract.storage.repositories import CommitRepository
    from tract.storage.schema import CommitRow

logger = logging.getLogger(__name__)


class CacheManager:
    """LRU compile-snapshot cache with incremental patching.

    Manages an OrderedDict-based LRU cache of CompileSnapshot objects.
    Supports O(1) incremental extension for APPEND commits, in-memory
    patching for EDIT commits, and annotation-aware invalidation.
    """

    def __init__(
        self,
        *,
        maxsize: int,
        compiler: ContextCompiler,
        token_counter: TokenCounter,
        commit_repo: CommitRepository,
    ) -> None:
        self._cache: OrderedDict[str, CompileSnapshot] = OrderedDict()
        self._maxsize = maxsize
        self._compiler = compiler
        self._token_counter = token_counter
        self._commit_repo = commit_repo

    # ------------------------------------------------------------------
    # LRU primitives
    # ------------------------------------------------------------------

    def get(self, head_hash: str) -> CompileSnapshot | None:
        """Get snapshot from LRU cache.  Returns None on miss."""
        if head_hash not in self._cache:
            logger.debug("Cache miss: %s", head_hash[:12])
            return None
        self._cache.move_to_end(head_hash)
        logger.debug("Cache hit: %s", head_hash[:12])
        return self._cache[head_hash]

    def put(self, head_hash: str, snapshot: CompileSnapshot) -> None:
        """Store snapshot in LRU cache, evicting LRU entry if at capacity."""
        if head_hash in self._cache:
            self._cache.move_to_end(head_hash)
        self._cache[head_hash] = snapshot
        while len(self._cache) > self._maxsize:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.debug("Cache evict: %s", evicted_key[:12])
        logger.debug("Cache put: %s (size=%d)", head_hash[:12], len(self._cache))

    def clear(self) -> None:
        """Clear all cached snapshots."""
        size = len(self._cache)
        self._cache.clear()
        if size > 0:
            logger.debug("Cache cleared (%d entries)", size)

    # ------------------------------------------------------------------
    # Snapshot <-> CompiledContext conversion
    # ------------------------------------------------------------------

    @staticmethod
    def to_compiled(snapshot: CompileSnapshot) -> CompiledContext:
        """Convert a CompileSnapshot to a CompiledContext for return.

        Uses copy-on-output for generation_configs to prevent user mutations
        of the returned CompiledContext from corrupting the cached snapshot.
        """
        return CompiledContext(
            messages=list(snapshot.messages),
            token_count=snapshot.token_count,
            commit_count=snapshot.commit_count,
            token_source=snapshot.token_source,
            generation_configs=[dict(c) for c in snapshot.generation_configs],
            commit_hashes=list(snapshot.commit_hashes),
        )

    def build_snapshot(
        self, head_hash: str, result: CompiledContext
    ) -> CompileSnapshot | None:
        """Build a CompileSnapshot from a full compile result.

        Returns None if the compiler is not a DefaultContextCompiler
        (custom compilers bypass incremental cache).
        """
        if not isinstance(self._compiler, DefaultContextCompiler):
            return None
        return CompileSnapshot(
            head_hash=head_hash,
            messages=tuple(result.messages),
            commit_count=result.commit_count,
            token_count=result.token_count,
            token_source=result.token_source,
            generation_configs=tuple(dict(c) for c in result.generation_configs),
            commit_hashes=tuple(result.commit_hashes),
        )

    # ------------------------------------------------------------------
    # Incremental patching
    # ------------------------------------------------------------------

    def _token_source(self) -> str:
        """Return the token_source string for tiktoken-based counts."""
        from tract.engine.tokens import TiktokenCounter

        if isinstance(self._token_counter, TiktokenCounter):
            return f"tiktoken:{self._token_counter._encoding_name}"
        return ""

    def _count_messages_from_tuples(self, messages: list[Message] | tuple[Message, ...]) -> int:
        """Count tokens for a sequence of Message objects."""
        messages_dicts = [
            {"role": m.role, "content": m.content}
            if m.name is None
            else {"role": m.role, "content": m.content, "name": m.name}
            for m in messages
        ]
        return self._token_counter.count_messages(messages_dicts)

    @property
    def uses_default_compiler(self) -> bool:
        """Whether the compiler supports incremental caching."""
        return isinstance(self._compiler, DefaultContextCompiler)

    def extend_for_append(
        self, commit_info: CommitInfo, parent_snapshot: CompileSnapshot
    ) -> None:
        """Incrementally extend a cached snapshot for an APPEND commit.

        Builds the message for the new commit, appends it (no aggregation),
        and recounts tokens.  The parent snapshot stays in the LRU cache
        under its own HEAD (useful for future checkout back).
        """
        commit_row = self._commit_repo.get(commit_info.commit_hash)
        if commit_row is None:
            return

        assert isinstance(self._compiler, DefaultContextCompiler)
        new_message = self._compiler.build_message_for_commit(commit_row)
        new_config = dict(commit_row.generation_config_json or {})

        new_messages = parent_snapshot.messages + (new_message,)
        new_commit_hashes = parent_snapshot.commit_hashes + (commit_info.commit_hash,)

        new_token_count = self._count_messages_from_tuples(new_messages)

        self.put(
            commit_info.commit_hash,
            CompileSnapshot(
                head_hash=commit_info.commit_hash,
                messages=new_messages,
                commit_count=parent_snapshot.commit_count + 1,
                token_count=new_token_count,
                token_source=self._token_source(),
                generation_configs=parent_snapshot.generation_configs + (new_config,),
                commit_hashes=new_commit_hashes,
            ),
        )

    def patch_for_edit(
        self,
        parent_snapshot: CompileSnapshot,
        new_head_hash: str,
        edit_row: CommitRow,
    ) -> CompileSnapshot | None:
        """Patch a cached snapshot for an EDIT commit in-memory.

        Finds the message corresponding to the edited target (via response_to),
        replaces it with the new message, and recounts tokens.

        Returns None if patching is not possible (missing commit_hashes, target
        not found), signaling caller to fall back to full recompile on next
        compile().
        """
        if not parent_snapshot.commit_hashes:
            return None

        target_hash = edit_row.response_to
        if target_hash is None:
            return None

        # Find position of the target commit in the snapshot
        try:
            target_idx = list(parent_snapshot.commit_hashes).index(target_hash)
        except ValueError:
            return None  # Target not in snapshot

        assert isinstance(self._compiler, DefaultContextCompiler)
        new_message = self._compiler.build_message_for_commit(edit_row)

        # Replace message at target position
        new_messages = list(parent_snapshot.messages)
        new_messages[target_idx] = new_message

        # Handle generation_config: edit-inherits-original rule
        new_configs = list(parent_snapshot.generation_configs)
        if edit_row.generation_config_json is not None:
            new_configs[target_idx] = dict(edit_row.generation_config_json)  # copy-on-input
        # else: keep original config at target_idx (edit-inherits-original)

        new_token_count = self._count_messages_from_tuples(new_messages)

        return CompileSnapshot(
            head_hash=new_head_hash,
            messages=tuple(new_messages),
            commit_count=parent_snapshot.commit_count,  # Same count (EDIT replaces, doesn't add)
            token_count=new_token_count,
            token_source=self._token_source(),
            generation_configs=tuple(new_configs),
            commit_hashes=parent_snapshot.commit_hashes,  # Same positions
        )

    def patch_for_annotate(
        self,
        snapshot: CompileSnapshot,
        target_hash: str,
        new_priority: Priority,
    ) -> CompileSnapshot | None:
        """Patch a cached snapshot for an annotation change.

        SKIP: remove the target's message from the snapshot.
        NORMAL/PINNED on already-included commit: no change needed.
        NORMAL/PINNED on previously-SKIP commit: return None (full recompile).
        """
        if not snapshot.commit_hashes:
            return None

        # Find target position
        target_idx = None
        for i, ch in enumerate(snapshot.commit_hashes):
            if ch == target_hash:
                target_idx = i
                break

        if new_priority == Priority.SKIP:
            if target_idx is None:
                return snapshot  # Already not in snapshot

            # Remove message, config, and hash at target position
            new_messages = list(snapshot.messages)
            new_configs = list(snapshot.generation_configs)
            new_hashes = list(snapshot.commit_hashes)
            del new_messages[target_idx]
            del new_configs[target_idx]
            del new_hashes[target_idx]

            new_token_count = self._count_messages_from_tuples(new_messages)

            return CompileSnapshot(
                head_hash=snapshot.head_hash,
                messages=tuple(new_messages),
                commit_count=snapshot.commit_count - 1,
                token_count=new_token_count,
                token_source=self._token_source(),
                generation_configs=tuple(new_configs),
                commit_hashes=tuple(new_hashes),
            )
        else:
            # NORMAL or PINNED
            if target_idx is not None:
                return snapshot  # Already included, no change
            else:
                return None  # Was skipped, need full recompile (don't have message content)
