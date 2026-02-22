# Phase 8: Format & Commit Shorthand - Research

**Researched:** 2026-02-19
**Domain:** Python SDK API design, LLM message format conversion, convenience methods
**Confidence:** HIGH

## Summary

Phase 8 adds three categories of convenience features to the existing Tract API: (1) output format methods on `CompiledContext` (`to_dicts()`, `to_openai()`, `to_anthropic()`), (2) shorthand commit methods on `Tract` (`system()`, `user()`, `assistant()`), and (3) auto-generated commit messages when `message=` is omitted.

All changes are additive to existing classes. No new modules, no new dependencies, no schema changes, no storage modifications. The primary technical challenge is the Anthropic format conversion, which requires extracting system messages from the message list and structuring them as a separate top-level parameter.

**Primary recommendation:** Implement in three layers -- (1) `CompiledContext` format methods first (pure functions on frozen dataclass, trivial to test), (2) `Tract` shorthand methods second (thin wrappers around `commit()`), (3) auto-generated commit messages last (requires content introspection logic already present in `extract_text_from_content`).

## Standard Stack

### Core

No new libraries needed. All implementation uses existing project infrastructure.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.10+ | `dataclasses`, `typing` | Already the project baseline |
| Pydantic | existing | Content model validation | Already in use for all content types |

### Supporting

No new supporting libraries required. This phase is pure Python convenience methods.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Methods on CompiledContext | Standalone converter functions | Methods are more discoverable, align with ToolDefinition.to_openai() pattern already in codebase |
| Auto-generated commit messages in Tract.commit() | Separate utility function | Inline in commit() is cleaner; keeps the logic where it's used |

**Installation:** No new packages.

## Architecture Patterns

### Where Code Goes

All changes touch exactly three existing files plus `__init__.py`:

```
src/tract/
  protocols.py           # Add to_dicts(), to_openai(), to_anthropic() on CompiledContext
  tract.py               # Add system(), user(), assistant() methods; modify commit() for auto-message
  __init__.py            # No new exports needed (CompiledContext already exported)
```

No new files. No new modules. No new packages.

### Pattern 1: Methods on Frozen Dataclass

**What:** `CompiledContext` is `@dataclass(frozen=True)`. Methods can be added freely -- frozen only prevents attribute mutation, not method calls.

**When to use:** For `to_dicts()`, `to_openai()`, `to_anthropic()`.

**Key insight:** This pattern is already used in the codebase. `CompileSnapshot` is also frozen and has no methods, but `ToolDefinition` (in `toolkit/models.py`) has both `to_openai()` and `to_anthropic()` methods. The naming convention is established.

**Example:**
```python
# On CompiledContext (protocols.py)
@dataclass(frozen=True)
class CompiledContext:
    messages: list[Message] = field(default_factory=list)
    # ... existing fields ...

    def to_dicts(self) -> list[dict[str, str]]:
        """Convert messages to list of dicts with role/content keys."""
        result = []
        for m in self.messages:
            d: dict[str, str] = {"role": m.role, "content": m.content}
            if m.name is not None:
                d["name"] = m.name
            result.append(d)
        return result
```

### Pattern 2: Thin Wrapper Methods on Tract

**What:** `t.system()`, `t.user()`, `t.assistant()` are shorthand that construct the appropriate content model and call `commit()`.

**When to use:** For CORE-01 shorthand commit methods.

**Key insight:** These methods must pass through `commit()` so that all existing behavior (cache updates, policy evaluation, orchestrator triggers, budget enforcement) fires correctly. They are purely sugar.

**Example:**
```python
# On Tract (tract.py)
def system(
    self,
    text: str,
    *,
    message: str | None = None,
    metadata: dict | None = None,
) -> CommitInfo:
    """Commit a system instruction (shorthand for InstructionContent)."""
    from tract.models.content import InstructionContent
    return self.commit(
        InstructionContent(text=text),
        message=message,
        metadata=metadata,
    )
```

### Pattern 3: Auto-Generated Commit Messages

**What:** When `message=None` on `commit()`, generate a descriptive message from the content.

**When to use:** For CORE-03.

**Key insight:** `extract_text_from_content()` already exists in `engine/commit.py` and extracts text from any content type. The auto-message logic truncates this text into a short commit message. This should be done in `Tract.commit()` (the facade), not in `CommitEngine.create_commit()`, to keep the engine layer unchanged and avoid breaking existing tests.

