# Tract

**Git-like version control for LLM context windows.**

Agents produce better outputs when their context is clean, coherent, and
relevant. Tract makes context a managed, version-controlled resource.

---

## Installation

```bash
pip install tract-ai

# With CLI support:
pip install tract-ai[cli]
```

## Quickstart

```python
from tract import Tract, InstructionContent, DialogueContent

with Tract.open("my_context.db") as t:
    # Build context through commits
    t.commit(InstructionContent(text="You are a helpful research assistant."))
    t.commit(DialogueContent(role="user", text="Summarize recent ML papers."))
    t.commit(DialogueContent(role="assistant", text="Here are the key papers..."))

    # Compile into LLM-ready messages
    result = t.compile()
    for msg in result.messages:
        print(f"[{msg.role}] {msg.content[:60]}...")

    print(f"Total tokens: {result.token_count}")
```

## Core Concepts

- **Tract** -- A version-controlled context container. Each tract stores an
  immutable chain of commits representing an agent's conversation history.

- **Commits** -- Immutable snapshots of context. Eight built-in content types
  cover instructions, dialogue, tool I/O, reasoning, artifacts, outputs,
  freeform data, and session boundaries.

- **Compile** -- Reconstruct LLM-ready messages from the commit history.
  Handles edits, priority annotations (SKIP/PINNED), and token budgets.

- **Branches** -- Divergent context exploration. Branch off to try different
  approaches, merge successful results back.

- **Compression** -- Token-budget-aware history summarization. Collapse long
  commit chains into summaries while preserving pinned content.

- **Session** -- Multi-agent coordination. A session manages multiple tracts
  in a shared database, supporting spawn/collapse workflows and cross-tract
  queries.

## Single-Agent Example

```python
from tract import Tract, InstructionContent, DialogueContent, Priority

with Tract.open("project.db") as t:
    # System instruction
    t.commit(InstructionContent(text="You are a code reviewer."))

    # Conversation
    t.commit(DialogueContent(role="user", text="Review this function."))
    t.commit(DialogueContent(role="assistant", text="The function has 3 issues..."))

    # Pin important context so compression preserves it
    commits = t.log(limit=1)
    t.annotate(commits[0].commit_hash, Priority.PINNED, reason="Key review")

    # Compile for the next API call
    result = t.compile()
    print(f"{result.commit_count} commits, {result.token_count} tokens")

    # View history
    for c in t.log():
        print(f"  {c.commit_hash[:8]} [{c.content_type}] {c.message or ''}")
```

## Multi-Agent Example

```python
from tract import Session, InstructionContent, DialogueContent

with Session.open("multi_agent.db") as session:
    # Orchestrator creates the parent tract
    parent = session.create_tract(display_name="orchestrator")
    parent.commit(InstructionContent(text="Build a web application."))
    parent.commit(DialogueContent(role="user", text="Start with the backend."))

    # Spawn a child agent for a subtask
    child = session.spawn(parent, purpose="Design the database schema")

    # Child does its work
    child.commit(DialogueContent(role="assistant", text="Schema: users, posts, comments..."))
    child.commit(DialogueContent(role="assistant", text="Added indexes for common queries."))

    # Collapse child results back into parent
    result = session.collapse(
        child, into=parent,
        content="Database schema designed: users, posts, comments with indexes.",
    )
    print(f"Summary tokens: {result.summary_tokens}")

    # View the full timeline across all agents
    for commit in session.timeline():
        print(f"  [{commit.tract_id[:8]}] {commit.content_type}: {commit.message or ''}")
```

## Session Continuity

Agents can record session boundaries for clean handoffs between work sessions:

```python
from tract import Session, SessionContent, InstructionContent

with Session.open("handoff.db") as session:
    agent = session.create_tract(display_name="agent-a")
    agent.commit(InstructionContent(text="You are building a REST API."))

    # Record what was accomplished
    agent.commit(SessionContent(
        session_type="end",
        summary="Built user authentication endpoints.",
        decisions=["Chose JWT for auth tokens", "Used bcrypt for passwords"],
        next_steps=["Add rate limiting", "Write integration tests"],
    ))

# Later, a new agent resumes
with Session.open("handoff.db") as session:
    recovered = session.resume()
    if recovered:
        context = recovered.compile()
        print(f"Resuming with {context.commit_count} commits of context")
```

## Content Types

| Type          | Class              | Role    | Description                          |
|---------------|--------------------|---------|--------------------------------------|
| instruction   | InstructionContent | system  | System-level instructions            |
| dialogue      | DialogueContent    | varies  | User/assistant/system messages       |
| tool_io       | ToolIOContent      | system  | Tool calls and results               |
| reasoning     | ReasoningContent   | system  | Chain-of-thought / internal reasoning|
| artifact      | ArtifactContent    | system  | Code, documents, structured data     |
| output        | OutputContent      | system  | Final deliverables                   |
| freeform      | FreeformContent    | system  | Arbitrary key-value payloads         |
| session       | SessionContent     | system  | Session boundary markers             |

## Autonomy Modes

Sessions support three autonomy levels for collapse operations:

- **manual** -- You provide the summary text directly via `content=`.
- **collaborative** -- LLM drafts a summary, you review before committing.
- **autonomous** -- LLM drafts and auto-commits the summary.

```python
session = Session.open("project.db", autonomy="manual")
```

## API Reference

### Tract

The single-agent entry point for context management.

| Method               | Description                              |
|----------------------|------------------------------------------|
| `Tract.open(path)`  | Open or create a tract database          |
| `.commit(content)`   | Create a new context commit              |
| `.compile()`         | Compile context into LLM-ready messages  |
| `.log(limit)`        | Walk commit history from HEAD            |
| `.status()`          | Get current tract status                 |
| `.diff(a, b)`        | Compare two commits                      |
| `.annotate(h, p)`    | Set priority (SKIP/NORMAL/PINNED)        |
| `.branch(name)`      | Create a new branch                      |
| `.merge(branch)`     | Merge a branch into current              |
| `.compress()`        | Compress commit chains into summaries    |
| `.gc()`              | Garbage-collect unreachable commits      |

### Session

The multi-agent entry point for coordinating multiple tracts.

| Method                      | Description                              |
|-----------------------------|------------------------------------------|
| `Session.open(path)`       | Open or create a multi-agent session     |
| `.create_tract()`          | Create a new tract in the session        |
| `.spawn(parent, purpose)`  | Spawn a child tract from a parent        |
| `.collapse(child, into)`   | Collapse child history into parent       |
| `.timeline()`              | Get all commits chronologically          |
| `.search(term)`            | Search commits across tracts             |
| `.compile_at(id, at_time)` | Compile a tract at a point in time       |
| `.resume()`                | Find most recent active tract            |
| `.list_tracts()`           | List all tracts with metadata            |

### Key Models

| Model                | Description                              |
|----------------------|------------------------------------------|
| `CommitInfo`         | Metadata about a commit                  |
| `CompiledContext`    | LLM-ready messages with token count      |
| `BranchInfo`        | Branch name and commit hash              |
| `SessionContent`     | Session boundary commit content          |
| `SpawnInfo`          | Spawn relationship metadata              |
| `CollapseResult`     | Result of a collapse operation           |
| `CompressResult`     | Result of a compression operation        |

## Development

```bash
# Clone the repository
git clone https://github.com/WilliamJin123/tract.git
cd tract

# Install dev dependencies
pip install -e ".[dev]"

# Run the test suite
python -m pytest tests/ -x -q

# Run with coverage
python -m pytest tests/ --cov=tract --cov-report=term-missing
```

## License

MIT
