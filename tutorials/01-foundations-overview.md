# Phase 1 Foundations: Architecture Overview

## What is Trace?

Trace is a **git-like version control system for LLM context windows**. It is a Python library -- an SDK -- that gives programs a structured, append-only history of every piece of content that flows into (and out of) a large language model conversation.

### The Problem

When you call an LLM API, you send a flat list of messages. That list *is* the context window. As conversations grow, as agents loop, as tool results pile up, managing that list becomes a serious engineering problem:

1. **No history.** Once you drop a message from the context window to save tokens, it is gone. There is no record that it ever existed, no way to restore it later.
2. **No structure.** A list of `{"role": "user", "content": "..."}` dicts carries no metadata -- no timestamps, no content types, no annotations about what is important and what can be compressed.
3. **No operations.** You cannot "edit" a previous message. You cannot "pin" a system prompt so it is never evicted. You cannot "skip" a stale tool result. You rebuild the list from scratch every time.
4. **No deduplication.** If the same system prompt appears in 1,000 conversations, it is stored 1,000 times.
5. **No auditability.** There is no log of what the model saw at each turn, making debugging agent behavior painful.

### The Solution

Trace models the context window as a **commit chain** -- a linked list of immutable snapshots, exactly like git commits. Each commit wraps a typed content block (system instruction, user message, tool result, reasoning trace, etc.) with metadata. A **compiler** walks the chain and produces the flat message list that the LLM API expects.

This gives you:

- **Full history**: every version of the context is recoverable.
- **Typed content**: 7 built-in content types with behavioral hints for compilation and future compression.
- **Operations**: APPEND new content, or EDIT an existing commit (producing a replacement without rewriting history).
- **Annotations**: Mark any commit as SKIP (exclude from compilation), NORMAL, or PINNED (always include).
- **Content-addressable storage**: identical content is stored once (blob deduplication via SHA-256).
- **Token awareness**: every commit is token-counted at creation time; the compiler reports total token usage for the compiled output.
- **Time-travel**: compile the context as it existed at any point in time or up to any commit.

---

## The Layered Architecture

Trace is organized into four layers, each building on the one below. Understanding this layering is the key to understanding the entire codebase.

```
  +--------------------------------------------------+
  |                     Repo                          |  <-- Public API (facade)
  |           repo.commit(), repo.compile()           |
  +--------------------------------------------------+
                         |
  +--------------------------------------------------+
  |                   Engine                          |  <-- Business logic
  |   CommitEngine, DefaultContextCompiler,           |
  |   content_hash(), TiktokenCounter                 |
  +--------------------------------------------------+
                         |
  +--------------------------------------------------+
  |                   Storage                         |  <-- Persistence
  |   SqliteCommitRepository, SqliteBlobRepository,   |
  |   SqliteRefRepository, SqliteAnnotationRepository |
  +--------------------------------------------------+
                         |
  +--------------------------------------------------+
  |                   Models                          |  <-- Data definitions
  |   ContentPayload, CommitInfo, PriorityAnnotation, |
  |   CommitRow, BlobRow, RefRow, AnnotationRow       |
  +--------------------------------------------------+
```

### Layer 1: Models (`src/tract/models/`)

Pure data definitions. No I/O, no side effects. This layer defines:

- **Content types** (`content.py`): 7 Pydantic models for different kinds of LLM content (InstructionContent, DialogueContent, ToolIOContent, ReasoningContent, ArtifactContent, OutputContent, FreeformContent), plus a discriminated union (ContentPayload) and a validation function.
- **Commit model** (`commit.py`): `CommitInfo` -- the SDK-facing data transfer object for commit data. `CommitOperation` enum (APPEND, EDIT).
- **Annotation model** (`annotations.py`): `Priority` enum (SKIP, NORMAL, PINNED), `PriorityAnnotation` Pydantic model, and `DEFAULT_TYPE_PRIORITIES` mapping.
- **Config** (`config.py`): `RepoConfig`, `TokenBudgetConfig`, `BudgetAction` -- per-repo settings.
- **Compiled output** (`compiled.py`): `CompileOptions` Pydantic model (time-travel params, etc.).