**Example:**
```python
# In Tract.commit(), before calling self._commit_engine.create_commit():
if message is None:
    from tract.engine.commit import extract_text_from_content
    text = extract_text_from_content(content)
    content_type = content.model_dump(mode="json").get("content_type", "unknown")
    # Generate: "dialogue: Hello, how are..." (truncated to ~72 chars)
    message = _auto_message(content_type, text)
```

### Anti-Patterns to Avoid

- **Do NOT modify CommitEngine for auto-messages:** The engine is the write path for all commits including merge commits, compression commits, etc. Auto-message logic belongs in the Tract facade only.
- **Do NOT make shorthand methods bypass commit():** Every shorthand must call `self.commit()` to preserve cache/policy/trigger behavior.
- **Do NOT make to_anthropic() lossy for non-system roles:** Messages with role="tool" or other unusual roles should be included as-is (Anthropic supports custom roles in some contexts, and users may be using non-standard roles).
- **Do NOT add provider-specific content block formatting:** The `to_anthropic()` method should produce the simple `{"role": "user", "content": "text"}` format, not the `[{"type": "text", "text": "..."}]` content block format. Users who need content blocks are already in the "full control" tier.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Extracting text from content models | New extraction function | `extract_text_from_content()` in `engine/commit.py` | Already handles all 8 content types including edge cases |
| Content type to role mapping | Duplicate role mapping | Compiler's `_map_role()` and `BUILTIN_TYPE_HINTS` | Authoritative role mapping already exists |
| Commit creation with all side-effects | Direct engine calls | `Tract.commit()` | Handles cache, policy, triggers, validation |

**Key insight:** The entire point of this phase is convenience wrappers. There is no novel logic to implement -- only proper delegation to existing infrastructure.

## Common Pitfalls

### Pitfall 1: Anthropic System Message Extraction
**What goes wrong:** The Anthropic API does NOT support `role: "system"` in the messages array. System messages must be extracted to a separate top-level `system` parameter.
**Why it happens:** OpenAI and most OpenAI-compatible APIs (Cerebras, Together, etc.) put system messages inline. Anthropic is the outlier.
**How to avoid:** `to_anthropic()` must return a dict with `{"system": str | None, "messages": list[dict]}` structure, NOT a flat list of messages. Multiple system messages should be concatenated with newlines.
**Warning signs:** Tests that only check `to_anthropic()` returns a list -- it must return a dict.

### Pitfall 2: Frozen Dataclass Return Type for to_anthropic()
**What goes wrong:** Since `to_dicts()` returns `list[dict]` and `to_openai()` returns `list[dict]`, developers might assume `to_anthropic()` returns the same type. But it MUST return a dict with both `system` and `messages` keys.
**Why it happens:** Anthropic's API structure is fundamentally different from OpenAI's.
**How to avoid:** Clear type annotations, distinct return type for `to_anthropic()`, and documentation.

### Pitfall 3: Auto-Message Breaking Existing Tests
**What goes wrong:** If auto-message generation is placed in `CommitEngine.create_commit()`, every existing test that checks `message=None` will start seeing auto-generated messages.
**Why it happens:** CommitEngine is called by merge, compression, and other internal code paths that intentionally pass `message=None`.
**How to avoid:** Auto-message logic goes in `Tract.commit()` only, before delegating to the engine. The engine's `create_commit(message=None)` behavior stays unchanged.

### Pitfall 4: Message Name Field Handling
**What goes wrong:** The `Message` dataclass has an optional `name` field (used by `DialogueContent` for multi-participant conversations). Forgetting to include it in `to_dicts()` / `to_openai()` silently drops information.
**Why it happens:** Most messages don't use `name`, so it's easy to overlook.
**How to avoid:** Include `name` in output dicts when it is not None. The compiler already handles this (see line 128-133 in `compiler.py`).

### Pitfall 5: Shorthand Methods and EDIT Operations
**What goes wrong:** `t.system("text")` always creates APPEND commits. Users might expect to be able to edit via shorthand.
**Why it happens:** Shorthand methods intentionally only support the common case (APPEND).
**How to avoid:** Document that for EDIT operations, users should use `t.commit()` directly. The shorthand methods should not accept `operation` or `edit_target` parameters -- that would defeat the purpose of being simple.

### Pitfall 6: Cache Invalidation with New CompiledContext Methods
**What goes wrong:** Nothing, actually. `to_dicts()`, `to_openai()`, `to_anthropic()` are pure read-only transformations on the already-compiled result. They don't interact with the cache at all.
**Why it happens:** Developers might worry about cache coherence, but these methods are post-compile consumers, not compile-path participants.
**How to avoid:** No special handling needed. This is a non-pitfall worth documenting to prevent unnecessary defensive coding.

