"""System prompts for the context management orchestrator.

Provides the orchestrator's system prompt and a builder for the
user-side assessment prompt that describes current context state.
"""

from __future__ import annotations

ORCHESTRATOR_SYSTEM_PROMPT: str = (
    "You are a context management assistant for an LLM conversation. "
    "Your job is to review the current context state and take actions "
    "to maintain context health.\n\n"
    "Decision framework:\n"
    "- Compress when token pressure is high (>80% of budget).\n"
    "- Pin important context (system prompts, key decisions, constraints).\n"
    "- Branch when the conversation has diverged into a tangent.\n"
    "- Prioritize actions by impact: compression > pinning > branching > other.\n\n"
    "Behavioral rules:\n"
    "- If the context is healthy, respond with a brief assessment and no tool calls.\n"
    "- If action is needed, explain your reasoning FIRST, then use the available tools.\n"
    "- Never compress pinned content.\n"
    "- Prefer small targeted actions over large sweeping changes.\n\n"
    "Output format:\n"
    "- Always start with a brief assessment of the current context state "
    "before taking any actions.\n\n"
    "Relevance and coherence guidance:\n"
    "- Assess relevance by examining whether recent activity aligns with the "
    "task context (if provided).\n"
    "- Assess coherence by looking for signs of fragmentation: many short "
    "tangential commits, frequent topic switches, or abandoned threads.\n"
    "- These signals inform whether branching or compression is warranted."
)


def build_assessment_prompt(
    token_count: int,
    max_tokens: int,
    commit_count: int,
    branch_name: str,
    recent_commits: list[str],
    task_context: str | None = None,
    pinned_count: int = 0,
    skip_count: int = 0,
    branch_count: int = 1,
) -> str:
    """Build the user-side assessment prompt with current context state.

    Args:
        token_count: Current token usage.
        max_tokens: Maximum token budget.
        commit_count: Total number of commits.
        branch_name: Name of the current branch.
        recent_commits: List of recent commit descriptions (max 10 shown).
        task_context: Optional task context description for relevance assessment.
        pinned_count: Number of pinned annotations.
        skip_count: Number of skipped annotations.
        branch_count: Total number of branches.

    Returns:
        Formatted assessment prompt string.
    """
    pct = (token_count / max_tokens * 100) if max_tokens > 0 else 0.0

    recent = "\n".join(f"  {c}" for c in recent_commits[:10])

    lines = [
        "Current context state:",
        f"- Token usage: {token_count}/{max_tokens} ({pct:.0f}%)",
        f"- Commits: {commit_count} total",
        f"- Current branch: {branch_name}",
        f"- Branches: {branch_count} total",
        f"- Annotations: {pinned_count} pinned, {skip_count} skipped",
        "- Recent activity:",
        recent,
    ]

    prompt = "\n".join(lines)

    if task_context is not None:
        prompt += f"\n\n{task_context}"

    prompt += "\n\nReview the context and determine if any maintenance actions are needed."

    return prompt
