# User Profile Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist per-user profiles as Markdown+YAML files under `{workspace}/profiles/`, auto-creating on first encounter from Feishu Contact API, with O(1) IM-ID lookup.

**Architecture:** A `UserProfile` frozen dataclass models the frontmatter. A `ProfileStore` class handles read/write of `.md` files and maintains an in-memory IM-ID → profile-ID index. `FeishuChannel._dispatch()` calls the store to ensure a profile exists and updates `last_seen` on every interaction.

**Tech Stack:** Python 3.12+, `dataclasses`, `PyYAML` (already a transitive dep via `bub`), `pathlib`, `asyncio.Lock`, `pytest` + `pytest-asyncio`.

---

## File Structure

| Action | File | Responsibility |
|:-------|:-----|:---------------|
| Create | `src/bub_im_bridge/profiles.py` | `UserProfile` dataclass, `ProfileStore` (read/write/index/lookup) |
| Create | `tests/test_profiles.py` | Unit tests for ProfileStore |
| Modify | `src/bub_im_bridge/feishu/channel.py:105-140` | Init ProfileStore; call it from `_dispatch()` |
| Modify | `src/bub_im_bridge/feishu/api.py:277-302` | Extract `fetch_user_info()` returning a dict (not just name) |

---

### Task 1: UserProfile dataclass and YAML serialization

**Files:**
- Create: `src/bub_im_bridge/profiles.py`
- Create: `tests/test_profiles.py`

- [ ] **Step 1: Write failing test for UserProfile creation and YAML round-trip**

```python
"""Unit tests for bub_im_bridge.profiles."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from bub_im_bridge.profiles import UserProfile


def test_create_profile_generates_id():
    p = UserProfile.create(name="Alice", im_ids={"feishu": {"open_id": "ou_aaa"}})
    assert len(p.id) == 8
    assert p.name == "Alice"
    assert p.im_ids == {"feishu": {"open_id": "ou_aaa"}}
    assert p.source == "auto"
    assert p.schema_version == "1.0"
    assert p.first_seen is not None


def test_profile_to_markdown_roundtrip(tmp_path: Path):
    p = UserProfile.create(name="Bob", im_ids={"feishu": {"open_id": "ou_bbb"}})
    path = tmp_path / f"{p.id}.md"
    p.write(path)

    loaded = UserProfile.read(path)
    assert loaded.id == p.id
    assert loaded.name == "Bob"
    assert loaded.im_ids == {"feishu": {"open_id": "ou_bbb"}}
    assert loaded.first_seen == p.first_seen


def test_profile_preserves_body(tmp_path: Path):
    p = UserProfile.create(name="Charlie", im_ids={"feishu": {"open_id": "ou_ccc"}})
    path = tmp_path / f"{p.id}.md"
    p.write(path)

    # Manually append body content
    with open(path, "a") as f:
        f.write("\n## 评价\n\n技术能力扎实。\n")

    loaded = UserProfile.read(path)
    assert loaded.name == "Charlie"
    assert "技术能力扎实" in loaded.body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/test_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bub_im_bridge.profiles'`

- [ ] **Step 3: Implement UserProfile dataclass with read/write**

```python
"""Persistent per-user profile storage as Markdown + YAML frontmatter."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _short_uuid() -> str:
    return uuid.uuid4().hex[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class UserProfile:
    """A single user profile backed by a Markdown+YAML file."""

    id: str
    name: str
    im_ids: dict[str, dict[str, str]]

    aliases: list[str] = field(default_factory=list)
    department: str = ""
    title: str = ""
    avatar_url: str = ""

    personality: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    relationships: list[dict[str, str]] = field(default_factory=list)

    first_seen: str = ""
    last_seen: str = ""
    updated_at: str = ""

    source: str = "auto"
    schema_version: str = "1.0"

    # Markdown body (not in frontmatter)
    body: str = ""

    @classmethod
    def create(cls, *, name: str, im_ids: dict[str, dict[str, str]], **kwargs: Any) -> UserProfile:
        now = _now_iso()
        return cls(
            id=_short_uuid(),
            name=name,
            im_ids=im_ids,
            first_seen=now,
            last_seen=now,
            updated_at=now,
            **kwargs,
        )

    def write(self, path: Path) -> None:
        front = {k: v for k, v in asdict(self).items() if k != "body" and v}
        content = "---\n" + yaml.dump(front, allow_unicode=True, sort_keys=False) + "---\n"
        if self.body:
            content += "\n" + self.body
        path.write_text(content, encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> UserProfile:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise ValueError(f"Missing YAML frontmatter in {path}")
        _, fm_raw, *rest = text.split("---", 2)
        front = yaml.safe_load(fm_raw) or {}
        body = rest[0].strip() if rest else ""

        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in front.items() if k in known_fields}
        return cls(**filtered, body=body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/test_profiles.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
cd ~/work/github/bub-im-bridge
git add src/bub_im_bridge/profiles.py tests/test_profiles.py
git commit -m "feat(profiles): UserProfile dataclass with YAML+Markdown read/write"
```

