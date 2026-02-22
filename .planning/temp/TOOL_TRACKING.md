# Tool Tracking Plan

## Background

LLM API calls accept a `tools` parameter (list of JSON tool schemas) that gets
injected into the model's context window alongside the system prompt. These tool
definitions consume tokens, affect model behavior, and are critical provenance
data ("what tools were available when this response was generated?").

Currently tract tracks messages and generation configs per-commit, but has no
way to record which tools were passed to the LLM.

### Design Decisions

1. **Tools are NOT messages.** They were never part of the conversation -- they
   are a separate API parameter. We do NOT inject them as synthetic system
   messages into the commit chain.
2. **Track the `tools` parameter as-is.** Store the raw JSON tool schemas
   exactly as passed to the API. Round-trip fidelity: what you stored is what
   you get back at compile time.
3. **Two-layer storage: definitions + per-commit references.** Tool schemas are
   verbose (dozens of lines each). Store each unique schema once
   (content-hashed), and link commits to their active tool set via lightweight
   ID references.
4. **Content hash for identity, name as metadata.** Two schemas with the same
   content hash are the same tool definition. The `name` field is human-readable
   metadata, not an identity key. This correctly handles version evolution (same
   name, different schema = different definition).
5. **PINNED by default at the provenance level.** Tool definitions are analogous
   to system prompts -- persistent, top-of-context, and essential for
   reproducibility. They should survive compression.
6. **Compile output: separate `tools` field.** `CompiledContext` gets a `tools`
   list alongside `messages`. The `to_openai()` and `to_anthropic()` methods
   route tools to the correct API parameter, never into the message array.

---

## Schema Changes (schema version 6 -> 7)

### New Table: `tool_definitions`

Stores each unique tool schema exactly once, keyed by content hash.

```python
class ToolSchemaRow(Base):
    """Content-addressed storage for tool JSON schemas."""

    __tablename__ = "tool_definitions"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

- `content_hash`: SHA-256 of the canonical JSON representation of the full tool
  schema (name + description + parameters). This is the identity key.
- `name`: The tool name (e.g. `"get_weather"`). Human-readable, indexed for
  lookups, but NOT the primary key (same name can have multiple versions).
- `schema_json`: The complete tool schema dict as passed to the API. For OpenAI
  format: `{"type": "function", "function": {"name": ..., "description": ...,
  "parameters": ...}}`. For Anthropic format: `{"name": ..., "description": ...,
  "input_schema": ...}`. We store whatever the user gave us.
- `created_at`: When this definition was first stored.

### New Table: `commit_tools`

Junction table linking commits to their active tool definitions.

```python
class CommitToolRow(Base):
    """Associates a commit with the tool definitions active at that point."""

    __tablename__ = "commit_tools"

    commit_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("commits.commit_hash"),
        primary_key=True,
    )
    tool_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tool_definitions.content_hash"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_commit_tools_commit", "commit_hash"),
    )
```

- `commit_hash + tool_hash`: Composite PK (a commit can have many tools, a tool
  can be referenced by many commits).
- `position`: Preserves tool ordering (order in the `tools` list matters for
  some providers).

---

## Implementation Tasks

### Task 1: Schema & Storage Layer

**Files modified:**
- `src/tract/storage/schema.py` -- add `ToolSchemaRow`, `CommitToolRow`
- `src/tract/storage/repositories.py` -- add `ToolSchemaRepository` ABC
- `src/tract/storage/sqlite.py` -- add `SqliteToolSchemaRepository`
- `src/tract/storage/engine.py` -- bump schema version 6 -> 7, migration

**1a. Add ToolSchemaRow and CommitToolRow to schema.py**

Add both ORM classes as shown in the schema section above.

**1b. Add ToolSchemaRepository ABC to repositories.py**

```python
class ToolSchemaRepository(ABC):
    """Repository for tool definition schemas."""

    @abstractmethod
    def store(self, content_hash: str, name: str, schema: dict,
              created_at: datetime) -> ToolSchemaRow:
        """Store a tool schema (idempotent -- skips if hash exists)."""
        ...

    @abstractmethod
    def get(self, content_hash: str) -> ToolSchemaRow | None:
        """Get a tool schema by content hash."""
        ...

    @abstractmethod
    def get_by_name(self, name: str) -> Sequence[ToolSchemaRow]:
        """Get all versions of a tool by name, ordered by created_at."""
        ...

    @abstractmethod
    def get_for_commit(self, commit_hash: str) -> Sequence[ToolSchemaRow]:
        """Get all tool schemas linked to a commit, ordered by position."""
        ...

    @abstractmethod
    def link_to_commit(self, commit_hash: str, tool_hash: str,
                       position: int) -> None:
        """Link a tool schema to a commit at a given position."""
        ...

    @abstractmethod
    def get_commit_tool_hashes(self, commit_hash: str) -> Sequence[str]:
        """Get tool content hashes for a commit, ordered by position."""
        ...
