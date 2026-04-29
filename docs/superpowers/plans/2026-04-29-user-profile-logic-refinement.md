# User Profile Logic Refinement — Implementation Plan

> Based on: `docs/superpowers/specs/2026-04-29-user-profile-logic-refinement-design.md`

**Goal:** Make Feishu user profiles predictable by separating identity patch from knowledge patch, enforcing `open_id` as canonical lookup key, and eliminating sender/mention/reply-target confusion in group chats.

**Architecture:** Keep the existing one-file-per-user profile format. Refine semantics in three places:

- `profiles.py` owns field-level persistence semantics
- `feishu/channel.py` owns sender identity patch and structured inbound actor context
- `feishu/tools.py` owns manual profile tools and knowledge-field update boundaries

**Tech Stack:** Python 3.14, existing `ProfileStore` / `UserProfile`, Feishu channel runtime, pytest.

---

## File Structure

| Action | File | Responsibility |
|:-------|:-----|:---------------|
| Modify | `src/bub_im_bridge/profiles.py` | Add explicit identity-patch semantics and placeholder-name upgrade rules |
| Modify | `src/bub_im_bridge/feishu/channel.py` | Refine sender bootstrap into identity patch; inject structured sender/mentions/reply_target |
| Modify | `src/bub_im_bridge/feishu/feishu_prompts.py` | Add prompt rules for sender vs mentions vs explicit @ continuation |
| Modify | `src/bub_im_bridge/feishu/tools.py` | Tighten `user.lookup`, `user.create`, `user.update` semantics |
| Modify | `tests/test_profiles.py` | Persistence and patch semantics tests |
| Create/Modify | `tests/test_feishu_*.py` or existing Feishu tests | Structured payload and prompt-context tests |

---

## Phase 1: Identity Patch Semantics

**Intent:** Replace the vague `auto-enrich` behavior with explicit sender identity patch semantics.

- [ ] Add a dedicated `ProfileStore` method for identity patching existing profiles instead of overloading generic `upsert` semantics
- [ ] Ensure Feishu sender patch only uses `open_id` for lookup
- [ ] Preserve `union_id` and `user_id` as auxiliary fields only
- [ ] Allow patching only these fields through identity patch:
  - `name`
  - `im_ids.feishu.{open_id, union_id, user_id}`
  - `department`
  - `title`
  - `avatar_url`
  - `first_seen / last_seen / updated_at / source`
- [ ] Forbid identity patch from mutating:
  - `aliases`
  - `personality`
  - `interests`
  - `relationships`
  - `body`

**Acceptance criteria:**

- sender bootstrap no longer relies on ambiguous generic write semantics
- a repeated sender event performs field-scoped identity patch only
- no knowledge fields are touched by automatic sender handling

---

## Phase 2: `profile.name` Repair and Upgrade Rules

**Intent:** Make `profile.name` reliably mean display name rather than `open_id`.

- [ ] Treat `name == im_ids.feishu.open_id` as placeholder/dirty state
- [ ] Upgrade placeholder `name` when a real display name is later observed from:
  - Feishu event `sender_name`
  - Feishu Contact API `name`
- [ ] Avoid writing weaker identity information over a valid existing display name
- [ ] Keep `open_id` only as runtime fallback, not a steady-state semantic name

**Acceptance criteria:**

- existing dirty profiles self-heal on subsequent sender encounters
- newly created or patched profiles converge toward real display names
- `open_id` remains in `im_ids.feishu.open_id`, not as the intended human-facing `name`

---

## Phase 3: Tool Boundary Tightening

**Intent:** Make tool semantics match the approved spec.

### `user.lookup`

- [ ] Keep Feishu ID lookup restricted to `open_id`
- [ ] Keep name lookup as convenience search only
- [ ] Document clearly that name lookup is not canonical identity resolution

### `user.create`

- [ ] Keep Feishu create requiring `open_id`
- [ ] If profile exists, treat create as identity completion / repair only
- [ ] Do not let `user.create` rewrite knowledge fields

### `user.update`

- [ ] Restrict updates to knowledge fields only:
  - `aliases`
  - `personality`
  - `interests`
  - `relationships`
  - `body`