---

### Task 2: ProfileStore with IM-ID index and lookup

**Files:**
- Modify: `src/bub_im_bridge/profiles.py`
- Modify: `tests/test_profiles.py`

- [ ] **Step 1: Write failing tests for ProfileStore**

Append to `tests/test_profiles.py`:

```python
from bub_im_bridge.profiles import ProfileStore


def test_store_load_and_lookup(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")

    # Create a profile manually
    p = UserProfile.create(name="Alice", im_ids={"feishu": {"open_id": "ou_aaa"}})
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    p.write(profiles_dir / f"{p.id}.md")

    store.load()
    found = store.lookup("feishu", "open_id", "ou_aaa")
    assert found is not None
    assert found.name == "Alice"


def test_store_lookup_missing(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    store.load()
    assert store.lookup("feishu", "open_id", "ou_missing") is None


def test_store_upsert_creates_file(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(
        platform="feishu",
        id_field="open_id",
        id_value="ou_new",
        name="NewUser",
        extra_ids={"union_id": "on_new"},
    )
    assert p.name == "NewUser"
    assert p.im_ids["feishu"]["open_id"] == "ou_new"
    assert p.im_ids["feishu"]["union_id"] == "on_new"

    # File should exist on disk
    path = tmp_path / "profiles" / f"{p.id}.md"
    assert path.exists()

    # Should be findable via lookup
    assert store.lookup("feishu", "open_id", "ou_new") is not None


def test_store_update_last_seen(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(platform="feishu", id_field="open_id", id_value="ou_xxx", name="X")
    old_last_seen = p.last_seen

    import time
    time.sleep(0.01)  # ensure timestamp differs
    store.touch(p.id)

    updated = store.get(p.id)
    assert updated is not None
    assert updated.last_seen >= old_last_seen
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/test_profiles.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProfileStore'`

- [ ] **Step 3: Implement ProfileStore**

Append to `src/bub_im_bridge/profiles.py`:

```python
from loguru import logger


class ProfileStore:
    """Manages user profile files under a directory with IM-ID indexing."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._profiles: dict[str, UserProfile] = {}  # id -> profile
        self._index: dict[str, str] = {}  # "platform:field:value" -> profile id

    def load(self) -> None:
        self._profiles.clear()
        self._index.clear()
        self._dir.mkdir(parents=True, exist_ok=True)
        for path in self._dir.glob("*.md"):
            try:
                profile = UserProfile.read(path)
                self._profiles[profile.id] = profile
                self._build_index(profile)
            except Exception:
                logger.warning("profiles: failed to load {}", path)

    def _build_index(self, profile: UserProfile) -> None:
        for platform, ids in profile.im_ids.items():
            for field, value in ids.items():
                key = f"{platform}:{field}:{value}"
                self._index[key] = profile.id

    def get(self, profile_id: str) -> UserProfile | None:
        return self._profiles.get(profile_id)

    def lookup(self, platform: str, id_field: str, id_value: str) -> UserProfile | None:
        key = f"{platform}:{id_field}:{id_value}"
        profile_id = self._index.get(key)
        return self._profiles.get(profile_id) if profile_id else None

    def upsert(
        self,
        *,
        platform: str,
        id_field: str,
        id_value: str,
        name: str,
        extra_ids: dict[str, str] | None = None,
        department: str = "",
        title: str = "",
        avatar_url: str = "",
    ) -> UserProfile:
        existing = self.lookup(platform, id_field, id_value)
        if existing is not None:
            return existing

        im_ids: dict[str, dict[str, str]] = {platform: {id_field: id_value}}
        if extra_ids:
            im_ids[platform].update(extra_ids)

        profile = UserProfile.create(
            name=name,
            im_ids=im_ids,
            department=department,
            title=title,
            avatar_url=avatar_url,
        )
        self._profiles[profile.id] = profile
        self._build_index(profile)
        self._write(profile)
        return profile

    def touch(self, profile_id: str) -> None:
        profile = self._profiles.get(profile_id)
        if profile is None:
            return
        now = _now_iso()
        updated = UserProfile(
            **{**{k: v for k, v in profile.__dict__.items() if k != "last_seen" and k != "updated_at"},
               "last_seen": now, "updated_at": now}
        )
        self._profiles[profile_id] = updated
        self._write(updated)

    def _write(self, profile: UserProfile) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{profile.id}.md"
        profile.write(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/test_profiles.py -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
cd ~/work/github/bub-im-bridge
git add src/bub_im_bridge/profiles.py tests/test_profiles.py
git commit -m "feat(profiles): ProfileStore with IM-ID index, upsert, and touch"
```