```

**1c. Implement SqliteToolSchemaRepository in sqlite.py**

Concrete implementation using SQLAlchemy session. `store()` is idempotent
(checks existence by hash first). `get_for_commit()` joins through
`CommitToolRow` ordered by position.

**1d. Bump schema version to 7 in engine.py**

Add migration path from v6 -> v7: create `tool_definitions` and `commit_tools`
tables. New databases start at v7.

---

### Task 2: Hashing Utility

**Files modified:**
- `src/tract/models/tools.py` (NEW)

Create a small utility module for tool schema hashing:

```python
"""Tool schema models and utilities for Trace."""

from __future__ import annotations

import hashlib
import json


def hash_tool_schema(schema: dict) -> str:
    """Compute SHA-256 content hash of a tool schema.

    Canonicalizes by sorting keys and using separators without spaces.
    This ensures the same logical schema always produces the same hash
    regardless of key ordering in the source dict.

    Args:
        schema: The full tool schema dict (name, description, parameters/input_schema).

    Returns:
        64-char hex SHA-256 digest.
    """
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

This is the same pattern used for content hashing in the blob store.

---

### Task 3: Tract Facade Wiring

**Files modified:**
- `src/tract/tract.py`
- `src/tract/protocols.py`

**3a. Add `tools` field to CompiledContext**

```python
@dataclass(frozen=True)
class CompiledContext:
    messages: list[Message] = field(default_factory=list)
    token_count: int = 0
    commit_count: int = 0
    token_source: str = ""
    generation_configs: list[LLMConfig | None] = field(default_factory=list)
    commit_hashes: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)  # <-- NEW
```

The `tools` field contains the deduplicated, ordered list of tool schemas that
were active across all commits in the compiled context. This is the union of
all per-commit tool sets, preserving the latest ordering.

**3b. Update `to_openai()` to include tools**

```python
def to_openai(self) -> dict[str, object]:
    """Convert to OpenAI chat completion format.

    Returns dict with "messages" and optionally "tools".
    """
    result: dict[str, object] = {"messages": self.to_dicts()}
    if self.tools:
        result["tools"] = list(self.tools)
    return result
```

Note: this changes the return type from `list[dict]` to `dict[str, object]`.
This is a **breaking change** that needs careful migration (see Task 5).

**3c. Update `to_anthropic()` to include tools**

```python
def to_anthropic(self) -> dict[str, object]:
    """Convert to Anthropic API format.

    Returns dict with "system", "messages", and optionally "tools".
    """
    # ... existing system/messages extraction ...
    result = {
        "system": "\n\n".join(system_parts) if system_parts else None,
        "messages": messages,
    }
    if self.tools:
        result["tools"] = list(self.tools)
    return result
```

**3d. Add `tools` parameter to `commit()`**

```python
def commit(
    self,
    content: BaseModel | dict,
    *,
    operation: CommitOperation = CommitOperation.APPEND,
    message: str | None = None,
    response_to: str | None = None,
    metadata: dict | None = None,
    generation_config: dict | None = None,
    tools: list[dict] | None = None,  # <-- NEW
) -> CommitInfo:
```

