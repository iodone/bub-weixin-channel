# User Profile Persistence — Design Spec

**Issue:** #12 — `feat: persist user profiles to user_profile.json for personalized interactions`  
**Date:** 2026-04-23  
**Status:** Approved  

---

## 1. Overview

Implement a persistent user profile system for bub-im-bridge. Each user gets a structured Markdown file with YAML frontmatter, stored in the Bub workspace. Profiles are auto-populated from IM platform APIs and enriched by Agent observations and human edits.

## 2. Design Decisions

| Decision | Choice | Rationale |
|:---------|:-------|:----------|
| Storage granularity | One file per user | Isolation, per-user loading, human-editable |
| File format | Markdown + YAML frontmatter | Structured metadata + free-text body for subjective content |
| Primary key | Random short UUID | Platform-agnostic; IM IDs are attributes, not keys |
| Relationship model | Embedded in profile | Self-contained; load one user = full context |
| Write model | Mixed mode | Auto-collect basics, Agent infers subjective, human confirms/edits |
| File naming | `{id}.md` | Enables cross-reference by ID |

## 3. Storage Structure

```
{workspace}/profiles/
├── a1b2c3d4.md
├── e5f6a7b8.md
└── c9d0e1f2.md
```

Location: `{BUB_WORKSPACE}/profiles/` (workspace root, alongside existing workspace files).

## 4. Schema

### 4.1 YAML Frontmatter (structured)

```yaml
---
# === Core Identity ===
id: "a1b2c3d4"                    # Required. Random short UUID, system-generated.
name: "Alice Wang"                 # Required. Display name, auto-collected.
aliases: ["小王", "Alice"]         # Optional. Alternative names.

# === IM Platform IDs ===
im_ids:                            # Required. At least one platform.
  feishu:
    open_id: "ou_xxxxxxxxxxxxxxxxxxxx"     # Canonical identity. Must start with ou_.
    union_id: "on_xxxxxxxxxxxxxxxxxxxx"    # Auxiliary. Cross-app ID. Not used for lookup.
    user_id: "alice.wang"                  # Auxiliary. Tenant-internal ID. Not used for lookup.
  telegram:
    user_id: "8671028832"
  wechat:
    wxid: "wxid_xxxxxxxxxxxx"

# === Basic Info (auto-collected) ===
department: "Engineering / OLAP"   # Optional. From Contact API.
title: "Senior Data Engineer"      # Optional. From Contact API.
avatar_url: "https://..."          # Optional. From Contact API.

# === Personality (Agent-inferred + human-confirmed) ===
personality:                       # Optional. Behavioral traits.
  - 逻辑严谨，偏好结构化表达
  - 直接高效，不喜欢冗余沟通

interests:                         # Optional. Topics of interest.
  - 函数式编程
  - 分布式系统

# === Relationships (embedded) ===
relationships:                     # Optional.
  - target_id: "e5f6a7b8"
    relation: "同组同事"
    notes: "Spark 项目搭档"

# === Timestamps (auto-maintained) ===
first_seen: "2026-04-08T10:00:00+08:00"   # Required. Auto-set on creation.
last_seen: "2026-04-23T08:55:00+08:00"    # Required. Auto-updated on interaction.
updated_at: "2026-04-23T08:55:00+08:00"   # Required. Auto-updated on any write.

# === Meta ===
source: "auto+manual"              # Required. auto | manual | auto+manual
schema_version: "1.0"              # Required. For future migrations.
---
```

### 4.2 Markdown Body (free-text sections)

```markdown
## 评价

综合评价，由 Agent 生成或人工编写。

## 过往经历

- [2026-03] 关键事件记录
- [2026-04] 另一个事件

## Agent 观察日志

- [2026-04-10] Agent 在对话中观察到的行为模式
```

### 4.3 Schema Constraints

| Field | Type | Required | Writer |
|:------|:-----|:---------|:-------|
| id | string (8-char hex) | YES | System |
| name | string | YES | Auto-collect |
| aliases | string[] | NO | Agent + Human |
| im_ids | object | YES | Auto-collect |
| department | string | NO | Auto-collect |
| title | string | NO | Auto-collect |
| avatar_url | string | NO | Auto-collect |
| personality | string[] | NO | Agent |
| interests | string[] | NO | Agent |
| relationships | object[] | NO | Agent + Human |
| first_seen | ISO datetime | YES | System |
| last_seen | ISO datetime | YES | System |
| updated_at | ISO datetime | YES | System |
| source | enum | YES | System |
| schema_version | string | YES | Fixed |

## 5. Core Behaviors

### 5.1 Lookup by IM ID

When a message arrives with `sender_open_id=ou_xxx`, the system must:
1. Scan loaded profiles for matching `im_ids.feishu.open_id`
2. If found, return the profile
3. If not found, create a new profile with auto-collected data from Contact API

An in-memory index (`{platform}:{id}` → profile UUID) provides O(1) lookup.

### 5.2 Auto-collection (on first encounter)

When a new user is seen:
1. Generate random short UUID
2. Fetch name, department, title, avatar from Feishu Contact API
3. Set `first_seen`, `last_seen`, `updated_at` to now
4. Set `source: "auto"`
5. Write `{id}.md` to `{workspace}/profiles/`

### 5.3 Last-seen Update

On every interaction from a known user:
1. Update `last_seen` timestamp
2. Rewrite frontmatter (preserve body untouched)

### 5.4 Agent Observation (future phase)

Agent can append to `## Agent 观察日志` section and update `personality`/`interests` fields. This is a follow-up feature — not in scope for the initial implementation.

### 5.5 Thread Safety

Use file-level locking (`fcntl.flock` or `asyncio.Lock` per profile) to prevent concurrent writes from corrupted state.

## 6. Integration Points

### 6.1 FeishuChannel

- In `_dispatch()`: after resolving sender, load or create profile, update `last_seen`
- Inject `sender_profile` into ChannelMessage context for downstream use

### 6.2 Prompt Injection

- In `build_prompt` hook or `feishu_prompts.py`: if sender profile exists, append user context to prompt so Agent knows who it's talking to

### 6.3 Profile Loading

- On startup: load all `profiles/*.md` files, build IM-ID index
- Lazy: load on first access if startup loading is too slow

## 7. Scope

### In scope (this PR)
- Profile data model (dataclass + read/write)
- File I/O: read/write Markdown+YAML profiles
- IM-ID index for fast lookup
- Auto-create on first encounter (Feishu)
- Last-seen update on interaction
- Integration with FeishuChannel dispatch

### Out of scope (future)
- Agent auto-inference of personality/interests
- Human confirmation workflow for Agent-generated content
- WeChat/Telegram profile auto-collection
- Profile management tools (list, search, merge)
- Prompt injection of user context
