# User Profile Logic Refinement — Design Spec

**Date:** 2026-04-29  
**Status:** Approved  
**Scope:** Refine the existing user profile system semantics without changing the top-level storage shape.

---

## 1. Overview

The current user profile system already persists per-user Markdown files with YAML frontmatter, but several responsibilities are mixed together:

- Feishu canonical identity and display name semantics are not clearly separated
- automatic sender bootstrap and manual knowledge updates share overlapping write paths
- sender / mentioned users / reply target are not injected into the model as explicit structured context
- placeholder values such as `ou_xxx` can incorrectly persist in `profile.name`

This spec refines the behavior while keeping the current one-file-per-user storage model.

The goal is not to redesign profiles from scratch. The goal is to make the current model predictable:

- Feishu canonical identity must be `im_ids.feishu.open_id`
- `profile.name` must mean display name, not ID
- automatic writes must only patch identity fields
- manual `user.update` writes must only patch knowledge fields
- outbound group replies must not confuse sender and mentioned users

---

## 2. Core Decisions

| Decision | Choice | Rationale |
|:---------|:-------|:----------|
| Feishu canonical identity | `im_ids.feishu.open_id` only | Stable app-scoped user identity; already adopted in runtime logic |
| Feishu auxiliary IDs | `union_id`, `user_id` stored but never used for lookup | Preserve useful metadata without weakening identity semantics |
| Meaning of `profile.name` | Display name only | Human-facing field must not be polluted by canonical IDs |
| Automatic sender write path | Identity patch only | Keep sender bootstrap useful but bounded |
| Manual update write path | Knowledge patch only | Prevent accidental overwrite of identity fields |
| Sender / mentions context | Structured payload, not only flattened text | Reduce LLM confusion in group chats |
| Mention rendering | Based on `open_id`, not name guessing | Avoid wrong-person @mentions |
| Historical dirty data | Lazy repair on next encounter | Avoid one-shot migration complexity |

---

## 3. Data Model Semantics

The profile document remains a single Markdown file with YAML frontmatter, but fields are treated as two semantic layers.

### 3.1 Identity Layer

These fields represent who the user is on IM platforms and what the platform currently reports.

- `id`
  - Internal profile primary key
  - Random short ID
  - Never derived from Feishu IDs

- `name`
  - Human-readable display name
  - For Feishu, should come from message event `sender.name` or Contact API `name`
  - Must not be treated as canonical identity

- `im_ids`
  - Stores platform identity attributes
  - For Feishu:
    - `open_id`: canonical identity
    - `union_id`: auxiliary only
    - `user_id`: auxiliary only

- `department`
- `title`
- `avatar_url`
- `first_seen`
- `last_seen`
- `updated_at`
- `source`

### 3.2 Knowledge Layer

These fields represent longer-lived understanding of the person rather than platform identity.

- `aliases`
- `personality`
- `interests`
- `relationships`
- `body`

### 3.3 Hard Rule

`profile.name` should converge to a real display name.

The following state is considered dirty data, not valid steady state:

```yaml
name: ou_a775e370fb853dd56aa4057b70e7e109
```

If a Feishu profile has `name == im_ids.feishu.open_id`, that value is a placeholder and must be repaired once a real display name is available.

---

## 4. Lookup Semantics

### 4.1 Feishu Lookup

Feishu identity lookup must only use:

```text
platform = "feishu"
id_field = "open_id"
id_value = "ou_..."
```

Rules:

- `union_id` must not be used as lookup key
- `user_id` must not be used as lookup key
- `name` must not be treated as canonical identity

### 4.2 Name Lookup

`lookup_by_name()` remains available as a convenience search mechanism, but it is not authoritative for identity decisions.

Use cases:

- fuzzy human search
- resolving a known profile by display name in tools

Non-use cases:

- sender identity resolution
- mention target resolution
- outbound Feishu @mention rendering

---

## 5. Write Paths

This spec defines three separate write paths with strict boundaries.

### 5.1 Identity Patch

**Entry point:** Feishu channel receives a sender event.

**Flow:**

1. Lookup by `feishu.open_id`
2. If missing, create a minimal profile
3. If present, patch only identity fields

**Allowed fields:**

- `name`
- `im_ids.feishu.open_id`
- `im_ids.feishu.union_id`
- `im_ids.feishu.user_id`
- `department`
- `title`
- `avatar_url`
- `first_seen`
- `last_seen`
- `updated_at`
- `source`

**Forbidden fields:**

- `aliases`
- `personality`
- `interests`
- `relationships`
- `body`

This is the refined replacement for the previous broad `auto-enrich` concept. It should be understood as `identity patch`, not general profile enrichment.

### 5.2 Cognitive Patch

**Entry point:** `user.update`

**Purpose:** update human/agent knowledge about the user without touching identity fields.

**Allowed fields:**

- `aliases`
- `personality`
- `interests`
- `relationships`
- `body`

**Forbidden fields:**

- `name`
- `im_ids`
- `department`
- `title`
- `avatar_url`
- canonical identity of any platform

### 5.3 Manual Create / Repair

**Entry point:** `user.create`

Behavior:

