# Agentic Patterns Extensions

Raw ideas for future cookbook/library work. Semi-organized braindump.

## Master Control / Orchestration

- **Parent watches subagent** — monitor progress, interrupt mid-task, reguide with new instructions. Show error robustness (subagent goes off-rails, parent catches it, steers back).
- **Dynamic shutdowns** — parent kills a subagent that's burning tokens without progress. Timeout-based or quality-based kill decisions.
- **Mid-task steering** — parent injects new context/directives into a running subagent's tract without stopping the loop. Middleware-mediated course corrections.
- **"Not worth pursuing" log** — dead branches / abandoned approaches tracked as a branch graveyard. Agents check the graveyard before starting work to avoid repeating known-bad paths.

## Multi-Agent Topologies

### Hierarchical (leaders + workers)
- Leader decomposes task, assigns to workers, collects results, makes decisions
- Workers report back structured artifacts, leader synthesizes
- Chain of command: leader > sub-leaders > workers (deep hierarchy)

### Shared Event Bus / Flat Swarm
- Agents share a task list / event bus / state store (no single leader)
- Any agent can pick up work, post findings, react to others' output
- Coordination via shared tract state (config, tags, commits) rather than explicit messaging

### Hybrid (hierarchy + swarm)
- Leader sets strategy, workers self-organize execution
- Leader intervenes only on conflicts or quality failures

## Workflow Patterns

- **Plan -> implement -> verify -> iterate** — staged pipeline with gates between each stage
- **Implement -> critique -> defend -> fix -> iterate** — adversarial improvement loop (partially covered in `05_adversarial_review.py`, but could be more general)
- **Tools to mark in-progress / done on a spec** — source-of-truth checklist that agents update as they work. Metadata or tags on commits tracking completion status against a requirements doc.

## Agent Role Patterns

### Dispatcher / Coordinator
- Receives tasks, routes to appropriate specialist agent based on task type
- Maintains a registry of available agents and their capabilities
- Load balancing, priority queuing

### Agents as Tools (Stateless Subagents)
- Subagent is invoked like a tool call — receives input, returns output, no persistent state
- Parent treats the subagent's response as a tool result in its own context
- Lightweight, composable, no session management overhead

### Evaluator-Optimizer
- One agent generates, another evaluates, scores fed back to improve next generation
- Exploit the fact that **LLMs are better at evaluating than generating**
- Evaluation criteria can be rubric-based (structured) or open-ended (semantic gate)

### Self-Correction Loop with Critic
- Agent generates output, built-in critic reviews it, agent revises
- Can be same-agent (reflect on own work) or separate-agent (external critic)
- **Forcing AI to justify / explain / audit choices improves performance** — require the agent to commit rationale before committing implementation

## Meta-Principles

- LLMs are better at evaluating than generating — design patterns that exploit this asymmetry
- Forcing justification/explanation/audit improves output quality — build this into workflows as mandatory steps
- Dead approach tracking prevents wasted work — agents should check what's been tried before
