# Phase 7: Agent Toolkit & Orchestrator - Context

**Gathered:** 2026-02-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose Tract operations as an agent toolkit (tool schemas with customizable prompts) and ship a lightweight built-in orchestrator that uses the toolkit. The orchestrator is policy-integrated: policies trigger it, it reasons via LLM, and policies constrain what it can do. This completes the autonomy spectrum from Core Value #2.

**Key reframing:** Phase 7 is NOT a monolithic context management agent. It is (1) a toolkit any agent can consume, and (2) a reference orchestrator built on top of that toolkit. The orchestrator IS the toolkit + a configurable agent loop.

</domain>

<decisions>
## Implementation Decisions

### Toolkit: Tool schemas with customizable prompts
- `Tract.as_tools()` returns tool definitions for Tract operations
- **Profiles + overrides**: Ship built-in profiles (e.g., `self` for self-management, `supervisor` for managing other agents). Each profile curates which tools are included and provides scenario-appropriate descriptions. Users can override individual tool descriptions on top of any profile.
- **Configurable tool set**: Profiles control which operations are exposed. All operations available, but profiles filter to the relevant subset. Users can add/remove tools from any profile.
- Tool schema format: Claude's discretion on the exact format — the key requirement is customizable descriptions per tool, not a specific schema standard.

### Orchestrator: Toolkit + configurable agent loop
- The orchestrator is literally what you'd build if you wired the toolkit into an agent yourself. We ship a good default.
- **Trigger modes**: Both periodic and event-triggered. Users define when the orchestrator runs (every N commits, on budget threshold, on compile, on schedule, etc.). Trigger conditions are user-configurable.
- **Every step is customizable**: What to review, when to review, instructions for how to act. The loop is not opaque.
- **LLM provider**: Built-in LLM client (Phase 3) as default, user-provided callable as override. Same pattern as merge resolvers and compression.

### Health assessment: Holistic LLM judgment, not numeric scoring
- **No arbitrary heuristic scores**. The agent does not compute "relevance: 45" or "coherence: 72". Context management doesn't work that way.
- **Token pressure is still math** — % of budget is quantitative and stays quantitative. This is the one "heuristic" that makes sense as a number.
- **Everything else is LLM-assessed holistically**. When triggered, the LLM reads the compiled context and reasons qualitatively about what's working, what's not, and what to do. Like a code review for context.
- **Context for assessment**: The LLM gets recent commits, user-provided task context (if available), and infers current focus from HEAD. Uses whatever's available — more context produces better assessments.
- **Output is free-form reasoning into actions**. The LLM reasons in natural language, then calls native Tract operations (compress, branch, pin, reorder, etc.) as tool calls. No intermediate scoring layer.

### Policy integration: Policies trigger, orchestrator reasons, policies constrain
- **Policies define "when" and "what"** — auto-compress at 80% budget, auto-branch on tangent detection, etc.
- **Orchestrator handles "how"** — via LLM reasoning. When a policy fires in autonomous mode, it invokes the orchestrator, which uses LLM judgment to decide how to act (which commits to compress, where to branch, etc.).
- **Policies also act as guardrails** — the orchestrator cannot exceed what policies allow.

### Proposal & review flow: Callback-based
- In collaborative mode, the orchestrator proposes before acting.
- **Callback-based**: User provides a callback function that receives proposals and returns approve/reject/modify. Programmatic — fits SDK-first design.
- **Proposal object contains**: Recommended action, LLM's reasoning for why, and alternative actions the LLM considered. Rich enough for informed decisions.
- **Full override**: Reviewer can approve the recommendation, pick an alternative, edit parameters, or replace with a completely different action. The proposal is a suggestion, not a constraint.
- **Built-in callbacks**: `auto_approve` (autonomous mode), `cli_prompt` (interactive CLI), `log_and_approve` (audit trails). Users build their own for queues, webhooks, custom UIs.

### Autonomy configuration: Global ceiling
- **Global autonomy ceiling** on the orchestrator, default = collaborative (Core Value #2).
- Policies can be at or below the ceiling, never above. If policy says autonomous but ceiling is collaborative, collaborative wins.
- **Runtime changeable**: User can raise/lower the ceiling at any time via SDK call. Supports progressive trust (start collaborative, gain confidence, escalate to autonomous).
- **Disable modes**: `stop()` for immediate halt (abort in-flight actions), `pause()` for graceful wind-down (finish in-flight, then stop). No data loss in either case.

### Core Value #2 alignment
- **Manual** = user calls Tract SDK directly. No orchestrator, no automation.
- **Collaborative** = orchestrator proposes, user approves via callback. Default mode.
- **Autonomous** = orchestrator acts within policy constraints, no human in the loop.
- Humans can intercept at any point: before (configure policies/prompts), during (callback review), after (review and revert).
- The orchestrator IS the toolkit + a loop — it's the reference implementation of what any agent would build with the toolkit.

### Claude's Discretion
- Tool schema format (JSON Schema, plain dicts, etc.)
- Exact profile names and default tool subsets per profile
- Orchestrator internal loop architecture (async, threading, etc.)
- How the LLM structures its holistic context review internally
- Built-in trigger condition implementations

</decisions>

<specifics>
## Specific Ideas

- The orchestrator should dogfood the toolkit — it calls the same tools any external agent would. No special internal APIs.
- Profiles are like "self-management" (when tools are given to an agent to manage its own context) vs "supervisor" (managing other agents' context). Different prompts for the same operations.
- The autonomy spectrum pattern: policies define rules, orchestrator provides LLM reasoning, callbacks provide human review. Three independent concerns that compose cleanly.

</specifics>

<deferred>
## Deferred Ideas

- Framework-specific adapters (OpenAI function calling format, Anthropic tool format, LangChain tool wrappers) — build after core toolkit is stable
- Web dashboard for reviewing proposals — separate phase/milestone
- Multi-orchestrator coordination (orchestrators managing orchestrators) — future capability

</deferred>

---

*Phase: 07-agent-toolkit-orchestrator*
*Context gathered: 2026-02-18*