The ORM schema (`storage/schema.py`) also lives conceptually at this layer -- it defines the SQLAlchemy table models (BlobRow, CommitRow, RefRow, AnnotationRow, TraceMetaRow).

### Layer 2: Storage (`src/tract/storage/`)

Persistence logic. This layer talks to SQLite via SQLAlchemy 2.0. It contains:

- **Abstract repositories** (`repositories.py`): ABCs defining the contract for commit, blob, ref, and annotation storage. No SQLAlchemy imports -- pure abstract interfaces.
- **SQLite implementations** (`sqlite.py`): Concrete implementations using `select()` + `session.execute()`. These are the only classes that touch the database.
- **Engine/session factory** (`engine.py`): Creates SQLAlchemy engines with SQLite performance pragmas (WAL mode, foreign keys, etc.), session factories, and `init_db()` for table creation + schema versioning.
- **Schema** (`schema.py`): SQLAlchemy ORM models for all 5 tables.
- **Custom type** (`types.py`): `PydanticJSON` TypeDecorator for transparent Pydantic-to-JSON column bridging.

### Layer 3: Engine (`src/tract/engine/`)

Business logic. This is where the interesting algorithms live:

- **Hashing** (`hashing.py`): Deterministic SHA-256 hashing for content blobs and commits. Canonical JSON serialization ensures key order does not affect hashes.
- **Token counting** (`tokens.py`): `TiktokenCounter` (production, wrapping OpenAI's tiktoken library) and `NullTokenCounter` (testing stub). Both satisfy the `TokenCounter` protocol.
- **Commit engine** (`commit.py`): `CommitEngine` orchestrates the entire commit workflow: serialize content, compute hashes, count tokens, store blob (with dedup), enforce token budget, validate edit constraints, save commit row, update HEAD, auto-create annotations.
- **Context compiler** (`compiler.py`): `DefaultContextCompiler` walks the commit chain, resolves edits, filters by priority/annotations, maps content types to LLM roles, aggregates consecutive same-role messages, and produces a `CompiledContext`.

### Layer 4: Repo (`src/tract/repo.py`)

The public facade. A single class (`Repo`) that ties everything together. Users never need to touch storage, engine, or schema classes directly. Key methods:

- `Repo.open(path)` -- create or open a repo (in-memory by default)
- `repo.commit(content)` -- create a new commit
- `repo.compile()` -- compile context into LLM-ready messages
- `repo.annotate(hash, priority)` -- set priority on a commit
- `repo.log()` -- walk commit history
- `repo.batch()` -- context manager for atomic multi-commit
- `repo.register_content_type(name, model)` -- extend the type system

---

## Data Flow: From API Call to SQLite and Back

Let us trace a complete round-trip through the system. This is the single most important thing to understand.

### Writing: `repo.commit(InstructionContent(text="You are helpful."))`

```
User code
   |
   v
Repo.commit(content)                          # src/tract/repo.py:244
   |
   |-- If content is a dict, validate_content()  # src/tract/models/content.py:120
   |   routes through discriminated union or
   |   custom registry
   |
   v
CommitEngine.create_commit(content)           # src/tract/engine/commit.py:92
   |
   |-- 1. content.model_dump(mode="json")     # Serialize Pydantic -> dict
   |-- 2. compute_content_hash(dict)          # SHA-256 of canonical JSON
   |-- 3. extract_text_from_content(content)  # Pull text field
   |--    token_counter.count_text(text)      # Count tokens via tiktoken
   |-- 4. BlobRow(content_hash, payload_json, byte_size, token_count)
   |      blob_repo.save_if_absent(blob)      # Dedup: skip if hash exists
   |-- 5. ref_repo.get_head(repo_id)          # Get current HEAD -> parent_hash
   |-- 6. Check token budget (warn/reject/callback)
   |-- 7. compute_commit_hash(content_hash, parent_hash, ...)
   |-- 8. Validate edit constraints (if EDIT operation)
   |-- 9. CommitRow(...) -> commit_repo.save()
   |-- 10. ref_repo.update_head(repo_id, commit_hash)
   |-- 11. Auto-create PINNED annotation (for InstructionContent)
   |
   v
Repo.commit() calls session.commit()         # Flush to SQLite
   |
   v
Clear compile cache                          # Invalidate stale results
   |
   v
Return CommitInfo                             # SDK-facing model
```

### Reading: `repo.compile()`

```
User code
   |
   v
Repo.compile()                                # src/tract/repo.py:285
   |
   |-- Check cache: is current HEAD already compiled?
   |   If yes, return cached CompiledContext.
   |
   v
DefaultContextCompiler.compile(repo_id, head) # src/tract/engine/compiler.py:63
   |
   |-- 1. _walk_chain(head_hash)               # Walk parent pointers to root
   |      commit_repo.get_ancestors(head)       # Returns newest-first
   |      Reverse to root-first order
   |      Apply up_to or as_of filters
   |
   |-- 2. _build_edit_map(commits)              # Map: target_hash -> latest edit
   |      For each EDIT commit with reply_to,
   |      record as replacement (latest wins)
   |
   |-- 3. _build_priority_map(commits)          # Map: commit_hash -> Priority
   |      annotation_repo.batch_get_latest()    # Single query, no N+1
   |      Fall back to DEFAULT_TYPE_PRIORITIES
   |
   |-- 4. _build_effective_commits(...)         # Filter out EDITs and SKIPs
   |
   |-- 5. _build_messages(...)                  # Load blobs, extract text,
   |      For each effective commit:             # map type to role, apply edits
   |        source = edit_map.get(c) or c
   |        blob = blob_repo.get(source.content_hash)
   |        role = _map_role(content_type, data)
   |        text = _extract_message_text(...)
   |        -> Message(role, content, name?)
   |
   |-- 6. _aggregate_messages()                 # Merge consecutive same-role
   |
   |-- 7. token_counter.count_messages(msgs)    # Count compiled output tokens
   |
   v
Return CompiledContext(messages, token_count, commit_count, token_source)
```

---

## Key Abstractions and Why They Exist

### Content-Addressable Blob Storage

Like git, Trace separates **content** from **commits**. The content (the actual text/payload) is stored in a `blobs` table keyed by SHA-256 hash. The commit references the blob by hash. This means:

- **Deduplication**: If you commit the same system prompt 100 times, the blob is stored once. Only the commit rows (which are small) multiply.
- **Integrity**: The hash *is* the content's identity. Corruption is detectable.
- **Cheap branching** (future): Branches can share blobs without copying data.

This is implemented in `SqliteBlobRepository.save_if_absent()` (`src/tract/storage/sqlite.py:41`), which checks for existing content before inserting.

### Immutable Commit Chain

Commits are immutable once created. You never modify a commit. To "edit" content, you create a new EDIT commit that points at the original via `reply_to`. The compiler resolves edits at compile time. This preserves full history while allowing content updates.

The chain is formed by `parent_hash` pointers: each commit points to its predecessor. Walking `parent_hash` from HEAD to null gives you the complete history.

### The Protocol Pattern

Trace uses Python's `typing.Protocol` for its pluggable interfaces:

- `TokenCounter`: Any object with `count_text()` and `count_messages()` methods.
- `ContextCompiler`: Any object with a `compile()` method matching the expected signature.
- `TokenUsageExtractor`: Defined for future use (Phase 3).

These are defined in `src/tract/protocols.py`. The `@runtime_checkable` decorator means you can use `isinstance(obj, TokenCounter)` at runtime.

**Why protocols instead of ABCs?** Protocols use structural subtyping ("duck typing with type checking"). You do not need to inherit from anything. Any class with the right methods satisfies the protocol. This makes testing trivial -- you can write a 3-line stub:

```python
class FixedCounter:
    def count_text(self, text: str) -> int:
        return 42
    def count_messages(self, messages: list[dict]) -> int:
        return 100
```

And it just works as a `TokenCounter`. See `tests/test_repo.py:471` for this exact pattern.

### The Repository Pattern

Storage is abstracted behind repository interfaces (ABCs in `src/tract/storage/repositories.py`). The SQLite implementations live in `src/tract/storage/sqlite.py`. This separation means:

- **Testability**: Tests use the real SQLite implementations against in-memory databases, which is fast and faithful. But you *could* swap in a different backend.
- **Clean boundaries**: The engine layer depends on abstract repository interfaces, not on SQLAlchemy directly.
- **Single Responsibility**: Each repository handles one table/concern.

### The Facade Pattern (Repo)

The `Repo` class (`src/tract/repo.py`) is a classic facade. It hides the complexity of creating engines, sessions, repositories, and wiring them together. Users see:

```python
with Repo.open() as repo:
    repo.commit(InstructionContent(text="You are helpful."))
    result = repo.compile()
```

Behind the scenes, `Repo.open()` creates a SQLAlchemy engine, initializes the database, creates four repository instances, a token counter, a commit engine, and a context compiler. That is ~15 object instantiations hidden behind one method call.

---

## The Component Relationship Diagram

```
                              +-------------------+
                              |      Repo         |
                              | (public facade)   |
                              +--------+----------+
                                       |
              +------------------------+----------------------------+
              |                        |                            |
    +---------v--------+    +----------v---------+    +-------------v-----------+
    |   CommitEngine   |    |  DefaultContext-    |    |     RepoConfig          |
    |                  |    |  Compiler           |    |  TokenBudgetConfig      |
    +----+----+----+---+    +---+----+----+------+    +-------------------------+
         |    |    |            |    |    |
         |    |    |            |    |    +-- TokenCounter (protocol)
         |    |    |            |    +------- BlobRepository (ABC)
         |    |    |            +------------ CommitRepository (ABC)
         |    |    |            +------------ AnnotationRepository (ABC)
         |    |    |
         |    |    +-- TokenCounter (protocol)
         |    +------- BlobRepository (ABC)
         +------------ CommitRepository (ABC)
         +------------ RefRepository (ABC)
         +------------ AnnotationRepository (ABC)

    Repository ABCs           SQLite Implementations
    (repositories.py)         (sqlite.py)
         |                         |
         |    +--------------------+
         |    |
    +----v----v---+    +------------------+
    | ORM Schema  |    |  Engine/Session  |
    | (schema.py) |    |  (engine.py)     |
    +------+------+    +--------+---------+
           |                    |
           +--------------------+
                    |
            +-------v--------+
            |    SQLite DB   |
            | (in-memory or  |
            |  file-backed)  |
            +----------------+
```

### Dependency Direction

Dependencies flow **downward**:

- `Repo` depends on `CommitEngine`, `DefaultContextCompiler`, and all repositories.
- `CommitEngine` and `DefaultContextCompiler` depend on repository ABCs and `TokenCounter` protocol.
- Repositories depend on the ORM schema.
- The ORM schema depends on domain model enums (`CommitOperation`, `Priority`).

Nothing in the lower layers knows about the layers above. The engine does not import `Repo`. The storage does not import the engine. This is deliberate -- it keeps the architecture testable at each layer independently.

---

## File Inventory

Here is every source file and its role:

| File | Lines | Purpose |
|------|-------|---------|
| `src/tract/__init__.py` | 91 | Package root; re-exports all public types |
| `src/tract/_version.py` | 1 | Version string (`0.1.0`) |
| `src/tract/exceptions.py` | 61 | Exception hierarchy: `TraceError` base + 5 specific exceptions |
| `src/tract/protocols.py` | 94 | Protocol definitions + frozen dataclasses (`Message`, `CompiledContext`, `TokenUsage`) |
| `src/tract/repo.py` | 456 | `Repo` facade class -- the entire public API |
| `src/tract/models/__init__.py` | 47 | Re-exports from model submodules |
| `src/tract/models/content.py` | 219 | 7 content type Pydantic models + discriminated union + validation + type hints |
| `src/tract/models/commit.py` | 41 | `CommitInfo` DTO + `CommitOperation` enum |
| `src/tract/models/annotations.py` | 45 | `Priority` enum + `PriorityAnnotation` model + default priority map |
| `src/tract/models/config.py` | 42 | `RepoConfig` + `TokenBudgetConfig` + `BudgetAction` |
| `src/tract/models/compiled.py` | 40 | `CompileOptions` model (time-travel params) |
| `src/tract/storage/__init__.py` | 23 | Re-exports storage components |
| `src/tract/storage/schema.py` | 138 | SQLAlchemy ORM: 5 tables (blobs, commits, refs, annotations, _trace_meta) |
| `src/tract/storage/engine.py` | 66 | SQLAlchemy engine creation, session factory, `init_db()` |
| `src/tract/storage/repositories.py` | 123 | Abstract repository interfaces (ABCs) |
| `src/tract/storage/sqlite.py` | 216 | Concrete SQLite repository implementations |
| `src/tract/storage/types.py` | 47 | `PydanticJSON` TypeDecorator |
| `src/tract/engine/__init__.py` | 5 | Engine package marker |
| `src/tract/engine/hashing.py` | 86 | `canonical_json()`, `content_hash()`, `commit_hash()` |
| `src/tract/engine/tokens.py` | 95 | `TiktokenCounter` + `NullTokenCounter` |
| `src/tract/engine/commit.py` | 309 | `CommitEngine` -- the commit orchestrator |
| `src/tract/engine/compiler.py` | 352 | `DefaultContextCompiler` -- commit chain to messages |

And the test files:

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared fixtures: in-memory engine, session, repository instances |
| `tests/strategies.py` | Hypothesis strategies for all 7 content types |
| `tests/test_models/test_content.py` | Content type validation, discriminated union, custom registry, round-trip |
| `tests/test_storage/test_schema.py` | ORM schema: table creation, round-trips, FK constraints, indexes |
| `tests/test_storage/test_repositories.py` | Repository CRUD, dedup, ancestor chain, refs, annotations, batch queries |
| `tests/test_engine/test_hashing.py` | Canonical JSON, content hash, commit hash, property-based tests |
| `tests/test_engine/test_tokens.py` | TiktokenCounter, NullTokenCounter, protocol conformance |
| `tests/test_engine/test_commit.py` | CommitEngine: create, edit, budget, dedup, annotations |
| `tests/test_engine/test_compiler.py` | Compiler: role mapping, edit resolution, priority filtering, time-travel, aggregation |
| `tests/test_repo.py` | Integration tests through public Repo API (all 5 success criteria) |

---

## Design Principles

Several principles run through the entire codebase:

1. **Immutability**: Commits and blobs are never modified after creation. Annotations are append-only (new rows, never updates). This makes the system inherently safe for concurrent reads and simplifies reasoning about state.

2. **Content-addressability**: Content is identified by its SHA-256 hash. Same content = same hash = stored once. This is the same insight that makes git efficient.

3. **Separation of concerns**: Each layer has a clear responsibility. Models define shapes. Storage handles persistence. Engine implements algorithms. Repo provides the user API.

4. **Protocol-based pluggability**: Core interfaces (TokenCounter, ContextCompiler) use Python protocols, not inheritance hierarchies. This enables easy testing and future extension without modifying existing code.

5. **Compute at compile time**: Token counts on commits are raw content counts. The compiled output token count (which includes per-message overhead, response primer, etc.) is computed at compile time, not stored. This avoids stale cached values.

6. **Explicit over implicit**: Time-travel uses two separate parameters (`as_of: datetime` and `up_to: str`) rather than a combined "revision" concept. This is more verbose but less ambiguous.

---

## What Comes Next

Phase 1 (Foundations) provides the complete linear history model. The subsequent phases build on this base:

- **Phase 2: Linear History** -- Additional linear operations, more advanced time-travel.
- **Phase 3: Branching** -- Git-like branching and merging of context.
- **Phase 4: Compression** -- Smart context compression using priority annotations and token budgets.
- **Phase 5: Multi-Agent** -- Shared context across multiple agents.

Each phase adds new capabilities without modifying the core commit/blob/compile pipeline established here. That is the payoff of the layered architecture -- the foundation is stable enough to build on.

---

*Next: [01a - Data Models and Storage](01a-data-models-and-storage.md) -- deep dive into the data layer.*
