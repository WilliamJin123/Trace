# Phase 1 Deep Dive: Data Models and Storage

This tutorial covers the bottom two layers of the Trace architecture: the Pydantic domain models that define the shape of data, and the SQLAlchemy storage layer that persists it. Together, these form the foundation on which the engine and public API are built.

---

## Table of Contents

1. [Content Type System](#content-type-system)
2. [Commit and Annotation Models](#commit-and-annotation-models)
3. [Configuration Models](#configuration-models)
4. [SQLAlchemy Schema Design](#sqlalchemy-schema-design)
5. [The Repository Pattern](#the-repository-pattern)
6. [Schema Versioning](#schema-versioning)
7. [Test Walkthrough](#test-walkthrough)

---

## Content Type System

**File:** `src/tract/models/content.py` (219 lines)

The content type system is the heart of Trace's data model. Every commit wraps a **typed content block** -- not a raw string, but a structured Pydantic model that carries semantic information about what kind of content it is.

### The 7 Built-in Content Types

Each type is a Pydantic `BaseModel` with a `content_type` literal discriminator field:

```python
# src/tract/models/content.py:26-81

class InstructionContent(BaseModel):
    content_type: Literal["instruction"] = "instruction"
    text: str

class DialogueContent(BaseModel):
    content_type: Literal["dialogue"] = "dialogue"
    role: Literal["user", "assistant", "system"]
    text: str
    name: str | None = None

class ToolIOContent(BaseModel):
    content_type: Literal["tool_io"] = "tool_io"
    tool_name: str
    direction: Literal["call", "result"]
    payload: dict
    status: Literal["success", "error"] | None = None

class ReasoningContent(BaseModel):
    content_type: Literal["reasoning"] = "reasoning"
    text: str

class ArtifactContent(BaseModel):
    content_type: Literal["artifact"] = "artifact"
    artifact_type: str
    content: str
    language: str | None = None

class OutputContent(BaseModel):
    content_type: Literal["output"] = "output"
    text: str
    format: Literal["text", "markdown", "json"] = "text"

class FreeformContent(BaseModel):
    content_type: Literal["freeform"] = "freeform"
    payload: dict
```

**Why 7 types?** These cover the categories of content that flow through a typical LLM agent conversation:

| Type | Purpose | Example |
|------|---------|---------|
| `instruction` | System-level prompts | "You are a helpful assistant." |
| `dialogue` | User/assistant/system messages | The actual conversation turns |
| `tool_io` | Tool calls and results | Function calling, MCP tools |
| `reasoning` | Chain-of-thought traces | Internal model reasoning |
| `artifact` | Produced artifacts | Generated code, documents |
| `output` | Final outputs | The answer to the user's question |
| `freeform` | Anything else | Arbitrary JSON payload |

**Why separate types instead of a generic message?** Because different content types need different handling:

- `instruction` defaults to PINNED priority (never evict the system prompt).
- `dialogue` carries a `role` field that maps directly to the LLM API's message role.
- `tool_io` compresses aggressively (low `compression_priority` of 30) because tool results are often large and less important over time.
- `reasoning` traces might be dropped entirely during compression.

These behavioral differences are encoded in `ContentTypeHints`.

### The Discriminated Union

```python
# src/tract/models/content.py:87-101

ContentPayload = Annotated[
    Union[
        InstructionContent,
        DialogueContent,
        ToolIOContent,
        ReasoningContent,
        ArtifactContent,
        OutputContent,
        FreeformContent,
    ],
    Field(discriminator="content_type"),
]

_builtin_adapter = TypeAdapter(ContentPayload)
```

`ContentPayload` is a Pydantic discriminated union. Given a dict like `{"content_type": "instruction", "text": "hello"}`, Pydantic reads the `content_type` field first, determines which model to use, and validates accordingly. This is extremely efficient -- Pydantic does not try all 7 types; it dispatches directly.

The `TypeAdapter` wraps the union for validation without needing a parent model. This is a Pydantic v2 pattern that avoids the boilerplate of creating a wrapper class.

**Test evidence** -- `tests/test_models/test_content.py:126-182`:

```python
class TestDiscriminatedUnion:
    adapter = TypeAdapter(ContentPayload)

    def test_instruction_dispatch(self):
        result = self.adapter.validate_python(
            {"content_type": "instruction", "text": "test"}
        )
        assert isinstance(result, InstructionContent)

    def test_invalid_content_type(self):
        with pytest.raises(Exception):
            self.adapter.validate_python(
                {"content_type": "nonexistent", "data": "test"}
            )
```

### The `validate_content()` Function and Custom Registry

```python
# src/tract/models/content.py:120-161

def validate_content(
    data: dict,
    *,
    custom_registry: dict[str, type[BaseModel]] | None = None,
) -> BaseModel:
    content_type = data.get("content_type")

    # Check custom registry first (if provided)
    if custom_registry and content_type in custom_registry:
        try:
            model_class = custom_registry[content_type]
            adapter = TypeAdapter(model_class)
            return adapter.validate_python(data)
        except ValidationError as e:
            raise ContentValidationError(...) from e

    # Fall through to built-in discriminated union
    try:
        return _builtin_adapter.validate_python(data)
    except ValidationError as e:
        raise ContentValidationError(...) from e
```

This function is the validation entry point when users pass dicts instead of Pydantic models. The two-tier lookup is critical:

1. **Custom registry first**: If the repo has registered a custom type with that name, use it.
2. **Built-in union second**: Otherwise, fall through to the 7 built-in types.

**Why per-repo registry instead of a global registry?** A global registry would create cross-contamination between repo instances in the same process. If Repo A registers a "custom_note" type, Repo B should not see it. Per-repo registries provide isolation. This is stored as `Repo._custom_type_registry: dict[str, type[BaseModel]]` (`src/tract/repo.py:87`).

**Why can custom types shadow builtins?** The custom registry is checked *first*. This means you can override the "instruction" type with a custom model that has extra fields. This is tested in `tests/test_models/test_content.py:244-258`:

```python
def test_custom_registry_can_shadow_builtin(self):
    class CustomInstruction(BaseModel):
        content_type: str = "instruction"
        text: str
        priority_override: int = 0

    registry = {"instruction": CustomInstruction}
    result = validate_content(
        {"content_type": "instruction", "text": "test", "priority_override": 5},
        custom_registry=registry,
    )
    assert isinstance(result, CustomInstruction)
    assert result.priority_override == 5
```

**Why `ContentValidationError` instead of letting Pydantic's `ValidationError` propagate?** Because `pydantic.ValidationError` is a common name in many codebases. Wrapping it in a Trace-specific exception (`ContentValidationError(TraceError)`) provides:
- A stable exception hierarchy users can catch without importing Pydantic.
- Clear messaging about what went wrong (content validation, not arbitrary Pydantic validation).

### Content Type Behavioral Hints

```python
# src/tract/models/content.py:169-218

@dataclass(frozen=True)
class ContentTypeHints:
    default_priority: str = "normal"
    default_role: str = "assistant"
    compression_priority: int = 50  # 0=compress first, 100=protect
    aggregation_rule: str = "concatenate"

BUILTIN_TYPE_HINTS: dict[str, ContentTypeHints] = {
    "instruction": ContentTypeHints(
        default_priority="pinned",
        default_role="system",
        compression_priority=90,
    ),
    "dialogue": ContentTypeHints(
        default_priority="normal",
        default_role="user",
        compression_priority=50,
    ),
    "tool_io": ContentTypeHints(
        default_priority="normal",
        default_role="tool",
        compression_priority=30,
    ),
    # ... etc for all 7 types
}
```

Each content type has behavioral hints that drive compilation and future compression:

- **`default_priority`**: What priority a commit gets if no annotation is set. Instructions are `"pinned"` -- they should never be evicted.
- **`default_role`**: What LLM message role this type maps to. Instructions -> `"system"`, dialogue -> `"user"` (overridden by the content's own `role` field), tool_io -> `"tool"`.
- **`compression_priority`**: 0 means "compress this first", 100 means "protect this". Tool I/O (30) compresses before dialogue (50), which compresses before instructions (90).
- **`aggregation_rule`**: How to merge consecutive same-type messages. Currently always `"concatenate"`.

**Reusable pattern**: This "type hints as a frozen dataclass keyed by discriminator value" pattern is useful any time you have a discriminated union where different variants need different default behaviors. It keeps the behavior configuration separate from the data models themselves.

---

## Commit and Annotation Models

### CommitInfo

**File:** `src/tract/models/commit.py`

```python
class CommitOperation(str, enum.Enum):
    APPEND = "append"
    EDIT = "edit"

class CommitInfo(BaseModel):
    commit_hash: str
    repo_id: str
    parent_hash: Optional[str] = None
    content_hash: str
    content_type: str
    operation: CommitOperation
    reply_to: Optional[str] = None
    message: Optional[str] = None
    token_count: int
    metadata: Optional[dict] = None
    created_at: datetime
```

`CommitInfo` is a **data transfer object** (DTO). It is *not* an ORM model -- it is what the SDK returns to users. Key fields:

- **`commit_hash`**: SHA-256 hash uniquely identifying this commit. Computed from content_hash + parent_hash + content_type + operation + timestamp + reply_to.
- **`parent_hash`**: Points to the previous commit. `None` for the first commit (root).
- **`content_hash`**: SHA-256 of the content blob. This is the foreign key into blob storage.
- **`content_type`**: The discriminator string (e.g., "instruction", "dialogue"). Stored as a plain string, not an enum, because custom types can have arbitrary names.
- **`operation`**: APPEND (new content) or EDIT (replacement for an existing commit).
- **`reply_to`**: For EDIT operations, the hash of the commit being replaced. For APPEND, always None.
- **`token_count`**: Number of tokens in the content (raw, not including message overhead).
- **`metadata`**: Arbitrary user-provided metadata dict.
- **`created_at`**: UTC timestamp.

**Why two operations (APPEND and EDIT), not three?** Early design considered a PIN operation, but pinning is an *annotation* -- mutable metadata on a commit -- not a commit operation. Operations are immutable (part of the commit hash), while annotations can change over time.

### Priority and PriorityAnnotation

**File:** `src/tract/models/annotations.py`

```python
class Priority(str, enum.Enum):
    SKIP = "skip"
    NORMAL = "normal"
    PINNED = "pinned"

class PriorityAnnotation(BaseModel):
    id: Optional[int] = None
    repo_id: str
    target_hash: str
    priority: Priority
    reason: Optional[str] = None
    created_at: datetime
```

Annotations are lightweight, mutable metadata attached to commits. The annotation table is **append-only**: changing a commit's priority creates a new annotation row. The latest row (by `created_at`) is the current priority.

**Why append-only?** For provenance. You can see the full history of priority changes: "This commit was NORMAL, then SKIPPED at 2:30pm (reason: 'not relevant'), then restored to NORMAL at 3:00pm (reason: 'actually needed')." This is tested in `tests/test_repo.py:581-592`:

```python
def test_annotation_history(self, repo: Repo):
    c1 = repo.commit(DialogueContent(role="user", text="test"))
    repo.annotate(c1.commit_hash, Priority.SKIP, reason="hide")
    repo.annotate(c1.commit_hash, Priority.NORMAL, reason="show")

    history = repo.get_annotations(c1.commit_hash)
    assert len(history) >= 2
    reasons = [a.reason for a in history if a.reason]
    assert "hide" in reasons
    assert "show" in reasons
```

### DEFAULT_TYPE_PRIORITIES

```python
DEFAULT_TYPE_PRIORITIES: dict[str, Priority] = {
    "instruction": Priority.PINNED,
    "dialogue": Priority.NORMAL,
    "tool_io": Priority.NORMAL,
    "reasoning": Priority.NORMAL,
    "artifact": Priority.NORMAL,
    "output": Priority.NORMAL,
    "freeform": Priority.NORMAL,
}
```

Only `instruction` has a non-NORMAL default. When `CommitEngine.create_commit()` processes an instruction commit, it auto-creates a PINNED annotation (`src/tract/engine/commit.py:212-221`). Dialogue and other types get no auto-annotation -- they default to NORMAL implicitly (the compiler checks DEFAULT_TYPE_PRIORITIES when no annotation exists).

This is verified in `tests/test_engine/test_commit.py:308-321`:

```python
def test_instruction_auto_pinned(self, commit_engine, repos):
    commit = commit_engine.create_commit(InstructionContent(text="system prompt"))
    latest = repos["annotation"].get_latest(commit.commit_hash)
    assert latest is not None
    assert latest.priority == Priority.PINNED

def test_dialogue_no_auto_annotation(self, commit_engine, repos):
    commit = commit_engine.create_commit(DialogueContent(role="user", text="hello"))
    latest = repos["annotation"].get_latest(commit.commit_hash)
    assert latest is None  # No annotation created for NORMAL default
```

---

## Configuration Models

**File:** `src/tract/models/config.py`

```python
class BudgetAction(str, enum.Enum):
    WARN = "warn"
    REJECT = "reject"
    CALLBACK = "callback"

class TokenBudgetConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    max_tokens: Optional[int] = None  # None = unlimited
    action: BudgetAction = BudgetAction.WARN
    callback: Optional[Callable[[int, int], None]] = None

class RepoConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    db_path: str = ":memory:"
    tokenizer_encoding: str = "o200k_base"
    token_budget: Optional[TokenBudgetConfig] = None
    default_branch: str = "main"
```

**Token budget enforcement** has three modes:

1. **WARN** (default): Log a warning but allow the commit. The context is over budget, but the user can decide what to do.
2. **REJECT**: Raise `BudgetExceededError`. The commit is prevented.
3. **CALLBACK**: Call a user-provided function `(current_tokens, max_tokens) -> None`. The user can implement custom logic (e.g., trigger compression).

**Why `arbitrary_types_allowed`?** The `callback` field is a `Callable`, which Pydantic cannot serialize/validate by default. Setting `arbitrary_types_allowed = True` in the model config tells Pydantic to accept it without validation.

**Why `o200k_base` as the default tokenizer encoding?** This is the tokenizer used by GPT-4o and later OpenAI models. It is the most common encoding for modern LLM APIs.

---

## SQLAlchemy Schema Design

**File:** `src/tract/storage/schema.py` (138 lines)

The schema defines 5 tables. Let's examine each one and the design reasoning.

### BlobRow -- Content-Addressable Storage

```python
class BlobRow(Base):
    __tablename__ = "blobs"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

The **primary key is the SHA-256 hash** of the content. This is the content-addressable storage pattern. If you try to insert a blob with the same hash, it is a duplicate -- the `SqliteBlobRepository.save_if_absent()` method checks for existence first.

- `payload_json`: The full Pydantic model serialized as JSON. This is the raw content.
- `byte_size`: Size of the JSON payload in bytes.
- `token_count`: Token count of the text content (not the JSON overhead).
- `created_at`: When the blob was first stored.

**Why store `payload_json` as `Text` instead of using `JSON` type?** The blob content needs to be stored exactly as-is for hash verification. The `JSON` type in SQLAlchemy may re-serialize the content, potentially changing key ordering. Storing as `Text` preserves the exact bytes.

### CommitRow -- The Commit DAG

```python
class CommitRow(Base):
    __tablename__ = "commits"

    commit_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("commits.commit_hash", ondelete="SET NULL"),
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("blobs.content_hash"),
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    operation: Mapped[CommitOperation] = mapped_column(nullable=False)
    reply_to: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("commits.commit_hash", ondelete="SET NULL"),
        nullable=True,
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

Key design decisions:

**Self-referencing foreign keys with `SET NULL`:** Both `parent_hash` and `reply_to` reference `commits.commit_hash`. The `ondelete="SET NULL"` means that if the referenced commit is ever deleted (e.g., future garbage collection), the pointer becomes NULL rather than causing a cascade delete or integrity error. This is defensive design for future GC support.

**Why `content_type` is a `String(50)`, not an enum column?** Because custom content types can have arbitrary names. An enum column would require schema migrations every time a new type is registered.

**Why `metadata_json` uses `JSON` type but `payload_json` in blobs uses `Text`?** Metadata is not content-addressed. Its exact serialization does not matter for hashing. The `JSON` type gives SQLAlchemy native JSON operations for querying metadata fields in the future.

**Indexes:**

```python
__table_args__ = (
    Index("ix_commits_repo_time", "repo_id", "created_at"),
    Index("ix_commits_repo_type", "repo_id", "content_type"),
    Index("ix_commits_reply_to", "reply_to"),
)
```

Three composite/single indexes optimized for the most common query patterns:
- `(repo_id, created_at)`: Walking commits in time order for a specific repo.
- `(repo_id, content_type)`: Finding all commits of a given type (e.g., all instructions).
- `(reply_to)`: Finding edits that target a specific commit.

The `repo_id` column also has a standalone index from the `index=True` on the column definition.

**Relationships:**

```python
blob: Mapped["BlobRow"] = relationship("BlobRow", lazy="select")
parent: Mapped[Optional["CommitRow"]] = relationship(
    "CommitRow",
    remote_side="CommitRow.commit_hash",
    foreign_keys=[parent_hash],
)
```

The `blob` relationship enables eager loading of content when needed. The `parent` self-referential relationship enables navigation up the commit chain, though in practice the code uses explicit `get_ancestors()` loops.

### RefRow -- Mutable Pointers

```python
class RefRow(Base):
    __tablename__ = "refs"

    repo_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ref_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    commit_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("commits.commit_hash"),
        nullable=True,
    )
    symbolic_target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

Refs are the **only mutable state** in the system. Everything else is append-only. A ref is a named pointer to a commit, like git's HEAD or branch pointers.

**Composite primary key `(repo_id, ref_name)`:** Different repos can have refs with the same name (e.g., both have a "HEAD"). This is tested in `tests/test_storage/test_schema.py:223-238`.

**`symbolic_target`:** Defined for future use (symbolic refs like git's `HEAD -> refs/heads/main`). Not used in Phase 1.

HEAD is stored as `ref_name="HEAD"`. Branches are stored as `ref_name="refs/heads/{name}"`. See `SqliteRefRepository` for the naming conventions (`src/tract/storage/sqlite.py:95-154`).

### AnnotationRow -- Append-Only Priority History

```python
class AnnotationRow(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("commits.commit_hash"),
        nullable=False,
    )
    priority: Mapped[Priority] = mapped_column(nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_annotations_target_time", "target_hash", "created_at"),
    )
```

**Autoincrement integer PK**: Unlike commits (hash-keyed) and blobs (hash-keyed), annotations use an autoincrement ID. This is because annotations are not content-addressed -- two identical priority changes at different times are distinct events.

**The `(target_hash, created_at)` index** optimizes the most common query: "get the latest annotation for this commit" (order by created_at DESC, limit 1).

### TraceMetaRow -- Schema Versioning

```python
class TraceMetaRow(Base):
    __tablename__ = "_trace_meta"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
```

A simple key-value table for database metadata. Currently stores only `schema_version = "1"`. The underscore prefix (`_trace_meta`) signals that this is internal infrastructure, not user-facing data.

**Why a separate meta table?** Schema versioning enables future migration support. When Phase 2 adds new columns or tables, the code can check `schema_version` and run appropriate migrations.

---

## The Repository Pattern

**Files:** `src/tract/storage/repositories.py` (ABCs) and `src/tract/storage/sqlite.py` (implementations)

### Abstract Interfaces

```python
# src/tract/storage/repositories.py

class CommitRepository(ABC):
    @abstractmethod
    def get(self, commit_hash: str) -> CommitRow | None: ...
    @abstractmethod
    def save(self, commit: CommitRow) -> None: ...
    @abstractmethod
    def get_ancestors(self, commit_hash: str, limit: int | None = None) -> Sequence[CommitRow]: ...
    @abstractmethod
    def get_by_type(self, content_type: str, repo_id: str) -> Sequence[CommitRow]: ...
    @abstractmethod
    def get_children(self, commit_hash: str) -> Sequence[CommitRow]: ...

class BlobRepository(ABC):
    @abstractmethod
    def get(self, content_hash: str) -> BlobRow | None: ...
    @abstractmethod
    def save_if_absent(self, blob: BlobRow) -> None: ...

class RefRepository(ABC):
    @abstractmethod
    def get_head(self, repo_id: str) -> str | None: ...
    @abstractmethod
    def update_head(self, repo_id: str, commit_hash: str) -> None: ...
    @abstractmethod
    def get_branch(self, repo_id: str, branch_name: str) -> str | None: ...
    @abstractmethod
    def set_branch(self, repo_id: str, branch_name: str, commit_hash: str) -> None: ...
    @abstractmethod
    def list_branches(self, repo_id: str) -> list[str]: ...

class AnnotationRepository(ABC):
    @abstractmethod
    def get_latest(self, target_hash: str) -> AnnotationRow | None: ...
    @abstractmethod
    def save(self, annotation: AnnotationRow) -> None: ...
    @abstractmethod
    def get_history(self, target_hash: str) -> Sequence[AnnotationRow]: ...
    @abstractmethod
    def batch_get_latest(self, target_hashes: list[str]) -> dict[str, AnnotationRow]: ...
```

Four repository interfaces, each owning one concern. The important thing is that **these ABCs do not import SQLAlchemy**. They reference schema types only via `TYPE_CHECKING` imports. This means the engine layer can depend on the abstract interfaces without pulling in SQLAlchemy.

**Why `save_if_absent` for blobs but `save` for commits?** Blobs are content-addressed: the same content should be stored once. The repository must check for existence before inserting. Commits are unique by construction (the hash includes a timestamp), so dedup is unnecessary.

**Why `batch_get_latest` on AnnotationRepository?** This exists to avoid the N+1 query problem during compilation. When compiling a chain of 100 commits, the compiler needs the latest annotation for each one. Without `batch_get_latest`, that would be 100 separate queries. With it, it is one query using a subquery:

```python
# src/tract/storage/sqlite.py:188-215

def batch_get_latest(self, target_hashes: list[str]) -> dict[str, AnnotationRow]:
    if not target_hashes:
        return {}

    # Subquery: max created_at per target_hash
    max_time_subq = (
        select(
            AnnotationRow.target_hash,
            func.max(AnnotationRow.created_at).label("max_created_at"),
        )
        .where(AnnotationRow.target_hash.in_(target_hashes))
        .group_by(AnnotationRow.target_hash)
        .subquery()
    )

    # Join to get full rows
    stmt = (
        select(AnnotationRow)
        .join(
            max_time_subq,
            (AnnotationRow.target_hash == max_time_subq.c.target_hash)
            & (AnnotationRow.created_at == max_time_subq.c.max_created_at),
        )
    )

    rows = self._session.execute(stmt).scalars().all()
    return {row.target_hash: row for row in rows}
```

This is a single SQL query that groups by `target_hash`, finds the max `created_at` per group, then joins back to get the full rows. Tested in `tests/test_storage/test_repositories.py:336-377`.

### SQLite Implementations

Each implementation takes a `Session` in its constructor and uses SQLAlchemy 2.0-style queries:

```python
# src/tract/storage/sqlite.py:49-93

class SqliteCommitRepository(CommitRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, commit_hash: str) -> CommitRow | None:
        stmt = select(CommitRow).where(CommitRow.commit_hash == commit_hash)
        return self._session.execute(stmt).scalar_one_or_none()

    def save(self, commit: CommitRow) -> None:
        self._session.add(commit)
        self._session.flush()

    def get_ancestors(self, commit_hash: str, limit: int | None = None) -> Sequence[CommitRow]:
        ancestors: list[CommitRow] = []
        current_hash: str | None = commit_hash

        while current_hash is not None:
            if limit is not None and len(ancestors) >= limit:
                break
            commit = self.get(current_hash)
            if commit is None:
                break
            ancestors.append(commit)
            current_hash = commit.parent_hash

        return ancestors
```

**`get_ancestors` walks the chain in Python**, not SQL. This is a deliberate trade-off:

- **Pro**: Simple, readable, works with any database. No recursive CTEs needed.
- **Con**: N queries for N commits (one `get()` per ancestor). For Phase 1's linear history, this is acceptable -- chains are typically < 100 commits in a conversation.
- **Future optimization**: A recursive CTE or denormalized ancestor table could be added in later phases for very long chains.

**`session.flush()` vs `session.commit()`:** Repositories call `flush()` (send SQL to the database) but not `commit()` (finalize the transaction). The `Repo` layer controls transaction boundaries by calling `session.commit()` after the engine completes its work. This enables the `batch()` context manager to defer the final commit.

### Engine and Session Factory

**File:** `src/tract/storage/engine.py`

```python
def create_trace_engine(db_path: str = ":memory:") -> Engine:
    url = "sqlite://" if db_path == ":memory:" else f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
```

Four SQLite pragmas are set on every connection:

1. **`journal_mode=WAL`** (Write-Ahead Logging): Allows concurrent readers and a single writer. Default SQLite uses rollback journals which block readers during writes.
2. **`busy_timeout=5000`**: Wait up to 5 seconds if the database is locked before returning BUSY. Prevents immediate failures in concurrent scenarios.
3. **`synchronous=NORMAL`**: Reduced fsync frequency (safe with WAL). Faster writes than the default FULL mode.
4. **`foreign_keys=ON`**: SQLite does not enforce foreign keys by default (!). This pragma enables FK enforcement, which is tested in `tests/test_storage/test_schema.py:159-173`:

```python
def test_fk_invalid_content_hash_fails(self, session):
    commit = CommitRow(
        commit_hash="bad_commit_" + "x" * 53,
        content_hash="nonexistent_blob_hash_" + "0" * 42,
        ...
    )
    session.add(commit)
    with pytest.raises(IntegrityError):
        session.flush()
```

The session factory uses `expire_on_commit=False`:

```python
def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
```

**Why `expire_on_commit=False`?** By default, SQLAlchemy expires all attributes on commit, requiring a new query to access them. Since Trace reads attributes immediately after committing (e.g., returning `CommitInfo` to the user), this would cause unnecessary lazy-load queries. Disabling expiration avoids this.

---

## Schema Versioning

```python
# src/tract/storage/engine.py:48-66

def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        existing = session.execute(
            select(TraceMetaRow).where(TraceMetaRow.key == "schema_version")
        ).scalar_one_or_none()

        if existing is None:
            session.add(TraceMetaRow(key="schema_version", value="1"))
            session.commit()
```

`init_db()` is idempotent -- it can be called multiple times safely. It:

1. Creates all tables (if they do not exist).
2. Checks if `schema_version` exists in `_trace_meta`.
3. If not, sets it to "1".

This is verified in `tests/test_storage/test_schema.py:39-45`:

```python
def test_trace_meta_has_schema_version(self, session):
    row = session.execute(
        select(TraceMetaRow).where(TraceMetaRow.key == "schema_version")
    ).scalar_one_or_none()
    assert row is not None
    assert row.value == "1"
```

---

## Test Walkthrough

The data model and storage layers have comprehensive tests. Here are the key patterns demonstrated.

### Test Infrastructure (conftest.py)

```python
# tests/conftest.py

@pytest.fixture
def engine():
    eng = create_trace_engine(":memory:")
    init_db(eng)
    yield eng
    eng.dispose()

@pytest.fixture
def session(engine):
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    sess = SessionLocal()
    yield sess
    sess.rollback()
    sess.close()
```

Every test gets a fresh in-memory SQLite database. The session rolls back after each test, ensuring perfect isolation. This is fast (no disk I/O) and faithful (using the real SQLAlchemy stack, not mocks).

### Property-Based Testing with Hypothesis

**File:** `tests/strategies.py` + `tests/test_models/test_content.py:266-279`

```python
# tests/strategies.py
any_content = st.one_of(
    instruction_content,
    dialogue_content,
    tool_io_content,
    reasoning_content,
    artifact_content,
    output_content,
    freeform_content,
)

# tests/test_models/test_content.py
class TestRoundTrip:
    @given(content=any_content)
    def test_model_dump_validate_round_trip(self, content):
        dumped = content.model_dump()
        restored = type(content).model_validate(dumped)
        assert restored == content

    @given(content=any_content)
    def test_model_dump_json_mode_round_trip(self, content):
        dumped = content.model_dump(mode="json")
        restored = type(content).model_validate(dumped)
        assert restored == content
```

Hypothesis generates random instances of all 7 content types and verifies that serialization round-trips perfectly. This catches subtle bugs like:
- Fields that serialize but do not deserialize.
- Unicode handling issues.
- Edge cases in optional fields.

**Reusable pattern**: Define Hypothesis strategies for your domain models, then write property-based round-trip tests. This gives you vastly more coverage than hand-written examples.

### Blob Deduplication Test

```python
# tests/test_storage/test_repositories.py:80-95

def test_deduplication(self, blob_repo, session):
    hash_val = "dedup_hash_" + "0" * 53
    blob1 = _make_blob(hash_val)
    blob2 = _make_blob(hash_val)

    blob_repo.save_if_absent(blob1)
    blob_repo.save_if_absent(blob2)  # Should be a no-op

    count = session.execute(
        select(func.count()).where(BR.content_hash == hash_val)
    ).scalar()
    assert count == 1
```

This verifies the core content-addressable property: saving the same content twice results in exactly one row.

### Ancestor Chain Test

```python
# tests/test_storage/test_repositories.py:128-147

def test_get_ancestors_chain(self, commit_repo, blob_repo, sample_repo_id):
    blob = self._setup_blob(blob_repo)
    now = datetime.now(timezone.utc)

    c1 = _make_commit("c1_" + "a" * 61, sample_repo_id, blob.content_hash, created_at=now)
    c2 = _make_commit("c2_" + "b" * 61, sample_repo_id, blob.content_hash,
                      parent_hash=c1.commit_hash, created_at=now + timedelta(seconds=1))
    c3 = _make_commit("c3_" + "c" * 61, sample_repo_id, blob.content_hash,
                      parent_hash=c2.commit_hash, created_at=now + timedelta(seconds=2))

    commit_repo.save(c1)
    commit_repo.save(c2)
    commit_repo.save(c3)

    ancestors = commit_repo.get_ancestors(c3.commit_hash)
    assert len(ancestors) == 3
    assert ancestors[0].commit_hash == c3.commit_hash  # newest first
    assert ancestors[1].commit_hash == c2.commit_hash
    assert ancestors[2].commit_hash == c1.commit_hash  # oldest last
```

This demonstrates how `get_ancestors` walks the parent chain from head to root, returning newest-first order. The compiler reverses this to get root-first (chronological) order.

---

## Summary of Design Tradeoffs

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Content types | 7 typed Pydantic models | Raw dicts | Type safety, behavioral hints, validation |
| Custom type registry | Per-repo dict | Global module-level set | Isolation between repo instances |
| Blob storage PK | SHA-256 hash | Auto-increment ID | Content-addressable dedup |
| Blob payload column | Text (not JSON) | JSON | Exact serialization preservation for hash integrity |
| Parent/reply_to FK | SET NULL on delete | CASCADE or RESTRICT | Enables future garbage collection |
| Annotation storage | Append-only | In-place update | Full provenance history |
| Ancestor walking | Python loop | Recursive SQL CTE | Simpler, sufficient for linear chains |
| Session management | flush() in repos, commit() in Repo | commit() in repos | Enables batch() context manager |
| Schema versioning | _trace_meta table | File-based migrations | Lightweight, sufficient for early phases |

---

*Next: [01b - Engine Layer](01b-engine-layer.md) -- deep dive into hashing, tokens, commit engine, and compiler.*
