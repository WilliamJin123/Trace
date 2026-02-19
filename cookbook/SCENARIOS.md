# Tract Usage Scenarios

A hierarchical guide from basic context management to fully autonomous agent orchestration. Each scenario is grounded in a real-world use case.

---

## Tier 1: Foundations

Core operations every tract user needs on day one.

### 1.1 — First Conversation

**Use case:** A coding assistant that remembers its system prompt, takes a user question, and replies.

Open a tract, commit a system prompt, commit a user message, get the assistant response from your LLM, commit it, then compile everything into the message list your next LLM call needs. Persist to disk so the conversation survives a server restart. Reopen the same tract tomorrow and pick up where you left off.

> `Tract.open()`, `commit()`, `compile()`, `close()`, `Tract.open(path=...)`

### 1.2 — Token Budget Guardrail

**Use case:** A chatbot with a 128k context window that needs to know when it's running hot before each API call.

Check `status()` before every LLM call to see current token count vs budget. After the call returns, feed the API's actual usage numbers back with `record_usage()` so your tracking reflects reality, not just tiktoken estimates.

> `status()`, `TractConfig(token_budget=128000)`, `record_usage()`

### 1.3 — Atomic Multi-Turn Exchange

**Use case:** A RAG pipeline that retrieves documents, asks the user a clarifying question, and gets a response — all of which should land as one atomic unit or not at all.

Wrap the retrieval commit, user commit, and assistant commit inside `batch()` so either all three land or none do. Attach `generation_config={"model": "gpt-4o", "temperature": 0.7}` to the assistant commit so you know exactly what settings produced it.

> `batch()`, `commit(generation_config={...})`

---

## Tier 2: Context Curation

Surgical control over what the LLM sees in its context window.

### 2.1 — Correcting a Hallucination

**Use case:** Your customer support agent told a user the return policy is 60 days, but it's actually 30 days. You need to fix the record without appending a correction that clutters the conversation.

EDIT the original assistant commit in-place. The next `compile()` serves the corrected content as if the mistake never happened. The original is still in history for audit purposes.

> `commit(operation=EDIT, response_to=original_hash)`

### 2.2 — Protecting Key Instructions, Hiding Noise

**Use case:** A legal document review agent has a detailed system prompt with formatting rules that must never be lost, but also produces verbose tool outputs (API calls, database queries) that bloat the context.

Pin the system prompt so it survives any future compression. Skip the noisy tool outputs so they're excluded from compiled context but preserved in history if you ever need to audit them.

> `annotate(system_hash, PINNED)`, `annotate(tool_hash, SKIP)`

### 2.3 — Debugging a Bad Response

**Use case:** Your agent gave a terrible answer 15 turns ago and you want to understand exactly what it was seeing at that point to figure out why.

Checkout the commit right before the bad response. Compile at that point to reconstruct the exact message list the LLM received. Diff it against the current state to see what's changed since.

> `checkout(past_hash)`, `compile(at_commit=...)`, `diff(then, now)`

---

## Tier 3: Branching & Exploration

When one timeline isn't enough and you need to explore in parallel.

### 3.1 — Try Two Approaches, Keep the Winner

**Use case:** A writing assistant is drafting an email. The user wants to see a formal version and a casual version before choosing.

Branch from the current state. Write the formal draft on `main`, switch to the branch and write the casual draft. Diff the two compiled contexts. The user picks formal — merge it back (fast-forward) and delete the experiment branch.

> `branch("casual")`, `switch()`, `diff()`, `merge()`, `delete_branch()`

### 3.2 — A/B Testing Model Configurations

**Use case:** You're evaluating whether gpt-4o at temperature 0.3 produces better code reviews than gpt-4o-mini at temperature 0.7.

Branch from the same conversation state. Run identical prompts on each branch with different `generation_config` values. Compare the compiled outputs. The generation configs are stored with each commit so you can query later which model produced what.

> `branch()`, `commit(generation_config={...})`, `query_by_config()`, `diff()`

### 3.3 — Moving Work Across Branches

**Use case:** An agent explored a tangent on a feature branch and produced one genuinely useful insight buried in 20 commits. Separately, main has moved forward and your subtask branch is stale.

Cherry-pick the single useful commit onto main. Then rebase your subtask branch onto the updated main so it has the latest context — with semantic safety checks that warn if the rebase would break response_to chains.

> `cherry_pick(useful_hash)`, `rebase("main")`

---

## Tier 4: Compression & Memory