When `tools` is provided:
1. For each tool schema in the list, compute its content hash via
   `hash_tool_schema()`.
2. Store each unique schema via `tool_schema_repo.store()` (idempotent).
3. Link each schema to the new commit via `tool_schema_repo.link_to_commit()`.

When `tools` is None, no tool links are created for that commit (the commit had
no tools, or the caller didn't track them).

**3e. Add `tools` parameter to `chat()` and `generate()`**

Thread `tools` through to the underlying commit. Also, when `generate()` calls
the LLM, if tools are active, pass them in the API call. This requires:

- `generate()` accepts `tools: list[dict] | None = None`
- When calling the LLM client, pass tools alongside messages
- The assistant commit created by `generate()` gets the same tool set linked

**3f. Compile: gather tools from commits**

After compiling messages, gather the active tool set. Strategy:

- Walk the effective commits in the compiled context.
- For each commit that has linked tools, collect them.
- Use the **last commit's tool set** as the active tools (most recent state
  wins, similar to how the latest system prompt would override an earlier one).
- If no commits have tools, `CompiledContext.tools` is empty.

Alternative: union of all tool sets across all commits. This is more complete
for provenance but might include tools that were removed mid-session.

**Decision: use the last commit's tool set.** This represents "what tools are
currently active" at the point of compilation. Historical tool sets are still
queryable via the per-commit links.

---

### Task 4: Convenience Methods

**Files modified:**
- `src/tract/tract.py`

**4a. `Tract.set_tools(tools: list[dict]) -> None`**

Sets the active tool set for subsequent commits. Stores internally on the Tract
instance. When `commit()` is called without an explicit `tools=` param, the
active tool set is used automatically.

```python
def set_tools(self, tools: list[dict] | None) -> None:
    """Set the active tool definitions for subsequent commits.

    Args:
        tools: List of tool schema dicts, or None to clear tools.
    """
    self._active_tools = tools
```

This avoids the user having to pass `tools=` on every commit call.

**4b. `Tract.get_tools() -> list[dict]`**

Returns the currently active tool set.

**4c. `Tract.get_commit_tools(commit_hash: str) -> list[dict]`**

Returns the tool schemas that were linked to a specific commit. Useful for
provenance queries.

---

### Task 5: Breaking Change Migration for `to_openai()`

The current `to_openai()` returns `list[dict[str, str]]`. Adding tools changes
it to return `dict[str, object]` with `"messages"` and `"tools"` keys. This is
a breaking change for existing users who do:

```python
messages = compiled.to_openai()
client.chat.completions.create(messages=messages, ...)
```

**Options:**

A. **Break it now** -- change `to_openai()` return type. Existing code breaks
   but the new shape is more correct (you should be passing `**compiled.to_openai()`).

B. **Keep old behavior, add new method** -- `to_openai()` continues returning
   messages only. Add `to_openai_params()` that returns the full dict with tools.

C. **Conditional** -- `to_openai()` returns `list` when no tools, `dict` when
   tools are present. Messy, do not recommend.

**Recommendation: Option B.** Keep `to_openai()` backward-compatible. Add
`to_openai_params()` and `to_anthropic_params()` that return full API-ready
dicts including tools. This avoids a breaking change while providing the
complete output. Document `to_openai()` as "messages only" and the new methods
as "full API params."

```python
def to_openai_params(self) -> dict[str, object]:
    """Full OpenAI API params dict with messages and tools."""
    params: dict[str, object] = {"messages": self.to_dicts()}
    if self.tools:
        params["tools"] = list(self.tools)
    return params

def to_anthropic_params(self) -> dict[str, object]:
    """Full Anthropic API params dict with system, messages, and tools."""
    result = self.to_anthropic()  # existing: {system, messages}
    if self.tools:
        result["tools"] = list(self.tools)
    return result
```

---

### Task 6: Cache Integration