---

### Task 3: Extract `fetch_user_info()` from api.py

**Files:**
- Modify: `src/bub_im_bridge/feishu/api.py:277-302`

- [ ] **Step 1: Write failing test for `fetch_user_info`**

Create `tests/test_api.py`:

```python
"""Unit tests for feishu API helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bub_im_bridge.feishu.api import fetch_user_info


def test_fetch_user_info_returns_dict():
    """fetch_user_info returns a dict with name, department, title, avatar_url."""
    mock_user = MagicMock()
    mock_user.name = "Alice"
    mock_user.department_id = "dept_001"
    mock_user.job_title = "Engineer"
    mock_user.avatar = MagicMock()
    mock_user.avatar.avatar_72 = "https://avatar.url"

    mock_data = MagicMock()
    mock_data.user = mock_user

    mock_resp = MagicMock()
    mock_resp.success.return_value = True
    mock_resp.data = mock_data

    mock_client = MagicMock()
    mock_client.contact.v3.user.get.return_value = mock_resp

    info = fetch_user_info(mock_client, "ou_aaa")
    assert info["name"] == "Alice"
    assert info["job_title"] == "Engineer"
    assert info["avatar_url"] == "https://avatar.url"


def test_fetch_user_info_fallback_on_failure():
    mock_resp = MagicMock()
    mock_resp.success.return_value = False
    mock_resp.code = 41050
    mock_resp.msg = "no permission"

    mock_client = MagicMock()
    mock_client.contact.v3.user.get.return_value = mock_resp

    info = fetch_user_info(mock_client, "ou_bbb")
    assert info["name"] == "ou_bbb"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/test_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_user_info'`

- [ ] **Step 3: Add `fetch_user_info` to api.py**

Add after `_fetch_user_name` in `src/bub_im_bridge/feishu/api.py`:

```python
def fetch_user_info(client: lark.Client, open_id: str) -> dict[str, str]:
    """Fetch user profile fields from Feishu Contact API.

    Returns a dict with keys: name, department_id, job_title, avatar_url.
    Falls back to open_id as name on failure.
    """
    fallback = {"name": open_id, "department_id": "", "job_title": "", "avatar_url": ""}
    if not open_id or open_id.startswith("cli_"):
        fallback["name"] = "bot" if open_id.startswith("cli_") else ""
        return fallback
    try:
        from lark_oapi.api.contact.v3 import GetUserRequest

        req = GetUserRequest.builder().user_id(open_id).user_id_type("open_id").build()
        resp = client.contact.v3.user.get(req)
        if resp.success():
            user = getattr(resp, "data", None)
            user_obj = getattr(user, "user", None) if user else None
            if user_obj:
                avatar = getattr(user_obj, "avatar", None)
                return {
                    "name": getattr(user_obj, "name", None) or open_id,
                    "department_id": getattr(user_obj, "department_id", None) or "",
                    "job_title": getattr(user_obj, "job_title", None) or "",
                    "avatar_url": getattr(avatar, "avatar_72", None) or "" if avatar else "",
                }
        else:
            logger.debug(
                "feishu.api.fetch_user_info failed open_id={} code={} msg={}",
                open_id, resp.code, resp.msg,
            )
    except Exception:
        logger.debug("feishu.api.fetch_user_info error open_id={}", open_id)
    return fallback
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/test_api.py -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
cd ~/work/github/bub-im-bridge
git add src/bub_im_bridge/feishu/api.py tests/test_api.py
git commit -m "feat(feishu): extract fetch_user_info for profile auto-collection"
```

---

### Task 4: Integrate ProfileStore into FeishuChannel

**Files:**
- Modify: `src/bub_im_bridge/feishu/channel.py:105-140` (init)
- Modify: `src/bub_im_bridge/feishu/channel.py:385-447` (_dispatch)

- [ ] **Step 1: Write integration test**

Append to `tests/test_profiles.py`:

```python
def test_store_feishu_integration(tmp_path: Path):
    """Simulate the FeishuChannel flow: lookup-or-create + touch."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # First encounter — profile does not exist, create it
    open_id = "ou_alice"
    profile = store.lookup("feishu", "open_id", open_id)
    assert profile is None

    profile = store.upsert(
        platform="feishu",
        id_field="open_id",
        id_value=open_id,
        name="Alice",
        extra_ids={"union_id": "on_alice", "user_id": "alice"},
        department="Engineering",
    )
    assert profile.name == "Alice"
    assert profile.department == "Engineering"

    # Second encounter — profile exists, just touch
    found = store.lookup("feishu", "open_id", open_id)
    assert found is not None
    store.touch(found.id)

    # Verify persistence — reload from disk
    store2 = ProfileStore(tmp_path / "profiles")
    store2.load()
    reloaded = store2.lookup("feishu", "open_id", open_id)
    assert reloaded is not None
    assert reloaded.name == "Alice"
```