Keeping conversations alive long past the context window limit.

### 4.1 — Three Ways to Compress

**Use case:** A therapy chatbot has been running for 200 turns. The early turns are stale but contain important emotional context that shouldn't be lost entirely.

- **Manual:** You write the summary yourself — deterministic, no LLM needed.
- **LLM:** Configure an LLM client and let it summarize the first 150 turns down to 2000 tokens.
- **Collaborative:** The LLM drafts a summary, you review it for accuracy and emotional nuance, then approve.

> `compress(content="...")`, `compress(target_tokens=2000)`, `compress(auto_commit=False)` + `approve_compression()`

### 4.2 — Pinned Content Survives Compression

**Use case:** A financial advisor agent has compliance disclaimers in its system prompt and regulatory citations pinned throughout the conversation. When compression runs, these must survive verbatim — no paraphrasing allowed.

Pin the critical commits. When compression runs over a range, pinned commits pass through untouched. Skipped commits are excluded entirely (they were noise anyway). Everything else gets summarized.

> `annotate(PINNED)` + `compress(from_commit=..., to_commit=...)`

### 4.3 — Reclaiming Storage

**Use case:** A production deployment has thousands of tracts, each with compression history. Original pre-compression commits are kept for audit but eventually need cleanup.

Run GC to remove orphaned commits older than N days. Archived (pre-compression) commits can have a separate retention window. This is non-destructive to any reachable commit chain.

> `gc(orphan_retention_days=7, archive_retention_days=30)`

---

## Tier 5: Multi-Agent

Coordinating context across parent and child agents.

### 5.1 — Sub-Agent Delegation

**Use case:** A research agent spawns a sub-agent to deep-dive on a specific topic. The sub-agent produces 40 turns of research. The parent only needs a 3-paragraph summary.

Spawn a child tract. The sub-agent does its work there. When finished, compress the child's entire history into a summary. The parent commits that summary as a single message on its own timeline — 40 turns collapsed into one.

> `parent()`, `children()`, `compress()`, `commit()`

### 5.2 — Parallel Agents, Supervisor Merge

**Use case:** A project planning agent assigns three sub-agents to research competitors, market size, and technical feasibility simultaneously.

Each agent works on its own branch. When all three finish, a supervisor agent reviews each branch, resolves any overlapping findings with a merge, and produces a unified context on main.

> `branch("competitor-research")`, `branch("market-size")`, `branch("tech-feasibility")`, `merge()`

---

## Tier 6: Automated Policies

Context that manages itself without manual intervention.

### 6.1 — Built-In Policy Suite

**Use case:** A 24/7 customer service agent that runs unattended. It needs to auto-compress when context gets large, protect its instruction set, branch when conversations go off-topic, and clean up dead-end branches.

Configure all four built-in policies at once: CompressPolicy fires at 80% budget, PinPolicy auto-pins instruction-type commits, BranchPolicy detects rapid content-type switching (topic drift), ArchivePolicy archives branches inactive for 7+ days.

> `configure_policies([CompressPolicy(0.8), PinPolicy(), BranchPolicy(), ArchivePolicy()])`

### 6.2 — Autonomy Spectrum

**Use case:** During development you want to approve every policy action. In staging, you want to review but auto-approve safe ones. In production, full auto.

The same policies work at any autonomy level. In manual mode, every action becomes a proposal you approve/reject. In collaborative mode, low-risk actions (pin, skip) auto-execute while high-risk ones (compress, branch) need approval. In autonomous mode, everything fires immediately.

> `configure_policies(on_proposal=cli_prompt)`, `approve_proposal()`, `reject_proposal()`

### 6.3 — Custom Policy

**Use case:** A healthcare agent must never have PII in its compiled context, and tool outputs older than 10 turns should be auto-skipped to save tokens.

Write a custom policy implementing the `Policy` protocol. It triggers on each commit, inspects the content for PII patterns, and proposes a SKIP annotation if found. A second policy triggers on compile and auto-skips tool outputs beyond a turn threshold.

> Implement `Policy` protocol: `name`, `priority`, `trigger`, `evaluate(tract) -> PolicyAction | None`

---

## Tier 7: Agent Toolkit & Orchestrator

The agent manages its own context window end-to-end.

### 7.1 — Agent Self-Management via Tool Calls

**Use case:** You're building an agent framework and want the LLM to decide when to compress, branch, or annotate — without your application code making those decisions.