**Files modified:**
- `src/tract/engine/cache.py`
- `src/tract/protocols.py` (CompileSnapshot)

**6a. Add `tool_hashes` to CompileSnapshot**

```python
@dataclass(frozen=True)
class CompileSnapshot:
    # ... existing fields ...
    tool_hashes: tuple[str, ...] = ()  # content hashes of active tools
```

The snapshot tracks which tool hashes are active at the cached HEAD. When
extending for an APPEND, if the new commit has tools, the snapshot's tool_hashes
are replaced. When converting snapshot -> CompiledContext, resolve tool_hashes
to full schemas via the tool_schema_repo.

**6b. Update CacheManager**

- `extend_for_append()`: if the new commit has tool links, update
  `tool_hashes`.
- `to_compiled()`: resolve `tool_hashes` to full tool schemas for the
  `CompiledContext.tools` field.

---

### Task 7: Tests

**Files modified:**
- `tests/test_tool_tracking.py` (NEW)

**Integration tests:**

```
TestToolTracking:
    test_commit_with_tools          -- tools linked to commit, retrievable
    test_commit_without_tools       -- no tools, no links
    test_tool_deduplication         -- same schema stored once, two commits reference it
    test_tool_versioning            -- same name, different schema = different hash
    test_compile_returns_tools      -- CompiledContext.tools has active tools
    test_compile_no_tools           -- CompiledContext.tools is empty when no tools
    test_compile_latest_tools_win   -- last commit's tools are the active set
    test_set_tools_auto_links       -- set_tools() auto-links on subsequent commits
    test_set_tools_clear            -- set_tools(None) clears
    test_get_commit_tools           -- provenance query by commit hash
    test_to_openai_params_includes_tools
    test_to_anthropic_params_includes_tools
    test_to_openai_backward_compat  -- to_openai() still returns list[dict]
    test_chat_with_tools            -- tools threaded through chat()
    test_generate_with_tools        -- tools threaded through generate()
```

**Unit tests:**

```
TestToolSchemaHashing:
    test_deterministic_hash         -- same schema, same hash
    test_key_order_independent      -- {"a":1,"b":2} == {"b":2,"a":1}
    test_different_schema_different_hash

TestSqliteToolSchemaRepository:
    test_store_and_get
    test_store_idempotent           -- storing same hash twice is no-op
    test_get_by_name
    test_get_for_commit
    test_link_to_commit
```

---

## Success Criteria

1. `tract.commit(..., tools=[...])` stores tool schemas (deduplicated by content
   hash) and links them to the commit.
2. `tract.set_tools([...])` sets a persistent tool set that auto-links to
   subsequent commits.
3. `tract.get_commit_tools(hash)` returns the exact tool schemas for a given
   commit (provenance).
4. `CompiledContext.tools` contains the active tool set at compile time (last
   commit's tools).
5. `to_openai_params()` returns `{"messages": [...], "tools": [...]}`.
6. `to_anthropic_params()` returns `{"system": ..., "messages": [...], "tools":
   [...]}`.
7. `to_openai()` backward-compatible -- still returns `list[dict]`.
8. Tool schemas are content-hashed: same schema across commits stored once.
9. Schema version bumped to 7 with migration from v6.
10. All existing tests pass with no regressions.

---

## Open Questions / Future Work

- **Tool-aware token counting.** Tools consume tokens. Should `compile()` count
  tool tokens in `token_count`? Probably yes, but requires knowing the
  provider's internal rendering format (TypeScript for OpenAI, unknown for
  Anthropic). Defer to a future phase.
- **Tool set diffing.** "What tools were added/removed between these two
  commits?" Could build on the per-commit links. Future convenience method.
- **Compression interaction.** When compressing, tool links should be preserved
  on the summary commit. Needs thought on whether the summary inherits the
  source commits' tools.
- **PINNED priority.** Tool definitions themselves are not commits, so they
  can't be annotated with Priority.PINNED directly. The "pinned" behavior is
  implicit: tools are stored separately and never subject to compression. They
  survive by design.