## Code Examples

### CompiledContext.to_dicts() (FMT-01)

```python
# Source: Derived from existing compiler.py line 128-133 pattern
def to_dicts(self) -> list[dict[str, str]]:
    """Convert to list of dicts with role/content keys.

    Returns dicts ready for most LLM APIs (OpenAI, Cerebras, Together, etc.).
    Includes 'name' key when present.
    """
    result: list[dict[str, str]] = []
    for m in self.messages:
        d: dict[str, str] = {"role": m.role, "content": m.content}
        if m.name is not None:
            d["name"] = m.name
        result.append(d)
    return result
```

### CompiledContext.to_openai() (FMT-02)

```python
# Source: Same format as to_dicts() -- OpenAI uses inline system messages
def to_openai(self) -> list[dict[str, str]]:
    """Convert to OpenAI chat completion message format.

    Identical to to_dicts() for text-only messages.
    System messages are included inline with role="system".
    """
    return self.to_dicts()
```

### CompiledContext.to_anthropic() (FMT-02)

```python
# Source: Anthropic API docs -- system is a separate top-level parameter
def to_anthropic(self) -> dict[str, object]:
    """Convert to Anthropic Messages API format.

    Returns a dict with:
    - 'system': concatenated system messages (str or None)
    - 'messages': list[dict] with user/assistant messages only

    Anthropic does not support role="system" in the messages array.
    System messages are extracted and concatenated into the 'system' parameter.
    """
    system_parts: list[str] = []
    messages: list[dict[str, str]] = []
    for m in self.messages:
        if m.role == "system":
            system_parts.append(m.content)
        else:
            d: dict[str, str] = {"role": m.role, "content": m.content}
            if m.name is not None:
                d["name"] = m.name
            messages.append(d)
    return {
        "system": "\n\n".join(system_parts) if system_parts else None,
        "messages": messages,
    }
```

### Tract.system() / user() / assistant() (CORE-01)

```python
# Source: Pattern follows existing Tract method conventions
def system(
    self,
    text: str,
    *,
    message: str | None = None,
    metadata: dict | None = None,
) -> CommitInfo:
    """Commit a system instruction.

    Shorthand for: commit(InstructionContent(text=text))
    """
    from tract.models.content import InstructionContent
    return self.commit(InstructionContent(text=text), message=message, metadata=metadata)

def user(
    self,
    text: str,
    *,
    message: str | None = None,
    name: str | None = None,
    metadata: dict | None = None,
) -> CommitInfo:
    """Commit a user message.

    Shorthand for: commit(DialogueContent(role="user", text=text))
    """
    from tract.models.content import DialogueContent
    return self.commit(
        DialogueContent(role="user", text=text, name=name),
        message=message, metadata=metadata,
    )

def assistant(
    self,
    text: str,
    *,
    message: str | None = None,
    name: str | None = None,
    metadata: dict | None = None,
    generation_config: dict | None = None,
) -> CommitInfo:
    """Commit an assistant response.

    Shorthand for: commit(DialogueContent(role="assistant", text=text))
    """
    from tract.models.content import DialogueContent
    return self.commit(
        DialogueContent(role="assistant", text=text, name=name),
        message=message, metadata=metadata,
        generation_config=generation_config,
    )
```

### Auto-Generated Commit Messages (CORE-03)