Call `as_tools()` to get tract operations formatted as OpenAI or Anthropic function-call definitions. Include them in your LLM's tool list. The agent can now commit, compile, annotate, compress, branch, and merge by calling tools — your framework just dispatches.

> `as_tools(profile="self", format="openai")`, `as_tools(profile="supervisor", format="anthropic")`

### 7.2 — Trigger-Based Orchestration

**Use case:** A long-running coding agent should automatically assess and manage its context every 20 commits or when token usage crosses 70% — without the application polling.

Configure the orchestrator with triggers. When a trigger fires, the orchestrator assesses context health (fragmentation, budget pressure, stale branches), then executes the appropriate tools — compress, GC, branch cleanup — in an autonomous loop.

> `configure_orchestrator(config=OrchestratorConfig(triggers=TriggerConfig(on_commit_count=20, on_token_threshold=0.7)))`, `orchestrate()`

### 7.3 — Human-in-the-Loop Orchestration

**Use case:** The orchestrator is managing context for a medical documentation agent. Compression and branch merges need human sign-off for regulatory compliance.

Configure the orchestrator with a callback. It proposes actions with reasoning ("Context at 85%, recommend compressing turns 1-50"). The human approves, rejects, or modifies ("Compress 1-40, keep 41-50 they contain the diagnosis"). The orchestrator executes the modified action and continues.

> `OrchestratorConfig(callbacks=cli_prompt)`, `pause_orchestrator()`, `approve_proposal()`

---

## Cross-Cutting Compositions

Real-world scenarios that combine multiple tiers. These represent the kind of integrated workflows tract was designed for.

### X.1 — Drift Steering

**Use case:** A project management agent starts discussing technical architecture but gradually drifts into bikeshedding about naming conventions for 30 turns.

BranchPolicy detects the content-type switching pattern and auto-branches the tangent. The orchestrator notices the tangent branch has stalled, compresses it into a one-paragraph summary, and merges that summary back to main. The agent is back on track with full context of what was discussed but none of the noise.

> Combines: Policies (6) + Orchestrator (7) + Compression (4)

### X.2 — Human Interjection Mid-Conversation

**Use case:** A sales agent is in the middle of a customer conversation when a supervisor notices it's quoting an outdated price. The conversation can't be restarted.

Pause the orchestrator. EDIT the commit containing the wrong price with the correct one. Pin the correction so it's never compressed away. Resume the orchestrator. The agent's next compile sees the corrected price as if it was always there.

> Combines: Orchestrator (7) + Curation (2) + Policies (6)

### X.3 — Context Forensics

**Use case:** An agent produced a terrible quarterly report. Somewhere in its 80-turn history, it ingested bad data and every subsequent turn built on that mistake.

Walk the log backwards. Checkout suspect commits and compile at each point to see exactly what the agent was working with. Diff adjacent commits to find where the bad data entered. Once found, create a branch from just before the bad commit, cherry-pick the good subsequent work, and rebase to produce a clean history without the contamination.

> Combines: Curation (2) + Branching (3)

### X.4 — Long-Running Autonomous Session

**Use case:** A monitoring agent runs for 8 hours processing alerts. It can't stop for maintenance. Context must stay fresh and storage can't grow unbounded.

CompressPolicy fires every time the budget hits 80%. Pinned alerts (severity: critical) survive every compression pass. After each compression, GC reclaims the archived originals older than 1 hour. Over 8 hours, the agent has compressed 4 times, its context is tight, and disk usage stayed flat.

> Combines: Compression (4) + Policies (6) + Orchestrator (7)

### X.5 — Streaming Integration

**Use case:** A real-time coding assistant streams responses token-by-token. You need to compile context before the stream starts, track the partial response as it arrives, and commit the final result cleanly.

Compile context and send to the LLM. As chunks stream back, accumulate them. On stream completion, commit the full response with the actual token usage from the API. If the stream is interrupted, commit what you have as a partial response and EDIT it later when you retry.

> Combines: Foundations (1) + Curation (2)

### X.6 — Undo / Redo

**Use case:** An agent committed a response the user didn't like. You want to undo it, try a different approach, and if that's worse, redo the original.

Soft reset to the commit before the bad response (the bad commit is now unreachable but not deleted). Try the new approach and commit it. If it's worse, `reset` back again and cherry-pick the original response from the orphaned commit before GC claims it. Alternatively, hard reset to fully discard everything after a checkpoint.

> Combines: Curation (2) + Branching (3)
