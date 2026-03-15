# Sentinel Design: Semantic Middleware for Tract

## Implementation Status

- **Phase 1 — `t.gate()` (SemanticGate)**: SHIPPED. `src/tract/gate.py`. 70 tests.
  - Post_* events rejected at registration time (gates block; can't block post-op).
- **Phase 2 — `t.maintain()` (SemanticMaintainer)**: SHIPPED. `src/tract/maintain.py`. 72 tests.
  - Actions: annotate, compress, configure, directive, tag, gc.
- **Phase 3 — Full sentinel (peeking + multi-turn)**: NOT STARTED. Deferred pending demand.

## Problem

Tract has two enforcement primitives:
- **Middleware** — deterministic Python functions (hard gates, counters, routing)
- **Directives** — natural language instructions compiled into agent context (advisory, no enforcement)

Missing: **semantic enforcement** — operations that need both LLM judgment AND actual enforcement. Examples:
- "Compress tool results that are no longer relevant to the current task"
- "Block transition unless the research has at least 3 distinct perspectives"
- "When the agent shifts from research to implementation, reconfigure automatically"
- "Mark commits that have been superseded by later edits as SKIP"

## Design Principle

A Sentinel is a **SemanticHandler registered as middleware**. It's a callable that:
1. Receives a MiddlewareContext (same as any middleware handler)
2. Optionally checks a deterministic condition (cheap pre-check)
3. Builds a manifest from the tract's DAG (token-efficient)
4. Makes a single LLM call with developer instructions + manifest + action schema
5. Executes returned actions against existing tract primitives
6. Optionally raises BlockedError (for gate use cases)

**No new middleware events. No new operations. No new storage.** It's a class that implements `__call__` and plugs into `t.use()`.

## API

### Registration

```python
from tract import Tract
from tract.sentinel import Sentinel

t = Tract.open(...)

# Maintenance: compress stale content when budget is tight
t.sentinel(
    "context-janitor",
    event="pre_compile",
    instructions=(
        "Review the context manifest below. Your job is to keep the "
        "context lean and relevant.\n"
        "- Mark tool call results older than 10 turns as SKIP\n"
        "- If total tokens exceed 80% budget, compress the oldest "
        "non-pinned cluster into a summary\n"
        "- Never touch commits tagged 'key-finding'"
    ),
    actions=["annotate", "compress"],
    model="small",  # cheap model
    condition=lambda ctx: (
        ctx.tract.status().token_count / (ctx.tract.status().token_budget_max or float('inf')) > 0.7
    ),
)

# Fuzzy gate: semantic quality check on agent output
t.sentinel(
    "citation-checker",
    event="pre_commit",
    instructions=(
        "The pending commit claims to contain research findings. "
        "Check that every factual claim references a source. "
        "If any claims are unsourced, block with a specific reason."
    ),
    actions=["block"],
    model="small",
    condition=lambda ctx: (
        getattr(ctx.pending, 'role', None) == 'assistant'
        and ctx.tract.get_config('stage') == 'research'
    ),
)

# Auto-routing: reconfigure based on content shift
t.sentinel(
    "phase-detector",
    event="post_commit",
    instructions=(
        "Analyze the last 3 commits. Determine if the agent has shifted "
        "from research (gathering info, reading) to implementation "
        "(writing code, defining structures). If so, set config "
        "stage='implementation' and temperature=0.3."
    ),
    actions=["configure"],
    model="small",
)
```

### Under the hood: `t.sentinel()` is sugar for `t.use()`

```python
# t.sentinel("name", event="pre_compile", ...) is equivalent to:
handler = Sentinel(
    name="context-janitor",
    instructions="...",
    actions=["annotate", "compress"],
    model="small",
    condition=lambda ctx: ...,
)
t.use("pre_compile", handler)
```

### Removal

```python
# Returns handler_id like any middleware
sentinel_id = t.sentinel("context-janitor", event="pre_compile", ...)

# Remove like any middleware
t.remove_middleware(sentinel_id)

# Or remove by name (new convenience)
t.remove_sentinel("context-janitor")
```

## Sentinel Class

```python
@dataclass
class Sentinel:
    """LLM-powered middleware handler.

    Registered via t.sentinel() or t.use(event, Sentinel(...)).
    When triggered, builds a manifest, makes one LLM call, and
    executes returned actions against existing tract primitives.
    """
    name: str
    instructions: str
    actions: list[str]           # allowed: "annotate", "compress", "configure", "directive", "block", "tag", "gc"
    model: str | None = None     # model override (defaults to tract's configured model)
    condition: Callable | None = None  # deterministic pre-check; skip LLM if returns False
    context: str = "manifest"    # "manifest" (cheap) or "full" (compiled context)
    max_peeks: int = 5           # max commits to peek into for content details
    temperature: float = 0.1     # low temp for infrastructure decisions

    def __call__(self, ctx: MiddlewareContext) -> None:
        """Called by middleware system. Makes LLM call and executes actions."""
        # 1. Pre-check
        if self.condition and not self.condition(ctx):
            return

        # 2. Build manifest
        manifest = self._build_manifest(ctx.tract)

        # 3. Build LLM messages
        messages = self._build_messages(manifest, ctx)

        # 4. Single LLM call with structured output
        response = self._call_llm(ctx.tract, messages)

        # 5. Parse and execute actions
        self._execute_actions(ctx, response)
```

## Manifest Format

The manifest is the key to cost efficiency. Built from `t.log()` + `t.status()` — no content loading.

```
=== CONTEXT MANIFEST ===
Branch: main | Stage: research | HEAD: a3f8b2c1
Tokens: 4,200 / 6,000 (70%) | Commits: 23

COMMIT LOG (newest first):
 #23 [a3f8] assistant  |  847 tok | age:0  | tags:[research] | NORMAL
     msg: "Analysis of B-tree indexing strategies"
 #22 [b2c1] tool_io    |  234 tok | age:1  | tags:[]         | NORMAL
     msg: "tool:search_db result"
 #21 [c9d4] assistant  | 1203 tok | age:2  | tags:[draft]    | IMPORTANT
     msg: "Recommended architecture based on findings"
 #20 [d1e5] tool_io    | 2100 tok | age:3  | tags:[]         | NORMAL
     msg: "tool:read_file result (large)"
 #19 [e2f6] user       |   45 tok | age:3  | tags:[]         | NORMAL
     msg: "Now implement the caching layer"
 ...

TAGS: research(5), draft(3), key-finding(2)
PINNED: 2 commits (#15, #8)
SKIPPED: 1 commit (#3)
CONFIG: {stage: "research", temperature: 0.7}
DIRECTIVES: research-protocol, output-format
```

~500-2000 tokens for a 50-commit context. The sidecar sees structure + metadata, not content.

## Peeking

If the sentinel needs content details for a decision, it can "peek" at specific commits. This is exposed as a tool in the sentinel's LLM call:

```json
{
  "name": "peek",
  "description": "Read the full content of a specific commit by hash",
  "parameters": {
    "commit_hash": {"type": "string"}
  }
}
```

Capped by `max_peeks` to control cost. The sentinel gets manifest + peek tool, so it can be selective about what it reads.

With peeking, the sentinel becomes a mini 2-3 step loop:
1. Read manifest → decide which commits need attention
2. Peek at 1-3 specific commits if needed
3. Return actions

## Action Schema

The sentinel's LLM response must conform to a structured action schema:

```json
{
  "reasoning": "Tool results #22 and #20 are stale DB lookups...",
  "actions": [
    {
      "type": "annotate",
      "target": "b2c1",
      "priority": "skip",
      "reason": "Stale tool result, superseded by commit #21"
    },
    {
      "type": "compress",
      "commits": ["d1e5"],
      "instructions": "Summarize the file contents in one line"
    },
    {
      "type": "block",
      "reason": "Pending commit lacks source citations"
    },
    {
      "type": "configure",
      "key": "stage",
      "value": "implementation"
    },
    {
      "type": "configure",
      "key": "temperature",
      "value": 0.3
    },
    {
      "type": "directive",
      "name": "current-phase",
      "text": "You are now in implementation mode. Write precise code."
    },
    {
      "type": "tag",
      "target": "c9d4",
      "tag": "key-finding"
    }
  ]
}
```

Each action maps 1:1 to an existing tract primitive:
- `annotate` → `t.annotate(hash, priority)`
- `compress` → `t.compress(commits=[...], instructions="...")`
- `block` → `raise BlockedError(event, [reason])`
- `configure` → `t.configure(**{key: value})`
- `directive` → `t.directive(name, text)`
- `tag` → `t.tag(hash, tag_name)`
- `gc` → `t.gc()`

## Cost Model

**Per sentinel invocation:**
- Manifest: ~500-2000 tokens (input)
- Instructions: ~100-300 tokens (input)
- Action schema: ~200 tokens (input)
- Response: ~100-500 tokens (output)
- Peeks: ~0-2000 tokens per peek (0-5 peeks)
- **Total: ~1000-5000 tokens per invocation**

**vs. full context replay: 10,000-100,000 tokens**

**Amortized savings:**
- If sentinel SKIPs 3 stale tool results (5000 tokens), the task agent saves 5000 tokens on EVERY subsequent turn
- If running 10 more turns, that's 50,000 tokens saved for a 3,000 token sentinel cost

**Triggers minimize unnecessary calls:**
- `condition` pre-check is pure Python (zero LLM cost)
- Only fires when threshold exceeded or event matches
- Most turns: sentinel doesn't run at all

## Integration with Existing Systems

### Middleware
Sentinel IS middleware. Registered via `t.use()`. Fires on standard events. Uses `MiddlewareContext`. Raises `BlockedError` for gates. No changes to middleware system needed.

### Directives
Sentinel instructions are NOT directives (they don't go in the task agent's context). They're internal to the Sentinel class. But sentinels CAN create directives as an action (e.g., phase-detector creates a new directive when it detects a phase shift).

### Compile
Sentinel actions (annotate, compress) modify the DAG. Next compile() picks up the changes automatically. No compile pipeline changes needed.

### Loop
The loop doesn't need to know about sentinels. They fire through existing middleware hooks. The recommended trigger for maintenance sentinels is `pre_compile` (fires every loop iteration before the LLM sees the context).

### Config
Sentinel configuration lives in the Sentinel dataclass, not in tract config. But sentinels CAN read config (`ctx.tract.get_config(...)`) and write config (via "configure" action).

## What This Replaces

- **Deleted cookbook 01_context_management**: Sentinel with "annotate" + "compress" actions handles this properly
- **Deleted cookbook 04_knowledge_organization**: Sentinel with "tag" actions handles taxonomy creation
- **Self-routing middleware (09_self_routing)**: Sentinel with "configure" + "directive" actions, but LLM-powered instead of keyword-based

## What This Does NOT Replace

- Deterministic middleware (gates with hard thresholds) — keep using `t.use()` with Python functions
- Task-agent directives — keep using `t.directive()` for instructions to the main agent
- Manual compression — keep using `t.compress()` directly when you know what to compress

## Open Questions

1. **Async**: Should `Sentinel.__call__` be async? Current middleware is sync. Could use `asyncio.to_thread()` or make the loop check for async handlers.

2. **Ordering**: If multiple sentinels fire on the same event, what order? Current middleware uses registration order.

3. **Sentinel-to-sentinel**: Can one sentinel's actions trigger another sentinel? The recursion guard in `_run_middleware` prevents re-entrance on the same event, but cross-event triggers are possible (e.g., sentinel annotates → triggers post_commit → another sentinel fires).

4. **Testing/debugging**: How do you test that a sentinel will do the right thing? Need a dry-run mode that returns actions without executing them.

5. **Error handling**: If the LLM returns malformed actions, skip gracefully? Log warning? The sentinel should be fail-safe — errors in the sentinel should not crash the task agent's loop.

6. **Model resolution**: `model="small"` needs to resolve to an actual model ID. Could use the provider system from cookbooks, or tract's configured LLM client with a model override.
