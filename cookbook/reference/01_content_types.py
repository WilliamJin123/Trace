"""Content Types, Shorthand, Formatting, Batch, Status, Chat + Persistence

Quick reference for the commit/compile surface area:
- 10 content types and when to use each
- Shorthand: t.system(), t.user(), t.assistant()
- Format: compile().to_dicts(), .to_openai(), .to_anthropic(), .pprint()
- Batch: t.batch() for atomic multi-commit
- Status: t.status() token tracking
- Chat + persistence: t.chat(), reopening from disk
"""

from tract import (
    Tract, InstructionContent, DialogueContent, ToolIOContent,
    ReasoningContent, ArtifactContent, OutputContent, FreeformContent,
    ConfigContent, MetadataContent, TractConfig, TokenBudgetConfig,
)


def main():
    # =================================================================
    # 1. CONTENT TYPES — manual commit with t.commit(ContentModel(...))
    # =================================================================
    t = Tract.open()
    print("=== 1. Content Types ===\n")

    ci = t.commit(InstructionContent(text="You are a helpful assistant."))
    print(f"  InstructionContent:  {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(DialogueContent(role="user", text="Hello"))
    print(f"  DialogueContent:     {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(DialogueContent(role="assistant", text="Hi there!"))
    print(f"  DialogueContent:     {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(ToolIOContent(
        tool_name="search", direction="call",
        payload={"query": "weather"}, status="success",
    ))
    print(f"  ToolIOContent:       {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(ReasoningContent(text="Let me think step by step..."))
    print(f"  ReasoningContent:    {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(ArtifactContent(
        artifact_type="code", content="print('hello')", language="python",
    ))
    print(f"  ArtifactContent:     {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(OutputContent(text="Result: 42", format="text"))
    print(f"  OutputContent:       {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(FreeformContent(payload={"custom_key": "custom_value"}))
    print(f"  FreeformContent:     {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(ConfigContent(settings={"temperature": 0.7, "model": "gpt-4o"}))
    print(f"  ConfigContent:       {ci.commit_hash[:8]}  {ci.message}")

    ci = t.commit(MetadataContent(kind="tag", data={"version": "1.0"}))
    print(f"  MetadataContent:     {ci.commit_hash[:8]}  {ci.message}")

    t.close()

    # =================================================================
    # 2. SHORTHAND — no imports needed, auto-creates DialogueContent
    # =================================================================
    t = Tract.open()
    print("\n=== 2. Shorthand ===\n")

    ci = t.system("You are a helpful assistant.")
    print(f"  t.system():    {ci.commit_hash[:8]}  {ci.content_type}  {ci.message}")

    ci = t.user("What is Python?")
    print(f"  t.user():      {ci.commit_hash[:8]}  {ci.content_type}  {ci.message}")

    ci = t.assistant("A programming language.")
    print(f"  t.assistant(): {ci.commit_hash[:8]}  {ci.content_type}  {ci.message}")

    # =================================================================
    # 3. FORMAT METHODS — compile() output for any LLM provider
    # =================================================================
    ctx = t.compile()

    # Generic list of {"role": ..., "content": ...}
    dicts = ctx.to_dicts()
    print("\n=== 3. Format Methods ===\n")
    print(f"  to_dicts():    {len(dicts)} messages")
    for d in dicts:
        print(f"    [{d['role']}] {d['content'][:60]}")

    # OpenAI format — ready for openai.chat.completions.create(messages=...)
    openai_msgs = ctx.to_openai()
    print(f"\n  to_openai():   {len(openai_msgs)} messages")

    # Anthropic format — system extracted, ready for anthropic.messages.create(**...)
    anthropic_fmt = ctx.to_anthropic()
    # anthropic_fmt == {"system": "...", "messages": [...]}
    print(f"  to_anthropic(): system={anthropic_fmt['system'][:40]}..., {len(anthropic_fmt['messages'])} messages")

    # Pretty-print (Rich tables) — three styles available
    print(f"\n  pprint styles: 'table' (default), 'chat', 'compact'")

    # Compact summary via str()
    print(ctx)  # e.g. "3 messages | 45 tokens"

    t.close()

    # =================================================================
    # 4. BATCH — atomic multi-commit (all-or-nothing)
    # =================================================================
    t = Tract.open()
    t.system("You are an assistant.")

    count_before = len(t.compile().messages)
    print("\n=== 4. Batch ===\n")
    try:
        with t.batch():
            t.user("Question 1")
            t.user("Question 2")
            raise RuntimeError("Simulated failure")  # triggers rollback
    except RuntimeError:
        pass

    count_after = len(t.compile().messages)
    assert count_before == count_after  # nothing landed
    print(f"  Batch rollback: {count_before} -> {count_after} messages (unchanged)")

    with t.batch():  # retry succeeds
        t.user("Question 1")
        t.user("Question 2")

    assert len(t.compile().messages) == 3  # system + 2 questions
    print(f"  Batch success:  {len(t.compile().messages)} messages (system + 2 questions)")
    t.close()

    # =================================================================
    # 5. STATUS — token counting and budget tracking
    # =================================================================
    t = Tract.open()
    t.system("You are helpful.")
    t.user("Hello")
    print("\n=== 5. Status ===\n")

    status = t.status()
    print(status)                       # compact one-liner
    print(status.commit_count)          # number of commits
    print(status.token_count)           # current token usage
    print(status.token_budget_max)      # None if no budget set

    # With a budget:
    config = TractConfig(token_budget=TokenBudgetConfig(max_tokens=4096))
    t2 = Tract.open(config=config)
    t2.system("You are helpful.")
    s = t2.status()
    if s.token_budget_max:
        pct = s.token_count / s.token_budget_max * 100
        print(f"Budget: {pct:.0f}% used")
    s.pprint()  # rich panel view
    t2.close()
    t.close()

    # =================================================================
    # 6. CHAT + PERSISTENCE — t.chat() and reopening from disk
    # =================================================================
    # chat() = commit user msg + compile + call LLM + commit response + record usage
    # Requires api_key/model on open():
    #   t = Tract.open(api_key="...", model="gpt-4o")
    #   r = t.chat("What is Python?")
    #   r.text           # response text
    #   r.usage          # token usage from API
    #   r.pprint()       # rich panel

    # Persistence — pass a db_path to save to disk:
    #   t = Tract.open("conversation.db", api_key="...", model="gpt-4o")
    #   t.chat("Hello")
    #   t.close()
    #   # Later: reopen and continue
    #   t = Tract.open("conversation.db", api_key="...", model="gpt-4o")
    #   t.chat("Follow-up")  # includes all prior context automatically

    print("Content types reference complete.")


if __name__ == "__main__":
    main()
