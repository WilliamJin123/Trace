# Trace Project — Claude Code Instructions

## Tutorial-First Development (MANDATORY)

**Before implementing ANY new feature, phase, or significant code change**, you MUST first create or update a tutorial writeup in the `tutorials/` directory. This is a hard requirement, not optional.

### What to write

Each tutorial should cover the relevant subset of:

1. **Conceptual explanation** — What problem does this solve? Why does it exist? What mental model should the reader have?
2. **Design choices** — What alternatives were considered? Why was this approach chosen over others? What are the tradeoffs?
3. **Implementation walkthrough** — How does the code actually work? Walk through the key functions, data flow, and interactions.
4. **Connection to the bigger picture** — How does this fit into the overall Trace architecture? What depends on it? What does it depend on?
5. **Code examples** — Show concrete usage with explanations, not just API signatures.

Tutorials should also include the date written and a one-line summary as a yaml frontmatter

### When to write

- **Before a new phase**: Write a tutorial covering the concepts and design that phase will implement.
- **Before a significant refactor**: Write a tutorial explaining the current state, why it needs to change, and the target state.
- **After completing a phase**: Update tutorials to reflect what was actually built (reality vs. plan).

### Naming convention

```
tutorial/
  01-foundations-overview.md        # Phase-level overview
  01a-data-models-and-storage.md   # Sub-topic deep dives
  01b-engine-layer.md
  01c-repo-api.md
  02-linear-history.md
  ...
```

### Quality bar

Tutorials should be written so that someone with Python experience but no knowledge of Trace could:
- Understand WHY each design decision was made
- Follow the implementation logic without reading the source code first
- Ask informed questions about alternatives and tradeoffs

The user will read these thoroughly and ask clarifying questions. Prioritize clarity and depth over brevity.

## Other Project Rules

- Package imports as `tract` (previously `trace_context`)
- Source lives in `src/tract/`
- Tests in `tests/`
- Planning docs in `.planning/`
- Always run verification tests before claiming completion
- Use subagents for parallel independent work