```python
# Source: Uses existing extract_text_from_content() from engine/commit.py
_MAX_AUTO_MSG_LEN = 72

def _auto_message(content_type: str, text: str) -> str:
    """Generate a short commit message from content type and text."""
    # Truncate text to a reasonable length
    preview = text.strip().replace("\n", " ")
    if len(preview) > _MAX_AUTO_MSG_LEN - len(content_type) - 2:
        max_text = _MAX_AUTO_MSG_LEN - len(content_type) - 5  # "type: text..."
        preview = preview[:max_text] + "..."
    return f"{content_type}: {preview}" if preview else content_type

# In Tract.commit():
if message is None:
    from tract.engine.commit import extract_text_from_content as _extract
    if isinstance(content, BaseModel):
        _text = _extract(content)
        _ctype = content.model_dump(mode="json").get("content_type", "unknown")
        message = _auto_message(_ctype, _text)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `[{"role": m.role, "content": m.content} for m in compiled.messages]` | `compiled.to_dicts()` | Phase 8 | Eliminates #1 boilerplate pattern |
| `from tract import InstructionContent; t.commit(InstructionContent(text="..."))` | `t.system("...")` | Phase 8 | Eliminates import ceremony |
| `t.commit(content, message="describe what happened")` | `t.commit(content)` (auto-message) | Phase 8 | Reduces ceremony for common commits |

**Note on OpenAI "developer" role:** OpenAI has introduced a `developer` role as an alternative to `system` in newer API versions. This is NOT relevant for Phase 8 because: (a) our `to_openai()` passes through whatever role the compiler assigned, and (b) the `system` role still works in OpenAI's API. If users need `developer` role, they can use the existing `DialogueContent(role="developer", text="...")` pathway.

## Open Questions

1. **Should `to_anthropic()` handle "tool" role messages?**
   - What we know: Anthropic supports `tool_result` and `tool_use` content blocks, but with a different structure than OpenAI's `role: "tool"`.
   - What's unclear: Whether to convert `role: "tool"` messages to Anthropic's `tool_result` format.
   - Recommendation: For Phase 8, pass `role: "tool"` messages through as-is in the `messages` list. Full tool message conversion is out of scope (it requires knowledge of tool_use_id which our Message dataclass doesn't carry). Document this limitation.

2. **Should shorthand methods support `generation_config`?**
   - What we know: `generation_config` is typically only relevant on assistant responses (it records what model/params produced the response).
   - What's unclear: Whether `system()` and `user()` should accept it.
   - Recommendation: Only `assistant()` should accept `generation_config`. System prompts and user messages don't have generation configs. This keeps the shorthand API clean.

3. **Auto-message for dict content passed to commit()**
   - What we know: `commit()` accepts both `BaseModel` and `dict` content. Auto-message needs to work for both.
   - What's unclear: For dicts, `extract_text_from_content()` won't work directly (it expects BaseModel).
   - Recommendation: For dict content, extract `content_type` from the dict and use a simple text extraction (check for "text", "content", "payload" keys). The dict gets validated into a BaseModel anyway, so we could also generate the message after validation.

4. **Should auto-message be opt-out?**
   - What we know: Setting `message=""` (empty string) vs `message=None` (not provided) are different in Python.
   - Recommendation: `message=None` triggers auto-generation. `message=""` stores empty string (explicit). This is the natural Python convention and requires no API change.

## Sources

### Primary (HIGH confidence)
- Codebase files read directly:
  - `src/tract/protocols.py` -- CompiledContext and Message definitions
  - `src/tract/tract.py` -- Tract facade with commit(), compile(), etc.
  - `src/tract/models/content.py` -- All 8 content types and type hints
  - `src/tract/engine/compiler.py` -- Role mapping, message building
  - `src/tract/engine/commit.py` -- extract_text_from_content(), CommitEngine
  - `src/tract/__init__.py` -- Current exports
  - `src/tract/llm/client.py` -- OpenAIClient.chat() message format
  - `src/tract/llm/protocols.py` -- LLMClient protocol
  - `.planning/VISION.md` -- Problem analysis and design constraints
  - `.planning/ROADMAP.md` -- Phase 8 requirements and success criteria
  - `.planning/REQUIREMENTS.md` -- CORE-01, CORE-02, CORE-03, FMT-01, FMT-02
  - `.planning/PRINCIPLES.md` -- Granular control + human/agent symmetry

### Secondary (MEDIUM confidence)
- Anthropic Messages API docs (fetched via WebFetch from platform.claude.com/docs):
  - System messages are a separate top-level parameter, NOT in messages array
  - Only "user" and "assistant" roles valid in messages array
  - Content can be string or array of content blocks
  - Usage reports `input_tokens` / `output_tokens` (not `prompt_tokens`)

### Tertiary (LOW confidence)
- OpenAI "developer" role information from WebSearch -- newer API versions may use "developer" instead of "system", but "system" still works. Not actionable for Phase 8.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- No new dependencies, pure Python methods on existing classes
- Architecture: HIGH -- Direct codebase analysis, patterns copy existing conventions (ToolDefinition.to_openai/to_anthropic)
- Pitfalls: HIGH -- Anthropic format difference verified with official docs; auto-message placement based on codebase analysis
- Code examples: HIGH -- Derived from existing codebase patterns with verified API format specs

**Research date:** 2026-02-19
**Valid until:** Indefinite (no external dependencies, format specs are stable)