- [ ] Keep updates field-scoped
- [ ] Preserve explicit `append=True` vs `append=False` behavior
- [ ] Tighten tool docs/prompt guidance so agents use `append=True` by default when adding observations

**Acceptance criteria:**

- no tool can accidentally rewrite Feishu canonical identity
- `user.update` remains field-level patch, not profile rewrite
- knowledge additions are append-safe by protocol, not by guesswork

---

## Phase 4: Structured Actor Context for Group Chats

**Intent:** Stop the model from confusing sender, mentioned users, and reply target.

- [ ] Extend Feishu inbound payload to include structured actor data:
  - `sender`
  - `mentions[]`
  - `reply_target`
- [ ] Keep flattened text for normal conversation, but do not rely on it as the only actor source
- [ ] Define `reply_target` default as current sender
- [ ] Ensure a mention in the body does not automatically replace the reply target

**Acceptance criteria:**

- downstream model sees sender and mentions as separate structured objects
- reply logic no longer depends on parsing raw text names alone

---

## Phase 5: Prompt Rules for Reply Target and Mentions

**Intent:** Reduce incorrect human-facing addressing before implementing full precise mention rendering.

- [ ] Update `feishu_prompts.py` with explicit rules:
  - default reply to sender
  - do not switch addressee because multiple names appear in the text
  - do not emit explicit `@name` unless continuation requires it
  - if explicit addressing is needed, prefer structured actor context rather than free-form guessing
- [ ] Add a rule that if sender display name is already present in structured context or profile, the model must not claim it is unknown

**Acceptance criteria:**

- fewer “I don’t know your name” hallucinations when name is already available
- fewer wrong-person replies in group chats

---

## Phase 6: Outbound Mention Rendering Foundation

**Intent:** Prepare the path toward exact Feishu mentions without mixing it into prompt logic.

- [ ] Keep the decision of whether to continue `@someone` in prompt/build-hook logic
- [ ] Reserve actual mention rendering for Feishu channel logic
- [ ] Ensure future exact mention rendering uses `open_id`, not `lookup_by_name()`
- [ ] Do not attempt free-form name-to-identity guessing in the outbound renderer

**Acceptance criteria:**

- channel rendering layer has a clean future extension point
- exact mentions can later be added without redefining profile semantics again

---

## Phase 7: Test Coverage

- [ ] Add tests for Feishu canonical lookup using only `open_id`
- [ ] Add tests proving `union_id` and `user_id` persist but are not lookup keys
- [ ] Add tests proving placeholder `name == open_id` upgrades on later sender identity patch
- [ ] Add tests proving identity patch never mutates knowledge fields
- [ ] Add tests proving `user.update` only changes the requested field
- [ ] Add tests proving structured `sender / mentions / reply_target` are present in the built payload
- [ ] Add tests for prompt rules that guard against wrong reply targets

---

## Recommended Execution Order

1. Phase 1 — identity patch semantics
2. Phase 2 — `profile.name` repair and upgrade
3. Phase 3 — tool boundary tightening
4. Phase 4 — structured actor context
5. Phase 5 — prompt rules
6. Phase 7 — tests
7. Phase 6 — outbound mention rendering foundation

Rationale:

- phases 1-3 fix the data contract first
- phases 4-5 fix the model-input contract next
- tests lock both down before extending mention rendering
- phase 6 can stay minimal now and evolve later

---

## Suggested Task Split

### Forger

- implement phases 1-3
- add tests for persistence/tool semantics

### Razor

- review phases 4-5 behavior from the perspective of group-chat correctness
- add or validate tests around sender vs mentions vs reply target confusion

### Weaver

- review interface boundaries and acceptance criteria
- confirm that implementation matches the approved spec before merge

---

## Done Criteria

This plan is complete when:

- Feishu sender identity is always keyed by `open_id`
- `profile.name` converges to display name rather than `open_id`
- automatic sender handling never mutates knowledge fields
- manual profile tools have explicit and non-overlapping semantics
- structured actor context prevents sender/mention confusion
- the approved spec and the implementation behavior are aligned
