# Phase 1 Deep Dive: Repo API and Design Patterns

The `Repo` class is the single public entry point for Trace. Everything a user needs is accessible through this facade. This tutorial examines the Repo API in detail, then pulls back to discuss the design patterns and architectural decisions that make the system testable, extensible, and correct.

---

## Table of Contents

1. [The Repo Facade](#the-repo-facade)
2. [Construction: open() vs from_components()](#construction-open-vs-from_components)
3. [The commit() Method](#the-commit-method)
4. [The compile() Method and Caching](#the-compile-method-and-caching)
5. [Annotations and History](#annotations-and-history)
6. [The batch() Context Manager](#the-batch-context-manager)
7. [Custom Content Types](#custom-content-types)
8. [Time-Travel: as_of vs up_to](#time-travel-as_of-vs-up_to)
9. [The Protocol Pattern](#the-protocol-pattern)
10. [Error Handling Philosophy](#error-handling-philosophy)
11. [Resource Management](#resource-management)
12. [Test Walkthrough: test_repo.py](#test-walkthrough)
13. [Reusable Patterns](#reusable-patterns)

---

## The Repo Facade

**File:** `src/tract/repo.py` (456 lines)

The Facade pattern hides a complex subsystem behind a simple interface. Trace has four repositories, a commit engine, a context compiler, a token counter, an SQLAlchemy engine, a session, and configuration -- at minimum 10 objects that need to be created and wired together. The `Repo` class wraps all of this:

```python
# What users write:
with Repo.open() as repo:
    repo.commit(InstructionContent(text="You are helpful."))
    repo.commit(DialogueContent(role="user", text="Hi"))
    result = repo.compile()
    print(result.messages)

# What happens internally: ~15 object instantiations, database initialization,
# session management, commit engine creation, compiler creation, ref checks...
```

The facade's value is **hiding irrelevant complexity**. A user who wants to commit content and compile a context should not need to understand SQLAlchemy sessions, blob repositories, or commit hash computation.

### What Repo Hides

Looking at the `__init__` signature reveals all the internal wiring:

```python
# src/tract/repo.py:61-89

def __init__(
    self,
    *,
    engine: Engine | None,
    session: Session,
    commit_engine: CommitEngine,
    compiler: ContextCompiler,
    repo_id: str,
    config: RepoConfig,
    commit_repo: SqliteCommitRepository,
    blob_repo: SqliteBlobRepository,
    ref_repo: SqliteRefRepository,
    annotation_repo: SqliteAnnotationRepository,
    token_counter: TokenCounter,
) -> None:
```

Eleven parameters, all keyword-only. Users never call `__init__` directly -- they use `Repo.open()` or `Repo.from_components()`.

### Internal State

```python
self._custom_type_registry: dict[str, type[BaseModel]] = {}
self._compile_cache: dict[str, CompiledContext] = {}
self._closed = False
```

Three pieces of mutable state:
1. **Custom type registry**: Per-repo mapping of content type names to Pydantic models.
2. **Compile cache**: Keyed by HEAD hash, stores compiled output for cache hits.
3. **Closed flag**: Prevents double-close errors.

---

## Construction: open() vs from_components()

### Repo.open() -- The Standard Path

```python
# src/tract/repo.py:92-173

@classmethod
def open(
    cls,
    path: str = ":memory:",
    *,
    repo_id: str | None = None,
    config: RepoConfig | None = None,
    tokenizer: TokenCounter | None = None,
    compiler: ContextCompiler | None = None,
) -> Repo:
```

`Repo.open()` is a classmethod factory that handles the full initialization sequence:

1. **Generate repo_id** if not provided: `uuid.uuid4().hex` produces a 32-character hex string.
2. **Create default config** if not provided: `RepoConfig(db_path=path)`.
3. **Create SQLAlchemy engine** with SQLite performance pragmas.
4. **Initialize database**: Create all tables, set schema version.
5. **Create session** via session factory.
6. **Create all four repositories**: Each takes the shared session.
7. **Create token counter**: Use the provided tokenizer or default to `TiktokenCounter`.
8. **Create commit engine**: Wire it to all repositories and the token counter.
9. **Create context compiler**: Wire it to repositories and the token counter.
10. **Check for existing HEAD**: If the repo already has commits (reopening a file-backed DB), HEAD exists.

**Why is `path` a positional argument defaulting to `":memory:"`?** The most common use case is in-memory (for development, testing, and short-lived agents). File-backed persistence is opt-in:

```python
# In-memory (default):
repo = Repo.open()

# File-backed:
repo = Repo.open("/path/to/context.db")

# With options:
repo = Repo.open(":memory:", repo_id="my-agent", config=custom_config)
```

**Pluggable components**: Both `tokenizer` and `compiler` are optional. If you provide a custom tokenizer, it is used for all token counting (both in CommitEngine and DefaultContextCompiler). If you provide a custom compiler, it replaces DefaultContextCompiler entirely.

This is demonstrated in `tests/test_repo.py:412-438`:

```python
def test_custom_compiler(self):
    class FixedCompiler:
        def compile(self, repo_id, head_hash, *, as_of=None, up_to=None,
                    include_edit_annotations=False) -> CompiledContext:
            return CompiledContext(
                messages=[Message(role="system", content="custom-compiled")],
                token_count=99, commit_count=1, token_source="custom",
            )

    with Repo.open(compiler=FixedCompiler()) as r:
        r.commit(InstructionContent(text="anything"))
        result = r.compile()
        assert result.messages[0].content == "custom-compiled"
        assert result.token_count == 99
```

### Repo.from_components() -- The DI Path

```python
# src/tract/repo.py:175-219

@classmethod
def from_components(
    cls,
    *,
    engine: Engine | None = None,
    session: Session,
    commit_repo: SqliteCommitRepository,
    blob_repo: SqliteBlobRepository,
    ref_repo: SqliteRefRepository,
    annotation_repo: SqliteAnnotationRepository,
    token_counter: TokenCounter,
    compiler: ContextCompiler,
    repo_id: str,
    config: RepoConfig | None = None,
) -> Repo:
```

`from_components()` skips all the automatic creation. You provide pre-built components, and the Repo just wires them together. This exists for two reasons:

1. **Testing**: Tests can inject mock or stub implementations.
2. **Dependency Injection**: Applications that manage their own SQLAlchemy sessions (e.g., sharing a session with other ORM operations) can inject them.

Tested in `tests/test_repo.py:116-160`:

```python
def test_from_components_uses_injected_deps(self):
    engine = create_trace_engine(":memory:")
    init_db(engine)
    session = create_session_factory(engine)()

    commit_repo = SqliteCommitRepository(session)
    blob_repo = SqliteBlobRepository(session)
    ref_repo = SqliteRefRepository(session)
    annotation_repo = SqliteAnnotationRepository(session)
    counter = TiktokenCounter()
    compiler = DefaultContextCompiler(
        commit_repo=commit_repo, blob_repo=blob_repo,
        annotation_repo=annotation_repo, token_counter=counter,
    )

    r = Repo.from_components(
        engine=engine, session=session,
        commit_repo=commit_repo, blob_repo=blob_repo,
        ref_repo=ref_repo, annotation_repo=annotation_repo,
        token_counter=counter, compiler=compiler, repo_id="injected",
    )

    c = r.commit(InstructionContent(text="DI test"))
    assert c.commit_hash is not None
    result = r.compile()
    assert len(result.messages) == 1
    r.close()
```

**Why two classmethods instead of overloaded constructors?** Python does not support constructor overloading. Classmethods provide named, self-documenting alternatives. The names `open` and `from_components` clearly communicate intent: one opens a database, the other assembles from parts.

---

## The commit() Method

```python
# src/tract/repo.py:244-283

def commit(
    self,
    content: BaseModel | dict,
    *,
    operation: CommitOperation = CommitOperation.APPEND,
    message: str | None = None,
    reply_to: str | None = None,
    metadata: dict | None = None,
) -> CommitInfo:
```

The commit method is the primary write interface. It accepts content as either a Pydantic model or a raw dict.

### Dict Auto-Validation

```python
if isinstance(content, dict):
    content = validate_content(content, custom_registry=self._custom_type_registry)
```

When content is a dict, it goes through the validation pipeline (custom registry first, then built-in discriminated union). This means users can write:

```python
repo.commit({"content_type": "instruction", "text": "From dict"})
```

And it is validated just as thoroughly as:

```python
repo.commit(InstructionContent(text="From model"))
```

Tested in `tests/test_repo.py:309-312`:

```python
def test_content_from_dict(self, repo):
    repo.commit({"content_type": "instruction", "text": "From dict"})
    result = repo.compile()
    assert "From dict" in result.messages[0].content
```

### The Three Post-Commit Steps

After the commit engine creates the commit:

```python
info = self._commit_engine.create_commit(content=content, ...)

# 1. Persist to database
self._session.commit()

# 2. Invalidate compile cache
self._compile_cache.clear()

# 3. Return CommitInfo
return info
```

1. **Session commit**: The engine uses `flush()` internally (sending SQL to the DB). The Repo calls `session.commit()` to finalize the transaction. This is the boundary between "in-flight changes" and "persisted state."
2. **Cache invalidation**: Any cached compile results are now stale because HEAD changed.
3. **Return**: The user gets a `CommitInfo` with all commit data.

---

## The compile() Method and Caching

```python
# src/tract/repo.py:285-322

def compile(
    self,
    *,
    as_of: datetime | None = None,
    up_to: str | None = None,
    include_edit_annotations: bool = False,
) -> CompiledContext:
    current_head = self.head
    if current_head is None:
        return CompiledContext(messages=[], token_count=0, commit_count=0, token_source="")

    # Cache hit (only for unfiltered queries)
    if as_of is None and up_to is None and current_head in self._compile_cache:
        return self._compile_cache[current_head]

    result = self._compiler.compile(
        self._repo_id, current_head,
        as_of=as_of, up_to=up_to, include_edit_annotations=include_edit_annotations,
    )

    # Cache unfiltered results
    if as_of is None and up_to is None:
        self._compile_cache[current_head] = result

    return result
```

### The Compile Cache

The cache is a `dict[str, CompiledContext]` keyed by the HEAD commit hash. The caching strategy:

**Cache hits**: Only for **unfiltered** queries (no `as_of`, no `up_to`). Filtered queries produce different results for different parameters, so caching them would require a complex multi-key cache with unclear eviction semantics.

**Cache invalidation**: The cache is cleared entirely on two events:
1. `repo.commit()` -- HEAD changed, all cached results are stale.
2. `repo.annotate()` -- A priority changed, which affects compilation output.

**Why clear the entire cache, not just the stale entry?** The cache is keyed by HEAD hash. A new commit changes HEAD, which means the old HEAD key is no longer relevant. Since the cache typically has at most one entry (the current HEAD), clearing the entire dict is the simplest correct approach.

Tested in `tests/test_repo.py:440-448`:

```python
def test_compile_cache_invalidated_on_commit(self, repo):
    repo.commit(InstructionContent(text="First"))
    result1 = repo.compile()
    assert len(result1.messages) == 1

    repo.commit(DialogueContent(role="user", text="Second"))
    result2 = repo.compile()
    assert len(result2.messages) == 2  # Cache was cleared; fresh compile
```

### Empty Repo Handling

```python
current_head = self.head
if current_head is None:
    return CompiledContext(messages=[], token_count=0, commit_count=0, token_source="")
```

A repo with no commits has no HEAD. Rather than passing None to the compiler, we short-circuit and return an empty result. This is tested in `tests/test_repo.py:352-355`.

---

## Annotations and History

### annotate()

```python
# src/tract/repo.py:332-352

def annotate(self, target_hash, priority, *, reason=None):
    annotation = self._commit_engine.annotate(target_hash, priority, reason)
    self._session.commit()
    self._compile_cache.clear()  # Priority change affects compilation
    return annotation
```

Three things happen:
1. CommitEngine validates the target and creates the annotation row.
2. Session is committed (persisted).
3. Compile cache is cleared (annotations affect compilation output).

### get_annotations()

```python
# src/tract/repo.py:354-371

def get_annotations(self, target_hash):
    rows = self._annotation_repo.get_history(target_hash)
    return [
        PriorityAnnotation(
            id=row.id, repo_id=row.repo_id, target_hash=row.target_hash,
            priority=row.priority, reason=row.reason, created_at=row.created_at,
        )
        for row in rows
    ]
```

This converts raw `AnnotationRow` ORM objects into `PriorityAnnotation` Pydantic models. The conversion is explicit -- we do not expose ORM objects through the public API. This ensures the public API surface is stable even if the storage layer changes.

### The Full Annotation Lifecycle

A complete example from `tests/test_repo.py:215-229`:

```python
def test_delete_via_skip_annotation(self, repo_with_commits):
    repo, c1, c2, c3 = repo_with_commits

    # Skip a user message
    repo.annotate(c2.commit_hash, Priority.SKIP, reason="not needed")
    result = repo.compile()
    roles = [m.role for m in result.messages]
    assert "user" not in roles  # c2 excluded from compilation

    # Restore it
    repo.annotate(c2.commit_hash, Priority.NORMAL, reason="restored")
    result2 = repo.compile()
    roles2 = [m.role for m in result2.messages]
    assert "user" in roles2  # c2 back in compilation
```

This demonstrates the full cycle: commit content, skip it via annotation, verify it is excluded, restore it, verify it is included again. The append-only annotation table preserves the full history of these changes.

---

## The batch() Context Manager

```python
# src/tract/repo.py:390-418

@contextmanager
def batch(self) -> Iterator[None]:
    _real_commit = self._session.commit

    def _noop_commit() -> None:
        pass

    self._session.commit = _noop_commit  # type: ignore[assignment]
    try:
        yield
        _real_commit()  # Success: commit once
    except Exception:
        self._session.rollback()
        raise
    finally:
        self._session.commit = _real_commit  # type: ignore[assignment]
```

`batch()` provides atomic multi-commit operations. The technique is clever: it temporarily replaces `session.commit()` with a no-op. Inside the batch, each `repo.commit()` call does its work (creating blobs, commit rows, updating HEAD) and calls `session.flush()` via the repositories, but the final `session.commit()` is a no-op. When the batch exits successfully, the real `session.commit()` is called once, persisting everything atomically.

If an exception occurs, `session.rollback()` undoes all pending changes.

**Why monkey-patch the method?** The alternative would be to add a `_batching` flag and check it in every method that calls `session.commit()`. The monkey-patch approach is more contained -- it only requires changes in `batch()`, not in every method. It is also easier to reason about: the invariant is "session.commit is either real or no-op, never anything else."

Tested in `tests/test_repo.py:231-240`:

```python
def test_batch_context_manager(self, repo):
    with repo.batch():
        for i in range(10):
            repo.commit(
                DialogueContent(role="user", text=f"Message {i}"),
                message=f"msg-{i}",
            )
    # All 10 should be committed atomically
    history = repo.log(limit=20)
    assert len(history) == 10
```

**Atomicity guarantee**: If any commit in the batch fails (e.g., edit validation error), *none* of the batch's commits are persisted:

```
with repo.batch():
    repo.commit(InstructionContent(text="A"))  # Would succeed
    repo.commit(InstructionContent(text="B"),  # Fails: edit without reply_to
                operation=CommitOperation.EDIT)
# Exception propagates, session.rollback() undoes commit A
```

---

## Custom Content Types

```python
# src/tract/repo.py:420-427

def register_content_type(self, name: str, model: type[BaseModel]) -> None:
    self._custom_type_registry[name] = model
```

Users can extend the type system on a per-repo basis:

```python
# tests/test_repo.py:331-341

class CustomContent(BaseModel):
    content_type: str = "custom_note"
    note: str

repo.register_content_type("custom_note", CustomContent)
repo.commit({"content_type": "custom_note", "note": "My custom note"})

info = repo.get_commit(repo.head)
assert info.content_type == "custom_note"
```

**How it works**: When `repo.commit()` receives a dict, it calls `validate_content(data, custom_registry=self._custom_type_registry)`. The registry is checked before the built-in types, so custom types can even shadow built-in names if needed.

**Why per-repo, not global?** If you have multiple Repo instances in a process (e.g., one per agent in a multi-agent system), each should have independent type registries. A global registry would leak types between agents.

**What about custom types during compilation?** The current compiler treats custom types as any other content -- it looks up the content from the blob, extracts text using the same heuristics (text field, content field, payload field), and maps to a role using BUILTIN_TYPE_HINTS or the fallback "assistant." Custom types do not need special compilation registration in Phase 1.

---

## Time-Travel: as_of vs up_to

Trace provides two independent time-travel mechanisms on `compile()`:

### as_of: Datetime-Based Filtering

```python
result = repo.compile(as_of=some_datetime)
```

Only includes commits with `created_at <= as_of`. This answers: "What did the context look like at this point in time?"

Tested in `tests/test_repo.py:383-393`:

```python
def test_compile_time_travel_datetime(self, repo):
    c1 = repo.commit(InstructionContent(text="First"))
    time.sleep(0.05)
    cutoff = datetime.now(timezone.utc)
    time.sleep(0.05)
    c2 = repo.commit(DialogueContent(role="user", text="Second"))

    result = repo.compile(as_of=cutoff)
    assert len(result.messages) == 1
    assert "First" in result.messages[0].content  # Only first commit
```

### up_to: Hash-Based Filtering

```python
result = repo.compile(up_to=some_commit_hash)
```

Only includes commits up to and including the specified hash in the chain. This answers: "What did the context look like at this specific commit?"

Tested in `tests/test_repo.py:395-401`:

```python
def test_compile_time_travel_hash(self, repo):
    c1 = repo.commit(InstructionContent(text="First"))
    c2 = repo.commit(DialogueContent(role="user", text="Second"))
    c3 = repo.commit(DialogueContent(role="assistant", text="Third"))

    result = repo.compile(up_to=c2.commit_hash)
    assert len(result.messages) == 2  # First + Second
```

### Why Two Separate Parameters?

**We chose separate parameters over a combined "revision" concept because:**

1. **Different use cases**: `as_of` is for temporal queries ("show me the state at 2pm"). `up_to` is for structural queries ("show me everything up to this commit"). Combining them into one parameter would require type-switching logic and be less explicit.

2. **Mutual exclusivity**: Using both simultaneously would be ambiguous. The compiler raises `ValueError` if both are provided:

```python
# src/tract/engine/compiler.py:88-89
if as_of is not None and up_to is not None:
    raise ValueError("Cannot specify both as_of and up_to; use one or the other.")
```

Tested in `tests/test_engine/test_compiler.py:352-363`.

3. **Clear semantics**: `as_of` always means datetime comparison. `up_to` always means position in the commit chain. No ambiguity about which filtering mode is active.

### The Timezone Normalization Problem

SQLite stores datetimes as strings without timezone information. When Python creates `datetime.now(timezone.utc)`, SQLAlchemy stores it as a naive datetime string. When you provide `as_of=datetime.now(timezone.utc)` (timezone-aware) and compare it against the stored naive datetime, Python raises `TypeError: can't compare offset-naive and offset-aware datetimes`.

The compiler handles this with `_normalize_dt()` (`src/tract/engine/compiler.py:31-33`):

```python
def _normalize_dt(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
```

Both the parameter and the stored datetime are stripped of timezone info before comparison. This works because all datetimes in the system are UTC -- the normalization is simply removing the UTC marker for comparison purposes.

---

## The Protocol Pattern

**File:** `src/tract/protocols.py`

Trace uses Python's `typing.Protocol` for its pluggable interfaces:

```python
@runtime_checkable
class TokenCounter(Protocol):
    def count_text(self, text: str) -> int: ...
    def count_messages(self, messages: list[dict]) -> int: ...

@runtime_checkable
class ContextCompiler(Protocol):
    def compile(
        self, repo_id: str, head_hash: str, *,
        as_of: datetime | None = None,
        up_to: str | None = None,
        include_edit_annotations: bool = False,
    ) -> CompiledContext: ...
```

### Why Protocols Instead of ABCs?

Protocols use **structural subtyping** (also called "static duck typing"). Any class that has the right methods satisfies the protocol, without inheriting from it. ABCs require explicit inheritance.

**Tradeoff: Protocols vs ABCs**

| Aspect | Protocol | ABC |
|--------|----------|-----|
| Inheritance required | No | Yes |
| Runtime checking | With `@runtime_checkable` | With `isinstance()` |
| Static type checking | Full support | Full support |
| Method signature enforcement | At type check time | At class definition time |
| Third-party compatibility | Works with any class | Requires inheritance chain |

**We chose Protocols because:**

1. **Testing is trivial.** A test stub does not need to inherit from anything:

```python
# tests/test_repo.py:471-476
class FixedCounter:
    def count_text(self, text: str) -> int:
        return 42
    def count_messages(self, messages: list[dict]) -> int:
        return 100
```

This works as a `TokenCounter` without importing the protocol. If we used ABCs, the stub would need `class FixedCounter(TokenCounter)` and would need to import the ABC.

2. **Third-party integration.** If a user has an existing token counter from another library, they can use it directly without wrapping it in an adapter class. As long as it has `count_text` and `count_messages`, it satisfies the protocol.

3. **`@runtime_checkable` enables isinstance():**

```python
# tests/test_engine/test_tokens.py:17-19
counter = TiktokenCounter()
assert isinstance(counter, TokenCounter)
```

### The Output Dataclasses

Alongside the protocols, `protocols.py` defines frozen dataclasses for structured output:

```python
@dataclass(frozen=True)
class Message:
    role: str
    content: str
    name: str | None = None

@dataclass(frozen=True)
class CompiledContext:
    messages: list[Message] = field(default_factory=list)
    token_count: int = 0
    commit_count: int = 0
    token_source: str = ""

@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

**Why frozen dataclasses instead of Pydantic models?** These are output types, not input types. They do not need validation, serialization, or any of Pydantic's features. Frozen dataclasses are:
- Simpler (no Pydantic dependency for consumers).
- Immutable (frozen=True prevents accidental mutation).
- Hashable (can be used in sets/dicts).
- Lightweight (no metaclass magic).

**Why are these in `protocols.py` instead of a separate file?** They are part of the protocol contract. `ContextCompiler.compile()` returns `CompiledContext`. Putting them together avoids circular imports and keeps the "interface" module self-contained.

---

## Error Handling Philosophy

**File:** `src/tract/exceptions.py` (61 lines)

### The Exception Hierarchy

```python
class TraceError(Exception):
    """Base exception for all Trace errors."""

class CommitNotFoundError(TraceError):
    def __init__(self, commit_hash: str):
        self.commit_hash = commit_hash
        super().__init__(f"Commit not found: {commit_hash}")

class BlobNotFoundError(TraceError):
    def __init__(self, content_hash: str):
        self.content_hash = content_hash
        super().__init__(f"Blob not found: {content_hash}")

class ContentValidationError(TraceError):
    """Named ContentValidationError (not ValidationError) to avoid
    collision with pydantic.ValidationError."""

class BudgetExceededError(TraceError):
    def __init__(self, current_tokens: int, max_tokens: int):
        self.current_tokens = current_tokens
        self.max_tokens = max_tokens
        super().__init__(f"Token budget exceeded: {current_tokens} tokens (max: {max_tokens})")

class EditTargetError(TraceError):
    """Raised when an edit targets an invalid commit."""

class DuplicateRefError(TraceError):
    def __init__(self, ref_name: str):
        self.ref_name = ref_name
        super().__init__(f"Ref already exists: {ref_name}")
```

### Design Principles

1. **Single base exception**: All Trace exceptions inherit from `TraceError`. Users can catch `TraceError` to handle any Trace-specific error:

```python
try:
    repo.commit(content)
except TraceError as e:
    logger.error(f"Trace operation failed: {e}")
```

2. **Structured exception data**: Exceptions carry machine-readable data as attributes. `BudgetExceededError` has `.current_tokens` and `.max_tokens`. `CommitNotFoundError` has `.commit_hash`. This enables programmatic error handling, not just string parsing.

3. **No name collisions**: The exception is named `ContentValidationError`, not `ValidationError`. This prevents confusion with `pydantic.ValidationError`, which users may also be catching in their code. An exception name collision can cause subtle bugs where the wrong handler catches the wrong exception.

4. **Exceptions are specific**: Each exception type corresponds to one kind of failure. `EditTargetError` is not a generic "validation error" -- it specifically means an edit operation targeted an invalid commit. This enables precise `except` clauses.

### Where Exceptions Are Raised

| Exception | Raised By | Condition |
|-----------|-----------|-----------|
| `ContentValidationError` | `validate_content()` | Dict fails Pydantic validation |
| `EditTargetError` | `CommitEngine.create_commit()` | Edit without reply_to, nonexistent target, or edit-of-edit |
| `BudgetExceededError` | `CommitEngine.create_commit()` | Token budget exceeded in REJECT mode |
| `CommitNotFoundError` | `CommitEngine.annotate()` | Annotating a nonexistent commit |
| `BlobNotFoundError` | (Not raised in Phase 1) | Reserved for future use |
| `DuplicateRefError` | (Not raised in Phase 1) | Reserved for future branching |

---

## Resource Management

### Context Manager Support

```python
# src/tract/repo.py:442-446

def __enter__(self) -> Repo:
    return self

def __exit__(self, exc_type, exc_val, exc_tb) -> None:
    self.close()
```

The `with` statement ensures `close()` is called even if an exception occurs:

```python
with Repo.open() as repo:
    repo.commit(InstructionContent(text="test"))
    # If an exception occurs here, close() is still called
```

### The close() Method

```python
# src/tract/repo.py:429-436

def close(self) -> None:
    if self._closed:
        return
    self._closed = True
    self._session.close()
    if self._engine is not None:
        self._engine.dispose()
```

**Idempotent close**: The `_closed` flag prevents double-close errors. Calling `close()` multiple times is safe.

**Engine disposal**: `engine.dispose()` closes the connection pool. For `from_components()` where `engine` may be None (the caller manages the engine), we skip disposal.

### The head Property

```python
# src/tract/repo.py:231-233

@property
def head(self) -> str | None:
    return self._ref_repo.get_head(self._repo_id)
```

`head` is a property, not a cached value. It queries the database every time. This ensures it always reflects the current state, even if something modified the database outside of this Repo instance (e.g., in a multi-process scenario).

---

## Test Walkthrough

**File:** `tests/test_repo.py` (602 lines)

The test file is organized by **success criteria** (SC1-SC5), providing a clear traceability from requirements to tests.

### Test Fixtures

```python
# tests/test_repo.py:45-61

@pytest.fixture()
def repo():
    r = Repo.open()
    yield r
    r.close()

@pytest.fixture()
def repo_with_commits(repo):
    c1 = repo.commit(InstructionContent(text="You are helpful."), message="system")
    c2 = repo.commit(DialogueContent(role="user", text="Hi"), message="greeting")
    c3 = repo.commit(
        DialogueContent(role="assistant", text="Hello!"), message="reply"
    )
    return repo, c1, c2, c3
```

Two fixtures:
- `repo`: A clean in-memory Repo for each test.
- `repo_with_commits`: A Repo pre-loaded with a typical 3-commit chain (system prompt + user + assistant).

### SC1: Initialization and Persistence

```python
def test_persistence_across_reopen(self, tmp_path):
    db_path = str(tmp_path / "persist.db")
    repo_id = "persist-test"

    with Repo.open(db_path, repo_id=repo_id) as r1:
        r1.commit(InstructionContent(text="Persist me"), message="first")
        head1 = r1.head

    with Repo.open(db_path, repo_id=repo_id) as r2:
        assert r2.head == head1
        result = r2.compile()
        assert len(result.messages) == 1
        assert "Persist me" in result.messages[0].content
```

This test demonstrates the full persistence lifecycle:
1. Open a file-backed repo, commit content, close it.
2. Reopen the same file with the same repo_id.
3. Verify HEAD is the same and content compiles correctly.

### SC2: Commits and Annotations

The commit chain test (`tests/test_repo.py:209-213`) verifies parent pointers:

```python
def test_commit_chain(self, repo_with_commits):
    repo, c1, c2, c3 = repo_with_commits
    assert c1.parent_hash is None       # Root: no parent
    assert c2.parent_hash == c1.commit_hash  # Points to c1
    assert c3.parent_hash == c2.commit_hash  # Points to c2
```

### SC3: All Content Types

Each of the 7 content types is tested individually (`tests/test_repo.py:251-307`). For example:

```python
def test_tool_io_content(self, repo):
    repo.commit(
        ToolIOContent(
            tool_name="calculator", direction="call",
            payload={"expression": "2+2"},
        )
    )
    result = repo.compile()
    assert result.messages[0].role == "tool"
    assert "calculator" in result.messages[0].content
```

And a mixed-type test verifies correct role mapping across all types:

```python
def test_mixed_content_types(self, repo):
    repo.commit(InstructionContent(text="System"))
    repo.commit(DialogueContent(role="user", text="Question"))
    repo.commit(ToolIOContent(tool_name="search", direction="result",
                               payload={"results": []}, status="success"))
    result = repo.compile()
    assert len(result.messages) == 3
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"
    assert result.messages[2].role == "tool"
```

### SC5: Token Counting with Pluggable Tokenizer

```python
def test_custom_tokenizer(self):
    class FixedCounter:
        def count_text(self, text: str) -> int:
            return 42
        def count_messages(self, messages: list[dict]) -> int:
            return 100

    with Repo.open(tokenizer=FixedCounter()) as r:
        info = r.commit(InstructionContent(text="test"))
        assert info.token_count == 42
        result = r.compile()
        assert result.token_count == 100
```

This test demonstrates the Protocol pattern in action:
1. Define a minimal stub (3-line class, no inheritance).
2. Inject it via `Repo.open(tokenizer=...)`.
3. Verify both commit-level and compile-level token counts use the custom counter.

### The log() Method

```python
# src/tract/repo.py:373-388

def log(self, limit: int = 10) -> list[CommitInfo]:
    current_head = self.head
    if current_head is None:
        return []
    ancestors = self._commit_repo.get_ancestors(current_head, limit=limit)
    return [self._commit_engine._row_to_info(row) for row in ancestors]
```

`log()` walks the ancestor chain from HEAD and converts ORM rows to CommitInfo DTOs. The `limit` parameter prevents unbounded queries.

Tested in `tests/test_repo.py:519-534`:

```python
def test_log_returns_commits_newest_first(self, repo_with_commits):
    repo, c1, c2, c3 = repo_with_commits
    history = repo.log()
    assert len(history) == 3
    assert history[0].commit_hash == c3.commit_hash  # Newest first
    assert history[1].commit_hash == c2.commit_hash
    assert history[2].commit_hash == c1.commit_hash  # Oldest last

def test_log_respects_limit(self, repo):
    for i in range(5):
        repo.commit(DialogueContent(role="user", text=f"msg {i}"))
    history = repo.log(limit=2)
    assert len(history) == 2
```

---

## Reusable Patterns

The Trace codebase demonstrates several patterns that are applicable to other Python projects.

### 1. The Layered Architecture

**Pattern**: Organize code into layers where each layer depends only on the layer below.

**Application in Trace**: Models -> Storage -> Engine -> Repo. Nothing in the lower layers imports from upper layers.

**When to use**: Any project with more than trivial complexity. It enforces separation of concerns and makes each layer independently testable.

### 2. Content-Addressable Storage

**Pattern**: Key data by the hash of its content. Same content = same key = stored once.

**Application in Trace**: Blob storage keyed by SHA-256 hash.

**When to use**: When you have potentially duplicated content (caching, deduplication, integrity verification). Also useful when you need immutable data -- once stored, the content at a given hash never changes.

### 3. Append-Only Tables for Mutable Metadata

**Pattern**: Instead of updating rows, append new rows. The latest row is the current state. Previous rows provide history.

**Application in Trace**: The annotations table. Priority changes create new rows.

**When to use**: When you need audit trails, provenance, or undo capability. The tradeoff is more storage and slightly more complex queries (need to find "latest" row).

### 4. Protocol-Based Pluggability

**Pattern**: Define interfaces as `typing.Protocol` rather than ABCs. Provide at least two implementations (production + testing stub).

**Application in Trace**: `TokenCounter` (TiktokenCounter + NullTokenCounter) and `ContextCompiler`.

**When to use**: When you want to support dependency injection without forcing users to inherit from your base classes. Especially useful when third-party classes might already implement the interface.

### 5. Factory Classmethods for Construction

**Pattern**: Multiple `@classmethod` factories instead of a complex `__init__`.

**Application in Trace**: `Repo.open()` (standard path) and `Repo.from_components()` (DI path).

**When to use**: When an object can be created from different sets of inputs. Each classmethod documents a specific construction path with clear naming.

### 6. Session-Level Transaction Control

**Pattern**: Repositories call `flush()` (send SQL), and the facade calls `commit()` (finalize transaction).

**Application in Trace**: Repositories flush; Repo.commit()/annotate() call session.commit().

**When to use**: When you need to support atomic multi-operation transactions. The batch() context manager depends on this pattern.

### 7. Cache Invalidation on Write

**Pattern**: A simple dict cache keyed by the entity that determines freshness. Clear the cache on any write operation.

**Application in Trace**: `_compile_cache` keyed by HEAD hash. Cleared on commit() and annotate().

**When to use**: When reads are more frequent than writes and compilation/computation is expensive. The simplicity of "clear everything on write" avoids cache coherency bugs.

### 8. Discriminated Union with Per-Instance Registry

**Pattern**: A Pydantic discriminated union for built-in types, plus a dict registry for user-defined types. Check the registry first, fall through to the union.

**Application in Trace**: `validate_content()` with `custom_registry` parameter.

**When to use**: When you have a fixed set of known types but need extensibility. The two-tier lookup provides both type safety (for built-ins) and flexibility (for custom types).

### 9. Frozen Dataclasses for Output Types

**Pattern**: Use `@dataclass(frozen=True)` for return types that should be immutable and lightweight.

**Application in Trace**: `Message`, `CompiledContext`, `TokenUsage`.

**When to use**: For return types that do not need validation. Frozen dataclasses are simpler, faster, and more explicit about immutability than Pydantic models.

### 10. Testing with Real Infrastructure, Not Mocks

**Pattern**: Use in-memory SQLite for tests instead of mocking the database layer.

**Application in Trace**: All tests use `create_trace_engine(":memory:")` with real repositories.

**When to use**: When the infrastructure is fast enough (in-memory SQLite is very fast) and the alternative (mocking) would reduce test fidelity. Testing against real SQL catches bugs that mocks would hide (FK violations, query errors, transaction behavior).

---

## Summary

The `Repo` class is a thin but carefully designed facade. It:
- Hides 10+ internal objects behind a clean API.
- Provides two construction paths (standard and DI).
- Manages transactions, caching, and resource cleanup.
- Supports extensibility through protocols and custom type registries.
- Maintains clear boundaries between "what users see" (CommitInfo, CompiledContext) and "what the system uses" (CommitRow, BlobRow).

The design patterns used throughout Trace are not novel, but their combination creates a system that is testable at every layer, extensible without modification, and understandable from top to bottom.

---

*Back to: [01 - Foundations Overview](01-foundations-overview.md)*