- [ ] **Step 2: Run test to verify it passes** (this validates the store API is correct for integration)

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/test_profiles.py::test_store_feishu_integration -v`
Expected: PASS

- [ ] **Step 3: Add ProfileStore to FeishuChannel.__init__**

In `src/bub_im_bridge/feishu/channel.py`, add import at top:

```python
from bub_im_bridge.profiles import ProfileStore
```

In `__init__` (after line 140, after `self._message_start_time`), add:

```python
        # User profile store
        workspace = os.environ.get("BUB_WORKSPACE", os.getcwd())
        self._profile_store = ProfileStore(Path(workspace) / "profiles")
        self._profile_store.load()
```

Add `from pathlib import Path` to imports if not already present.

- [ ] **Step 4: Add profile lookup/creation to `_dispatch`**

In `src/bub_im_bridge/feishu/channel.py`, in `_dispatch()` method, after `sender_id = message.sender_open_id or ""` (line 388), add:

```python
        # Ensure user profile exists
        if sender_id and message.sender_type != "bot":
            profile = self._profile_store.lookup("feishu", "open_id", sender_id)
            if profile is not None:
                self._profile_store.touch(profile.id)
            else:
                extra_ids: dict[str, str] = {}
                if message.sender_union_id:
                    extra_ids["union_id"] = message.sender_union_id
                if message.sender_user_id:
                    extra_ids["user_id"] = message.sender_user_id

                info = {"name": message.sender_name or sender_id}
                if self._api_client is not None:
                    from bub_im_bridge.feishu.api import fetch_user_info
                    info = fetch_user_info(self._api_client, sender_id)

                self._profile_store.upsert(
                    platform="feishu",
                    id_field="open_id",
                    id_value=sender_id,
                    name=info.get("name", sender_id),
                    extra_ids=extra_ids,
                    department=info.get("department_id", ""),
                    title=info.get("job_title", ""),
                    avatar_url=info.get("avatar_url", ""),
                )
```

- [ ] **Step 5: Run all tests**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/ -v`
Expected: All PASSED

- [ ] **Step 6: Commit**

```bash
cd ~/work/github/bub-im-bridge
git add src/bub_im_bridge/feishu/channel.py src/bub_im_bridge/profiles.py tests/test_profiles.py
git commit -m "feat(feishu): integrate ProfileStore into FeishuChannel dispatch"
```

---

### Task 5: Final verification and PR

- [ ] **Step 1: Run full test suite**

Run: `cd ~/work/github/bub-im-bridge && python -m pytest tests/ -v`
Expected: All PASSED

- [ ] **Step 2: Verify profile file output manually**

Run:
```bash
cd ~/work/github/bub-im-bridge
python -c "
from bub_im_bridge.profiles import ProfileStore, UserProfile
from pathlib import Path
import tempfile, os
d = Path(tempfile.mkdtemp()) / 'profiles'
store = ProfileStore(d)
store.load()
p = store.upsert(platform='feishu', id_field='open_id', id_value='ou_demo', name='Demo User', department='Engineering')
print(open(d / f'{p.id}.md').read())
"
```
Expected: Valid Markdown+YAML profile file printed to stdout.

- [ ] **Step 3: Create feature branch and push**

```bash
cd ~/work/github/bub-im-bridge
git checkout -b feat/user-profiles
git push -u origin feat/user-profiles
```

- [ ] **Step 4: Create PR**

```bash
cd ~/work/github/bub-im-bridge
gh pr create --title "feat: persist user profiles as Markdown+YAML files" --body "$(cat <<'EOF'
## Summary
- Implements #12: persistent per-user profiles stored as Markdown+YAML files
- Each user gets a `{id}.md` file under `{workspace}/profiles/`
- Auto-creates profile on first Feishu interaction with data from Contact API
- O(1) IM-ID → profile lookup via in-memory index
- Updates `last_seen` on every interaction

## Design
See `docs/superpowers/specs/2026-04-23-user-profiles-design.md`

## Test plan
- [ ] Unit tests for UserProfile read/write round-trip
- [ ] Unit tests for ProfileStore index, upsert, touch
- [ ] Unit tests for fetch_user_info API helper
- [ ] Integration test simulating FeishuChannel flow
- [ ] Manual verification of profile file output

Closes #12

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