- If the profile does not exist, create it
- If the profile already exists, do not rebuild it
- Existing profile case may only fill missing identity fields
- It must not overwrite knowledge fields

This keeps `user.create` useful for manual repair while avoiding destructive semantics.

---

## 6. Name Maintenance Rules

### 6.1 Priority Order

For Feishu sender identity patch, name candidates are ranked:

1. current message event `sender_name`
2. Feishu Contact API `name`
3. existing `profile.name`
4. temporary in-memory fallback to `open_id`

### 6.2 Persistence Rule

`open_id` may be used as a temporary runtime fallback to avoid null handling, but it must not be treated as a correct persisted display name.

That means:

- creating a new profile with `name = open_id` is tolerated only as placeholder behavior when no real name is available
- once a real display name is later observed, the profile must be upgraded automatically
- identity patch logic should avoid rewriting a good existing display name with weaker information

### 6.3 Upgrade Rule

If a stored profile satisfies:

- `profile.name == profile.im_ids.feishu.open_id`

and a new event or API response contains a real display name, then `profile.name` must be upgraded during identity patch.

---

## 7. Sender, Mentions, and Reply Target

Group chat errors showed that flattened plain text is insufficient context. The model needs structured actor information.

### 7.1 Required Structured Input

Feishu inbound payload passed downstream should include:

```json
{
  "sender": {
    "open_id": "ou_xxx",
    "name": "Zhang Yaodong",
    "user_id": "zhangyaodong",
    "union_id": "on_xxx"
  },
  "mentions": [
    {
      "open_id": "ou_yyy",
      "name": "Philip"
    }
  ],
  "reply_target": {
    "kind": "sender",
    "open_id": "ou_xxx",
    "name": "Zhang Yaodong"
  }
}
```

### 7.2 Behavioral Rules

- default reply target is the current sender
- a mention in the message body must not automatically replace the sender as the reply target
- the model should not output `@someone` unless it explicitly intends to continue addressing that person

This separates:

- who sent the message
- who was mentioned in the message
- who the assistant is replying to

---

## 8. Outbound Mention Rules

Mention rendering must be split into two layers.

### 8.1 Prompt / Decision Layer

The prompt layer decides whether the assistant should continue mentioning someone.

This belongs in prompt-building logic or a `build_prompt`-style hook.

Rules:

- default: reply to sender without emitting any explicit @mention
- only continue `@someone` when the conversation requires explicit addressing
- if choosing to continue `@someone`, the decision must be based on structured actor data, not name guessing

### 8.2 Rendering Layer

The Feishu channel layer is responsible for actual mention rendering.

Rules:

- rendering must use `open_id`
- rendering must not infer target identity from free-form `@Name` text
- sender and mentions must never be resolved through `lookup_by_name()` when producing Feishu mentions

This prevents cases like “replying to 张耀东 but accidentally emitting @Philip”.

---

## 9. Tool Semantics

### 9.1 `user.lookup`

- Feishu ID lookup only accepts `open_id`
- name lookup remains a convenience search, not identity resolution
- if future mention resolution needs exact identity, it must use structured `open_id`

### 9.2 `user.update`

`user.update` is already field-scoped, but its list semantics need explicit protocol guidance.

Rules:

- the tool updates exactly one field at a time
- list fields support append or replace
- agent protocol should default to `append=True` when adding new observations
- `append=False` should be used only for deliberate replacement

This avoids accidental knowledge loss without changing the core tool shape.

### 9.3 `user.create`

- Feishu create path must still require `open_id`
- if profile exists, treat call as identity repair / completion, not full rewrite

---

## 10. Dirty Data Repair Strategy

Historical profiles may already contain placeholder names equal to Feishu `open_id`.

This spec adopts lazy repair, not an eager migration.

### 10.1 Dirty Data Definition

A profile is dirty if:

- `profile.name == im_ids.feishu.open_id`

### 10.2 Repair Trigger

Repair happens when the user appears again and a real display name becomes available from:

- event `sender_name`, or
- Contact API

### 10.3 Repair Action

- replace placeholder `name` with real display name
- keep all other fields unchanged

No bulk migration job is required in this phase.

---

## 11. Testing Requirements

At minimum, add or preserve tests for:

1. Feishu canonical lookup uses only `open_id`
2. `union_id` and `user_id` persist but are not lookup keys
3. placeholder `name == open_id` upgrades to real display name on later identity patch
4. identity patch never modifies knowledge fields
5. `user.update` modifies only the requested field
6. list-field append does not overwrite unrelated knowledge
7. sender / mentions / reply target are injected as structured context
8. outbound mention rendering uses `open_id`, not guessed name resolution

---

## 12. Implementation Notes

This spec intentionally avoids introducing a new storage format or splitting identity and knowledge into separate files. That would be a larger redesign than the current issue requires.

The preferred implementation strategy is:

1. keep `UserProfile` file shape stable
2. refine semantics in `profiles.py`
3. tighten Feishu channel sender patch behavior
4. tighten tool boundaries in `feishu/tools.py`
5. add structured actor payload for prompts
6. add exact-identity outbound mention rendering later if needed

This keeps the change set proportional while making the profile system much more predictable.
