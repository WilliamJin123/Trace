# Phase 1 Deep Dive: The Engine Layer

The engine layer sits between storage and the public API. It contains all the business logic: how content is hashed, how tokens are counted, how commits are created with validation and budget enforcement, and how commit chains are compiled into LLM-ready messages.

---

## Table of Contents

1. [Content Hashing](#content-hashing)
2. [Token Counting](#token-counting)
3. [CommitEngine](#commitengine)
4. [DefaultContextCompiler](#defaultcontextcompiler)
5. [Operations: APPEND vs EDIT](#operations-append-vs-edit)
6. [Test Walkthrough](#test-walkthrough)

---

## Content Hashing

**File:** `src/tract/engine/hashing.py` (86 lines)

Trace uses SHA-256 hashing for two purposes: content-addressing blobs and computing commit identities. The hashing module provides three functions.

### Canonical JSON Serialization

```python
# src/tract/engine/hashing.py:19-36

def canonical_json(data: Any) -> bytes:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
```

**Why canonical JSON?** Python dicts do not guarantee key order across different construction paths (though CPython 3.7+ preserves insertion order). If two dicts have the same key-value pairs but different key orders, they should hash identically. Canonical JSON solves this with three rules:

1. **`sort_keys=True`**: Keys are sorted alphabetically at every nesting level.
2. **`separators=(",", ":")`**: No whitespace. Compact representation means the hash does not change if someone pretty-prints the JSON elsewhere.
3. **`ensure_ascii=False`**: Unicode characters are preserved as-is (not escaped to `\uXXXX`). This ensures `"hello"` hashes the same whether the string was created in Python, JavaScript, or any other language.

The output is `bytes` (UTF-8 encoded), ready to feed directly into hashlib.

**Test evidence** -- `tests/test_engine/test_hashing.py:21-59`:

```python
def test_sorted_keys(self):
    data = {"z": 1, "a": 2, "m": 3}
    result = json.loads(canonical_json(data))
    assert list(result.keys()) == ["a", "m", "z"]

def test_compact_separators(self):
    data = {"a": 1, "b": 2}
    result = canonical_json(data).decode("utf-8")
    assert result == '{"a":1,"b":2}'

def test_nested_dicts_sorted(self):
    data = {"outer": {"z": 1, "a": 2}}
    result = canonical_json(data).decode("utf-8")
    assert result.index('"a"') < result.index('"z"')
```

### Content Hash

```python
# src/tract/engine/hashing.py:39-48

def content_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()
```

Takes a content dict (already converted from a Pydantic model via `model_dump(mode="json")`) and returns a 64-character hex digest. This is the blob's primary key.

**Critical contract**: The input must be a plain dict, not a Pydantic model. The docstring explicitly states this: "Pydantic models must be converted to dicts via `model_dump(mode='json')` BEFORE passing to these functions." This ensures consistent serialization (Pydantic's JSON mode produces JSON-safe types like strings for datetimes).

**Key property: dict key order does not matter:**

```python
# tests/test_engine/test_hashing.py:84-88

def test_key_order_irrelevant(self):
    h1 = content_hash({"b": 2, "a": 1})
    h2 = content_hash({"a": 1, "b": 2})
    assert h1 == h2
```

This is what makes content-addressable storage work correctly. The same content always produces the same hash, regardless of how the dict was constructed.

**Property-based test** -- `tests/test_engine/test_hashing.py:90-106`:

```python
@given(
    data=st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(
            st.text(max_size=100),
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.booleans(),
        ),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=50)
def test_property_deterministic(self, data: dict):
    assert content_hash(data) == content_hash(data)
```

Hypothesis generates random dicts and verifies determinism. The `allow_nan=False, allow_infinity=False` exclusion is important because `NaN != NaN` in floating point, and `json.dumps` handles infinity/NaN inconsistently across platforms.

### Commit Hash

```python
# src/tract/engine/hashing.py:51-85

def commit_hash(
    content_hash: str,
    parent_hash: str | None,
    content_type: str,
    operation: str,
    timestamp_iso: str,
    reply_to: str | None = None,
) -> str:
    data: dict[str, Any] = {
        "content_hash": content_hash,
        "parent_hash": parent_hash,
        "content_type": content_type,
        "operation": operation,
        "timestamp_iso": timestamp_iso,
    }
    if reply_to is not None:
        data["reply_to"] = reply_to

    return hashlib.sha256(canonical_json(data)).hexdigest()
```

The commit hash is computed from a structured dict of identity-relevant fields. This is analogous to git's commit hash which includes tree hash, parent hash, author, timestamp, and message.

**What goes into the commit hash:**
- `content_hash`: The SHA-256 of the content blob.
- `parent_hash`: The previous commit's hash (or null for root).
- `content_type`: The content type discriminator.
- `operation`: "append" or "edit".
- `timestamp_iso`: ISO 8601 timestamp string.
- `reply_to` (conditionally): Only included when not None.

**What does NOT go into the commit hash:**
- `message`: Human-readable commit messages are metadata, not identity. Two commits with the same content at the same time but different messages would be unusual, but the message is not part of the identity.
- `metadata`: Arbitrary user data, not identity-defining.
- `token_count`: Derived from content, not independent data.
- `repo_id`: A commit's identity should be independent of which repo it lives in (important for future cross-repo operations).

**Why exclude `reply_to` when None?** If `reply_to` is `None`, the key is omitted entirely from the dict (not set to `null`). This means APPEND commits (which never have reply_to) produce the same hash regardless of whether you explicitly pass `reply_to=None` or omit it.

```python
# tests/test_engine/test_hashing.py:136-141

def test_reply_to_none_excluded_from_data(self):
    h1 = commit_hash("abc", None, "instruction", "append", "2024-01-01T00:00:00Z")
    h2 = commit_hash("abc", None, "instruction", "append", "2024-01-01T00:00:00Z", reply_to=None)
    assert h1 == h2
```

**Why SHA-256?** It is the standard choice for content-addressable storage (git uses SHA-1, but SHA-256 is stronger). The 64-character hex digest fits in a `String(64)` column. Collision probability is negligible for any practical number of commits (the birthday paradox threshold for SHA-256 is ~2^128 operations).

---

## Token Counting

**File:** `src/tract/engine/tokens.py` (95 lines)

### TiktokenCounter

```python
# src/tract/engine/tokens.py:10-78

class TiktokenCounter:
    def __init__(self, model: str = "gpt-4o", encoding_name: str | None = None) -> None:
        import tiktoken

        if encoding_name is not None:
            self._enc = tiktoken.get_encoding(encoding_name)
        else:
            try:
                self._enc = tiktoken.encoding_for_model(model)
            except KeyError:
                self._enc = tiktoken.get_encoding("o200k_base")

        self._encoding_name = self._enc.name
```

**Lazy import of tiktoken**: The `import tiktoken` is inside `__init__`, not at module level. This means the `tiktoken` package (which has a non-trivial import cost -- it downloads encoding files on first use) is only loaded when a counter is actually created. If you are using a custom counter, tiktoken is never imported.

**Encoding selection priority:**
1. If `encoding_name` is explicitly provided, use that encoding directly.
2. Otherwise, try to get the encoding for the specified `model` (default: "gpt-4o").
3. If the model is unknown, fall back to `o200k_base`.

This is tested in `tests/test_engine/test_tokens.py:81-91`:

```python
def test_explicit_encoding_name(self):
    counter = TiktokenCounter(encoding_name="cl100k_base")
    assert counter.encoding_name == "cl100k_base"

def test_unknown_model_falls_back(self):
    counter = TiktokenCounter(model="totally-unknown-model-xyz")
    assert counter.encoding_name == "o200k_base"
```

### count_text()

```python
def count_text(self, text: str) -> int:
    if not text:
        return 0
    return len(self._enc.encode(text))
```

Simple: encode the text with tiktoken, return the number of tokens. The empty-string guard avoids unnecessary work.

### count_messages()

```python
def count_messages(self, messages: list[dict]) -> int:
    if not messages:
        return 0

    total = 0
    for message in messages:
        total += 3  # per-message overhead
        for key, value in message.items():
            if isinstance(value, str):
                total += len(self._enc.encode(value))
            if key == "name":
                total += 1  # name field costs an extra token
    total += 3  # response primer
    return total
```

This implements the **OpenAI cookbook formula** for counting tokens in structured messages. The overhead structure:

- **3 tokens per message**: The `<|im_start|>`, role, and `<|im_sep|>` special tokens that frame each message in the chat format.
- **1 extra token for name field**: If a message has a `name` (like `"name": "Claude"`), it costs one additional token.
- **3 tokens for response primer**: The final `<|im_start|>assistant<|im_sep|>` that primes the model's response.

This means `count_messages()` returns a higher number than simply counting the text tokens. The difference is the **message framing overhead**. This is tested in `tests/test_engine/test_tokens.py:46-53`:

```python
def test_count_messages_includes_overhead(self):
    counter = TiktokenCounter()
    messages = [{"role": "user", "content": "Hello"}]
    text_tokens = counter.count_text("Hello") + counter.count_text("user")
    message_tokens = counter.count_messages(messages)
    assert message_tokens > text_tokens
```

**Why does this matter?** When you have a token budget (e.g., 4096 tokens for a model), you need to count not just the content but the framing overhead. A conversation with 100 short messages has 300+ tokens of overhead just from message framing. The compiled output uses `count_messages()` to give an accurate picture.

### NullTokenCounter

```python
class NullTokenCounter:
    def count_text(self, text: str) -> int:
        return 0

    def count_messages(self, messages: list[dict]) -> int:
        return 0
```

A testing stub that always returns 0. Useful when token counts are irrelevant to the test being run. Both counters satisfy the `TokenCounter` protocol:

```python
# tests/test_engine/test_tokens.py:17-19, 98-100

def test_implements_protocol(self):
    counter = TiktokenCounter()
    assert isinstance(counter, TokenCounter)

def test_implements_protocol(self):
    counter = NullTokenCounter()
    assert isinstance(counter, TokenCounter)
```

**Reusable pattern**: Always provide a null/stub implementation of your protocols alongside the real one. It makes testing dramatically easier and serves as documentation of the protocol's minimum contract.

---

## CommitEngine

**File:** `src/tract/engine/commit.py` (309 lines)

The CommitEngine is the **write path** for Trace. It orchestrates the entire commit creation workflow.

### Constructor and Dependencies

```python
# src/tract/engine/commit.py:63-90

class CommitEngine:
    def __init__(
        self,
        commit_repo: CommitRepository,
        blob_repo: BlobRepository,
        ref_repo: RefRepository,
        annotation_repo: AnnotationRepository,
        token_counter: TokenCounter,
        repo_id: str,
        token_budget: TokenBudgetConfig | None = None,
    ) -> None:
```

The engine depends on four repositories, a token counter, and optional budget config. All dependencies are injected through the constructor. The engine never creates its own dependencies -- this is the Dependency Injection pattern that makes testing straightforward.

### The create_commit() Workflow

The `create_commit()` method (`src/tract/engine/commit.py:92-236`) is a 13-step pipeline. Let's walk through each step.

**Step 1: Serialize content**

```python
content_dict = content.model_dump(mode="json")
content_type = content_dict.get("content_type", "unknown")
```

Convert the Pydantic model to a JSON-safe dict. `mode="json"` ensures all types are JSON-serializable (e.g., datetimes become ISO strings).

**Step 2: Compute content hash**

```python
c_hash = compute_content_hash(content_dict)
```

SHA-256 of the canonical JSON. This becomes the blob's primary key.

**Step 3: Count tokens**

```python
text = extract_text_from_content(content)
token_count = self._token_counter.count_text(text)
```

The `extract_text_from_content()` helper (`src/tract/engine/commit.py:40-60`) handles the different field names across content types:

```python
def extract_text_from_content(content: BaseModel) -> str:
    if hasattr(content, "text"):
        return content.text          # InstructionContent, DialogueContent, etc.
    if hasattr(content, "content") and isinstance(content.content, str):
        return content.content       # ArtifactContent
    if hasattr(content, "payload"):
        return json.dumps(content.payload, sort_keys=True)  # ToolIOContent, FreeformContent
    return ""
```

**Why not a method on the content models?** Because content models are pure data -- they should not know about token counting. The extraction logic belongs in the engine. This keeps the models clean and the engine in control of how text is interpreted.

This helper is thoroughly tested (`tests/test_engine/test_commit.py:60-84`):

```python
class TestExtractText:
    def test_instruction(self):
        assert extract_text_from_content(InstructionContent(text="hello")) == "hello"

    def test_artifact(self):
        assert extract_text_from_content(
            ArtifactContent(artifact_type="code", content="print()")
        ) == "print()"

    def test_tool_io(self):
        result = extract_text_from_content(
            ToolIOContent(tool_name="search", direction="call", payload={"q": "test"})
        )
        assert "test" in result
```

**Step 4: Store blob (content-addressable dedup)**

```python
now = datetime.now(timezone.utc)
blob = BlobRow(
    content_hash=c_hash,
    payload_json=json.dumps(content_dict, sort_keys=True, ensure_ascii=False),
    byte_size=len(json.dumps(content_dict).encode("utf-8")),
    token_count=token_count,
    created_at=now,
)
self._blob_repo.save_if_absent(blob)
```

The blob is created with the hash as its PK. `save_if_absent()` checks for existing content -- if the hash already exists, this is a no-op. This is the deduplication mechanism.

Tested in `tests/test_engine/test_commit.py:122-135`:

```python
def test_blob_deduplication(self, commit_engine, repos):
    content = InstructionContent(text="You are a helpful assistant.")
    c1 = commit_engine.create_commit(content, message="first")
    c2 = commit_engine.create_commit(content, message="second")

    assert c1.content_hash == c2.content_hash    # Same content hash
    assert c1.commit_hash != c2.commit_hash      # Different commit hashes
```

**Step 5: Get current HEAD**

```python
parent_hash = self._ref_repo.get_head(self._repo_id)
```

The current HEAD becomes the new commit's parent. If this is the first commit, HEAD is None, so parent_hash is None (root commit).

**Step 6: Check token budget**

```python
if self._token_budget and self._token_budget.max_tokens is not None:
    total_tokens = token_count
    if parent_hash is not None:
        ancestors = self._commit_repo.get_ancestors(parent_hash)
        for ancestor in ancestors:
            total_tokens += ancestor.token_count

    if total_tokens > self._token_budget.max_tokens:
        if self._token_budget.action == BudgetAction.REJECT:
            raise BudgetExceededError(total_tokens, self._token_budget.max_tokens)
        elif self._token_budget.action == BudgetAction.WARN:
            logger.warning(...)
        elif self._token_budget.action == BudgetAction.CALLBACK:
            if self._token_budget.callback is not None:
                self._token_budget.callback(total_tokens, self._token_budget.max_tokens)
```

Budget checking sums the new commit's tokens with all ancestor tokens. The three enforcement modes:

1. **REJECT**: Raise `BudgetExceededError` with the actual and max token counts.
2. **WARN**: Log a warning but proceed with the commit.
3. **CALLBACK**: Call the user's callback function for custom handling.

Tested in `tests/test_engine/test_commit.py:203-269`:

```python
def test_reject_mode_raises(self, session, sample_repo_id):
    budget = TokenBudgetConfig(max_tokens=1, action=BudgetAction.REJECT)
    engine = CommitEngine(..., token_budget=budget)

    with pytest.raises(BudgetExceededError) as exc_info:
        engine.create_commit(InstructionContent(text="This text definitely has more than 1 token"))
    assert exc_info.value.max_tokens == 1

def test_callback_mode_calls_callback(self, session, sample_repo_id):
    callback_calls: list[tuple[int, int]] = []
    budget = TokenBudgetConfig(
        max_tokens=1,
        action=BudgetAction.CALLBACK,
        callback=lambda current, max_t: callback_calls.append((current, max_t)),
    )
    engine = CommitEngine(..., token_budget=budget)
    engine.create_commit(InstructionContent(text="This text definitely has more than 1 token"))

    assert len(callback_calls) == 1
    assert callback_calls[0][1] == 1
    assert callback_calls[0][0] > 1
```

**Step 7-8: Generate timestamp and compute commit hash**

```python
timestamp = datetime.now(timezone.utc)
timestamp_iso = timestamp.isoformat()

c_commit_hash = compute_commit_hash(
    content_hash=c_hash,
    parent_hash=parent_hash,
    content_type=content_type,
    operation=operation_value,
    timestamp_iso=timestamp_iso,
    reply_to=reply_to,
)
```

The commit hash includes the timestamp, which means two commits with identical content will have different hashes (because they are created at different times with different parent pointers).

**Step 9: Validate edit constraints**

```python
if operation == CommitOperation.EDIT:
    if reply_to is None:
        raise EditTargetError("EDIT operation requires reply_to to be set")
    target_commit = self._commit_repo.get(reply_to)
    if target_commit is None:
        raise EditTargetError(f"EDIT target commit not found: {reply_to}")
    if target_commit.operation == CommitOperation.EDIT:
        raise EditTargetError(f"Cannot edit an EDIT commit: {reply_to}")
```

Three constraints on EDIT operations:

1. **`reply_to` is required**: You must specify what you are editing.
2. **Target must exist**: You cannot edit a nonexistent commit.
3. **Target must not be an EDIT**: You cannot "edit an edit." Edits always target the original APPEND commit. If you want to change an edit, create a new edit targeting the same original.

**Why no "edit of edit"?** It would create ambiguous resolution chains. If commit A is edited by B, and B is edited by C, what does the compiler show for A's position? Is it C (the edit of the edit)? Or B (the direct edit of A)? The rule "edits always target APPEND commits" keeps resolution simple: there is at most one level of indirection.

Tested in `tests/test_engine/test_commit.py:170-185`:

```python
def test_edit_targeting_edit_raises(self, commit_engine):
    original = commit_engine.create_commit(DialogueContent(role="user", text="Hello"))
    edit = commit_engine.create_commit(
        DialogueContent(role="user", text="Hello edited"),
        operation=CommitOperation.EDIT,
        reply_to=original.commit_hash,
    )
    with pytest.raises(EditTargetError):
        commit_engine.create_commit(
            DialogueContent(role="user", text="Hello re-edited"),
            operation=CommitOperation.EDIT,
            reply_to=edit.commit_hash,
        )
```

**Steps 10-11: Save commit and update HEAD**

```python
commit_row = CommitRow(
    commit_hash=c_commit_hash,
    repo_id=self._repo_id,
    parent_hash=parent_hash,
    content_hash=c_hash,
    content_type=content_type,
    operation=operation,
    reply_to=reply_to,
    message=message,
    token_count=token_count,
    metadata_json=metadata,
    created_at=timestamp,
)
self._commit_repo.save(commit_row)
self._ref_repo.update_head(self._repo_id, c_commit_hash)
```

The commit row is saved and HEAD is updated in the same transaction (both call `flush()`, not `commit()`). The actual database commit happens in the `Repo` layer.

**Step 12: Auto-create priority annotation**

```python
default_priority = DEFAULT_TYPE_PRIORITIES.get(content_type, Priority.NORMAL)
if default_priority != Priority.NORMAL:
    annotation = AnnotationRow(
        repo_id=self._repo_id,
        target_hash=c_commit_hash,
        priority=default_priority,
        reason=f"Default priority for {content_type}",
        created_at=timestamp,
    )
    self._annotation_repo.save(annotation)
```

Only non-NORMAL defaults trigger annotation creation. Currently, only `instruction` has a non-NORMAL default (PINNED). This means instruction commits automatically get a PINNED annotation, ensuring they are never filtered out during compilation.

**Step 13: Return CommitInfo**

The method constructs and returns a `CommitInfo` DTO with all the commit data. This is what the user receives.

### The annotate() Method

```python
# src/tract/engine/commit.py:252-292

def annotate(self, target_hash: str, priority: Priority, reason: str | None = None) -> PriorityAnnotation:
    target = self._commit_repo.get(target_hash)
    if target is None:
        raise CommitNotFoundError(target_hash)

    now = datetime.now(timezone.utc)
    annotation = AnnotationRow(
        repo_id=self._repo_id,
        target_hash=target_hash,
        priority=priority,
        reason=reason,
        created_at=now,
    )
    self._annotation_repo.save(annotation)

    return PriorityAnnotation(...)
```

Validates that the target commit exists, then appends a new annotation row. The CommitNotFoundError is raised if the target does not exist -- tested in `tests/test_engine/test_commit.py:303-306`.

---

## DefaultContextCompiler

**File:** `src/tract/engine/compiler.py` (352 lines)

The compiler is the **read path** for Trace. It converts a commit chain into `CompiledContext` -- a list of `Message` objects ready for an LLM API.

### The compile() Pipeline

```python
# src/tract/engine/compiler.py:63-129

def compile(self, repo_id, head_hash, *, as_of=None, up_to=None, include_edit_annotations=False):
    if as_of is not None and up_to is not None:
        raise ValueError("Cannot specify both as_of and up_to")

    # Step 1: Walk commit chain
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
    messages_dicts = [{"role": m.role, "content": m.content, ...} for m in messages]
    token_count = self._token_counter.count_messages(messages_dicts)

    return CompiledContext(messages=messages, token_count=token_count, ...)
```

Eight steps. Let's examine each.

### Step 1: Walking the Chain

```python
# src/tract/engine/compiler.py:131-157

def _walk_chain(self, head_hash, *, as_of=None, up_to=None):
    ancestors = self._commit_repo.get_ancestors(head_hash)
    # ancestors is head-first (newest first), reverse to root-first
    commits = list(reversed(ancestors))

    # Apply up_to filter
    if up_to is not None:
        filtered = []
        for c in commits:
            filtered.append(c)
            if c.commit_hash == up_to:
                break
        commits = filtered

    # Apply as_of filter
    if as_of is not None:
        as_of_naive = _normalize_dt(as_of)
        commits = [c for c in commits if _normalize_dt(c.created_at) <= as_of_naive]

    return commits
```

The chain is walked from HEAD to root (via `get_ancestors`), then **reversed** to root-to-head order. This is the chronological order -- the order in which commits were created. The LLM API expects messages in chronological order: system prompt first, then user/assistant turns.

**The `_normalize_dt()` helper** (`src/tract/engine/compiler.py:31-33`):

```python
def _normalize_dt(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
```

**Why strip timezone info?** SQLite stores datetimes as naive (no timezone) strings. When Python creates `datetime.now(timezone.utc)` and stores it, SQLAlchemy strips the timezone on write and returns a naive datetime on read. Comparing a timezone-aware `as_of` parameter with naive database timestamps would raise `TypeError`. Normalizing both to naive makes the comparison work.

This is a known SQLite/SQLAlchemy quirk and is called out in the project memory.

### Step 2: Edit Resolution Map

```python
# src/tract/engine/compiler.py:159-180

def _build_edit_map(self, commits, *, as_of=None):
    edit_map: dict[str, CommitRow] = {}
    for c in commits:
        if c.operation == CommitOperation.EDIT and c.reply_to is not None:
            if as_of is not None and _normalize_dt(c.created_at) > _normalize_dt(as_of):
                continue
            existing = edit_map.get(c.reply_to)
            if existing is None or c.created_at > existing.created_at:
                edit_map[c.reply_to] = c
    return edit_map
```

The edit map answers: "For each original commit, what is the latest edit that replaces it?" If multiple edits target the same commit, the one with the latest `created_at` wins. The map is keyed by the original commit's hash, and the value is the edit commit row.

Tested in `tests/test_engine/test_compiler.py:215-237`:

```python
def test_multiple_edits_latest_wins(self, commit_engine, compiler):
    original = commit_engine.create_commit(DialogueContent(role="user", text="Version 1"))
    commit_engine.create_commit(
        DialogueContent(role="user", text="Version 2"),
        operation=CommitOperation.EDIT, reply_to=original.commit_hash,
    )
    commit_engine.create_commit(
        DialogueContent(role="user", text="Version 3"),
        operation=CommitOperation.EDIT, reply_to=original.commit_hash,
    )

    head = commit_engine._ref_repo.get_head(REPO_ID)
    result = compiler.compile(REPO_ID, head)
    assert result.messages[0].content == "Version 3"  # Latest edit wins
```

### Step 3: Priority Map

```python
# src/tract/engine/compiler.py:182-211

def _build_priority_map(self, commits, *, as_of=None):
    commit_hashes = [c.commit_hash for c in commits]
    annotations = self._annotation_repo.batch_get_latest(commit_hashes)

    priority_map: dict[str, Priority] = {}
    for c in commits:
        annotation = annotations.get(c.commit_hash)
        if annotation is not None:
            if as_of is not None and _normalize_dt(annotation.created_at) > _normalize_dt(as_of):
                annotation = None
        if annotation is not None:
            priority_map[c.commit_hash] = annotation.priority
        else:
            priority_map[c.commit_hash] = DEFAULT_TYPE_PRIORITIES.get(
                c.content_type, Priority.NORMAL
            )
    return priority_map
```

Uses `batch_get_latest()` to fetch all annotations in one query (avoiding N+1). For each commit:
1. If an annotation exists (and is within the `as_of` boundary), use its priority.
2. Otherwise, fall back to `DEFAULT_TYPE_PRIORITIES` (e.g., instruction -> PINNED, dialogue -> NORMAL).

### Step 4: Effective Commit List

```python
# src/tract/engine/compiler.py:213-233

def _build_effective_commits(self, commits, edit_map, priority_map):
    effective: list[CommitRow] = []
    for c in commits:
        if c.operation == CommitOperation.EDIT:
            continue           # EDIT commits are substitutions, not standalone
        if priority_map.get(c.commit_hash) == Priority.SKIP:
            continue           # SKIP priority excludes from compilation
        effective.append(c)
    return effective
```

Two filters:
1. **EDIT commits are excluded** as standalone messages. They participate only through the edit_map (as replacements for the original).
2. **SKIP priority excludes** the commit entirely.

The result is the list of commits that will appear as messages in the output.

### Step 5-6: Building Messages

```python
# src/tract/engine/compiler.py:235-273

def _build_messages(self, effective_commits, edit_map, include_edit_annotations):
    messages: list[Message] = []

    for c in effective_commits:
        source_commit = edit_map.get(c.commit_hash, c)  # Use edit content if available
        blob = self._blob_repo.get(source_commit.content_hash)
        content_data = json.loads(blob.payload_json)
        content_type = content_data.get("content_type", "unknown")

        role = self._map_role(content_type, content_data)
        text = self._extract_message_text(content_type, content_data)

        if include_edit_annotations and c.commit_hash in edit_map:
            text += " [edited]"

        name = content_data.get("name") if content_type == "dialogue" else None
        messages.append(Message(role=role, content=text, name=name))

    return messages
```

For each effective commit:
1. **Check the edit map**: If this commit has been edited, use the edit's content instead of the original.
2. **Load the blob**: Deserialize the JSON payload.
3. **Map role**: Determine the LLM message role.
4. **Extract text**: Get the display text from the content.
5. **Add edit annotation** (optional): Append `" [edited]"` if requested.

### Role Mapping

```python
# src/tract/engine/compiler.py:275-302

def _map_role(self, content_type, content_data):
    # 1. Override map
    if content_type in self._type_to_role_override:
        return self._type_to_role_override[content_type]

    # 2. DialogueContent uses its own role field
    if content_type == "dialogue":
        return content_data.get("role", "user")

    # 3. ToolIOContent always maps to "tool"
    if content_type == "tool_io":
        return "tool"

    # 4. BUILTIN_TYPE_HINTS default_role
    hints = BUILTIN_TYPE_HINTS.get(content_type)
    if hints is not None:
        return hints.default_role

    # 5. Fallback
    return "assistant"
```

Five-level priority for role resolution:
1. User-provided override map (for custom mappings).
2. DialogueContent uses its own `role` field -- a user message is "user", an assistant message is "assistant."
3. ToolIOContent is always "tool" (LLM APIs expect tool results with role "tool").
4. Built-in type hints provide defaults (instruction -> "system", reasoning -> "assistant", etc.).
5. Unknown types fall back to "assistant."

This is comprehensively tested in `tests/test_engine/test_compiler.py:140-184`.

### Message Aggregation

```python
# src/tract/engine/compiler.py:329-351

def _aggregate_messages(self, messages):
    if not messages:
        return messages

    aggregated: list[Message] = []
    current = messages[0]

    for msg in messages[1:]:
        if msg.role == current.role:
            new_content = current.content + "\n\n" + msg.content
            current = Message(role=current.role, content=new_content, name=current.name)
        else:
            aggregated.append(current)
            current = msg

    aggregated.append(current)
    return aggregated
```

Consecutive messages with the same role are merged by concatenating their content with `\n\n`. This is a common LLM API requirement: some APIs reject consecutive messages with the same role.

Tested in `tests/test_engine/test_compiler.py:397-413`:

```python
def test_aggregation_preserves_boundaries(self, commit_engine, compiler):
    """user-user-assistant-user becomes 3 messages (agg, single, single)."""
    commit_engine.create_commit(DialogueContent(role="user", text="A"))
    commit_engine.create_commit(DialogueContent(role="user", text="B"))
    commit_engine.create_commit(DialogueContent(role="assistant", text="C"))
    c4 = commit_engine.create_commit(DialogueContent(role="user", text="D"))

    result = compiler.compile(REPO_ID, c4.commit_hash)

    assert len(result.messages) == 3
    assert "A" in result.messages[0].content
    assert "B" in result.messages[0].content  # Merged with A
    assert result.messages[1].content == "C"   # Not merged (different role)
    assert result.messages[2].content == "D"   # Not merged (role boundary)
```

### Token Counting on Compiled Output

```python
# Step 8 in compile()
messages_dicts = [
    {"role": m.role, "content": m.content}
    if m.name is None
    else {"role": m.role, "content": m.content, "name": m.name}
    for m in messages
]
token_count = self._token_counter.count_messages(messages_dicts)
```

The token count on `CompiledContext` reflects the **compiled output including message overhead**, not the raw content tokens. This is the number that matters when checking against a model's context window limit.

Tested in `tests/test_engine/test_compiler.py:430-441`:

```python
def test_token_count_reflects_compiled_output(self, commit_engine, compiler):
    c1 = commit_engine.create_commit(InstructionContent(text="System prompt."))
    c2 = commit_engine.create_commit(DialogueContent(role="user", text="Hello!"))

    result = compiler.compile(REPO_ID, c2.commit_hash)

    counter = TiktokenCounter()
    raw_text_tokens = counter.count_text("System prompt.") + counter.count_text("Hello!")
    assert result.token_count > raw_text_tokens  # Overhead included
```

---

## Operations: APPEND vs EDIT

There are exactly two commit operations:

### APPEND

The default operation. Creates a new commit at the head of the chain. The content is new information being added to the context.

```python
repo.commit(DialogueContent(role="user", text="What is the weather?"))
# Creates: APPEND commit with parent = previous HEAD
```

### EDIT

A replacement operation. Creates a new commit that specifies "this content should replace the content at position X." The `reply_to` field points to the original commit being replaced.

```python
# Create original
c1 = repo.commit(InstructionContent(text="You are a helpful assistant."))

# Edit it
repo.commit(
    InstructionContent(text="You are a concise, helpful assistant."),
    operation=CommitOperation.EDIT,
    reply_to=c1.commit_hash,
)
```

**How edits compose during compilation:**

1. The original APPEND commit still exists at its position in the chain.
2. The EDIT commit also exists in the chain (later, with the original as its parent or a descendant of the original as its parent).
3. During compilation, the compiler builds an `edit_map: {original_hash -> edit_commit}`.
4. When processing the original's position, the compiler uses the edit's content instead.
5. The EDIT commit itself does NOT appear as a standalone message.

This means the compiled output shows the edited content at the original's chronological position. The conversation flow is preserved, but the content is updated.

**Visual example:**

```
Commit chain:  [root] -> [instruction: "Be helpful"] -> [user: "Hi"] -> [EDIT of instruction: "Be concise"]
                  |                |                        |                      |
Position:         1                2                        3                      4

Compiled output (root -> head):
  Position 1: (nothing - root not shown)
  Position 2: role=system, content="Be concise"  <-- EDIT content substituted
  Position 3: role=user, content="Hi"
  Position 4: (EDIT commit excluded as standalone)

Result: [system: "Be concise", user: "Hi"]
```

**Why not destructive edits?** You could modify the original commit's content in place. But that would:
- Violate immutability (the content hash would change, breaking the content-addressable property).
- Destroy history (you could not see what the original content was).
- Complicate branching (future phases) because different branches might see different versions.

The EDIT operation preserves all information while still producing the desired compiled output.

---

## Test Walkthrough

### Test Infrastructure for the Engine

```python
# tests/test_engine/test_commit.py:38-57

@pytest.fixture
def commit_engine(session, sample_repo_id):
    commit_repo = SqliteCommitRepository(session)
    blob_repo = SqliteBlobRepository(session)
    ref_repo = SqliteRefRepository(session)
    annot_repo = SqliteAnnotationRepository(session)
    counter = TiktokenCounter()
    return CommitEngine(commit_repo, blob_repo, ref_repo, annot_repo, counter, sample_repo_id)

@pytest.fixture
def repos(session):
    return {
        "commit": SqliteCommitRepository(session),
        "blob": SqliteBlobRepository(session),
        "ref": SqliteRefRepository(session),
        "annotation": SqliteAnnotationRepository(session),
    }
```

Tests use real SQLite (in-memory) with real repository implementations. This is an integration test style that tests the engine against the actual storage layer. The `repos` fixture provides direct access to repositories for verifying side effects (e.g., checking that a blob was stored).

### Compiler Test Stack

```python
# tests/test_engine/test_compiler.py:41-61

@pytest.fixture
def stack(session):
    commit_repo = SqliteCommitRepository(session)
    blob_repo = SqliteBlobRepository(session)
    ref_repo = SqliteRefRepository(session)
    annot_repo = SqliteAnnotationRepository(session)
    counter = TiktokenCounter()

    engine = CommitEngine(commit_repo, blob_repo, ref_repo, annot_repo, counter, REPO_ID)
    compiler = DefaultContextCompiler(commit_repo, blob_repo, annot_repo, counter)

    return {"engine": engine, "compiler": compiler, ...}
```

Compiler tests create both an engine (to create commits) and a compiler (to compile them). They share the same session, so commits created by the engine are visible to the compiler. This is the same sharing pattern used in production.

### A Complete Test Scenario

Here is the full flow of `test_edit_replaces_original` from `tests/test_engine/test_compiler.py:195-213`:

```python
def test_edit_replaces_original(self, commit_engine, compiler):
    # 1. Create an original user message
    original = commit_engine.create_commit(
        DialogueContent(role="user", text="Hello"),
        message="original",
    )
    # 2. Create an edit targeting the original
    commit_engine.create_commit(
        DialogueContent(role="user", text="Hello, world!"),
        operation=CommitOperation.EDIT,
        reply_to=original.commit_hash,
        message="edit",
    )
    # 3. Get HEAD and compile
    head = commit_engine._ref_repo.get_head(REPO_ID)
    result = compiler.compile(REPO_ID, head)

    # 4. Verify: one message with the edited content
    assert len(result.messages) == 1
    assert result.messages[0].content == "Hello, world!"
```

What happens under the hood:

1. CommitEngine creates commit A (APPEND, "Hello") -- HEAD moves to A.
2. CommitEngine creates commit B (EDIT, "Hello, world!", reply_to=A) -- HEAD moves to B.
3. Compiler walks: B -> A (newest-first), reverses to A -> B (root-first).
4. Edit map: `{A.hash: B}` (B replaces A).
5. Effective commits: [A] (B is EDIT, excluded as standalone).
6. Building message for A: edit_map has A -> B, so use B's content: "Hello, world!".
7. Result: one message, "Hello, world!".

---

## Summary of Design Tradeoffs

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Hashing algorithm | SHA-256 | SHA-1, xxHash, BLAKE3 | Industry standard for content-addressing; 64-char hex fits column |
| Canonical JSON | sorted keys + compact | Deterministic serialization library | Sufficient for JSON; no extra dependency |
| Token counting | tiktoken (lazy import) | sentence-piece, custom | Matches OpenAI API token model; lazy import avoids cost if unused |
| Edit resolution | Latest edit wins | Explicit version chain | Simpler; avoids edit-of-edit complexity |
| No edit-of-edit | Enforce at creation | Allow with resolution rules | Keeps resolution algorithm O(n) with simple map lookup |
| Budget enforcement | 3 modes (warn/reject/callback) | Single mode | Different users need different behaviors; callbacks enable custom logic |
| Ancestor walking | Python loop | Recursive SQL CTE | Simpler; acceptable for Phase 1 chain lengths |
| Token count on compile | count_messages() with overhead | Raw text token sum | Accurate for LLM API budgeting |

---

*Next: [01c - Repo API and Design Patterns](01c-repo-api-and-design-patterns.md) -- the public facade, DI, batch operations, caching, and protocols.*
