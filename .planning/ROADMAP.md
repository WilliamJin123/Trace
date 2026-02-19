# Roadmap: Tract

## Milestones

- v1.0 Core (Phases 1-5) -- shipped 2026-02-16
- v2.0 Autonomy (Phases 6-7) -- shipped 2026-02-18
- v3.0 DX & API Overhaul (Phases 8-10) -- in progress

## Phases

<details>
<summary>v1.0 Core (Phases 1-5) -- SHIPPED 2026-02-16</summary>

### Phase 1: Foundations
**Plans**: 3/3 complete

### Phase 1.1: Compile Cache & Token Tracking
**Plans**: 2/2 complete

### Phase 1.2: Rename Repo to Tract
**Plans**: 1/1 complete

### Phase 1.3: Hyperparameter Config Storage
**Plans**: 1/1 complete

### Phase 1.4: LRU Compile Cache & Snapshot Patching
**Plans**: 1/1 complete

### Phase 2: Linear History & CLI
**Plans**: 3/3 complete

### Phase 3: Branching & Merging
**Plans**: 5/5 complete

### Phase 4: Compression
**Plans**: 3/3 complete

### Phase 5: Multi-Agent & Release
**Plans**: 3/3 complete

</details>

<details>
<summary>v2.0 Autonomy (Phases 6-7) -- SHIPPED 2026-02-18</summary>

### Phase 6: Policy Engine
**Plans**: 3/3 complete

### Phase 7: Agent Toolkit & Orchestrator
**Plans**: 3/3 complete

</details>

### v3.0 DX & API Overhaul (In Progress)

**Milestone Goal:** Rich functionality through minimal interfaces. Easy for the common case, configurable for every edge case. Cookbook-driven -- every API change must make a cookbook example simpler.

**Phase Numbering:** Integer phases (8, 9, 10): Planned milestone work. Decimal phases (8.1, 9.1): Urgent insertions.

- [ ] **Phase 8: Format & Commit Shorthand** - Eliminate import ceremony and output boilerplate
- [ ] **Phase 9: Conversation Layer** - One-call chat/generate with integrated LLM
- [ ] **Phase 10: Per-Operation LLM Config** - Independent model/params per LLM-powered operation

## Phase Details

### Phase 8: Format & Commit Shorthand
**Goal**: Users can commit messages and consume compiled output without importing content models or writing list comprehensions
**Depends on**: Phase 7 (v2.0 complete)
**Requirements**: CORE-01, CORE-02, CORE-03, FMT-01, FMT-02
**Success Criteria** (what must be TRUE):
  1. User can call t.system("prompt"), t.user("hello"), t.assistant("response") without importing any content model classes
  2. User can call compiled.to_dicts() and receive a list[dict] with "role" and "content" keys ready for any LLM API
  3. User can call compiled.to_openai() and compiled.to_anthropic() and receive provider-specific formatted messages
  4. User can omit the message= parameter on commit() and get an auto-generated commit message describing the content
  5. CORE-02 verified: the path from compile() to LLM-ready dicts requires zero manual transformation
**Plans**: TBD

Plans:
- [ ] 08-01: TBD

### Phase 9: Conversation Layer
**Goal**: Users can have multi-turn LLM conversations with version control using 1-2 lines per turn instead of 15
**Depends on**: Phase 8
**Requirements**: LLM-01, LLM-02, LLM-03, CONV-01, CONV-02, CONV-03
**Success Criteria** (what must be TRUE):
  1. User can pass api_key, model, and base_url to Tract.open() and have an LLM ready to use without a separate configure_llm() call
  2. User can call response = t.chat("question") and get back a response where response.text contains the assistant's reply -- one call did commit + compile + LLM call + assistant commit + usage recording
  3. User can call t.user("question") followed by response = t.generate() to have explicit control over when the user message is committed vs when the LLM is called
  4. Response object from chat/generate exposes .text, .usage, .commit_info, and .generation_config
  5. After chat() or generate(), the commit's generation_config is automatically populated from the LLM request parameters (model, temperature, etc.) and record_usage() is automatically called with the API response token counts
**Plans**: TBD

Plans:
- [ ] 09-01: TBD

### Phase 10: Per-Operation LLM Config
**Goal**: Users can configure different models and parameters for each LLM-powered operation independently
**Depends on**: Phase 9
**Requirements**: LLM-04
**Success Criteria** (what must be TRUE):
  1. User can configure chat/generate to use one model while merge uses a different model, without reconfiguring the Tract instance between operations
  2. User can set per-operation defaults (e.g., compress always uses a cheap model, chat uses a powerful model) that persist across calls
  3. User can override per-operation config on individual calls (e.g., t.chat("complex question", model="gpt-4o") even when default chat model is gpt-4o-mini)
**Plans**: TBD

Plans:
- [ ] 10-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 8 -> 9 -> 10 (plus any inserted decimal phases)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundations | v1.0 | 3/3 | Complete | 2026-02-10 |
| 1.1. Compile Cache | v1.0 | 2/2 | Complete | 2026-02-11 |
| 1.2. Rename | v1.0 | 1/1 | Complete | 2026-02-11 |
| 1.3. Hyperparams | v1.0 | 1/1 | Complete | 2026-02-11 |
| 1.4. LRU Cache | v1.0 | 1/1 | Complete | 2026-02-11 |
| 2. Linear History | v1.0 | 3/3 | Complete | 2026-02-12 |
| 3. Branching | v1.0 | 5/5 | Complete | 2026-02-14 |
| 4. Compression | v1.0 | 3/3 | Complete | 2026-02-16 |
| 5. Multi-Agent | v1.0 | 3/3 | Complete | 2026-02-16 |
| 6. Policy Engine | v2.0 | 3/3 | Complete | 2026-02-17 |
| 7. Agent Toolkit | v2.0 | 3/3 | Complete | 2026-02-18 |
| 8. Format & Shorthand | v3.0 | 0/? | Not started | - |
| 9. Conversation Layer | v3.0 | 0/? | Not started | - |
| 10. Per-Op LLM Config | v3.0 | 0/? | Not started | - |
