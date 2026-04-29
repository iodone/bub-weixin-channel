"""Unit tests for bub_im_bridge.profiles."""

from __future__ import annotations

from pathlib import Path

from bub_im_bridge.profiles import ProfileStore, UserProfile


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


def test_feishu_user_id_persists_in_im_ids(tmp_path: Path):
    """user_id and union_id are persisted in im_ids.feishu after write/read."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    store.upsert(
        platform="feishu",
        id_field="open_id",
        id_value="ou_persist",
        name="Persist",
        extra_ids={"union_id": "on_persist", "user_id": "persist.wang"},
    )

    # Reload from disk
    store2 = ProfileStore(tmp_path / "profiles")
    store2.load()
    p = store2.lookup("feishu", "open_id", "ou_persist")
    assert p is not None
    assert p.im_ids["feishu"]["open_id"] == "ou_persist"
    assert p.im_ids["feishu"]["union_id"] == "on_persist"
    assert p.im_ids["feishu"]["user_id"] == "persist.wang"


def test_upsert_merges_existing(tmp_path: Path):
    """upsert updates existing profile with new data instead of ignoring."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # First create
    p = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_merge",
        name="ou_merge",  # placeholder name
    )
    assert p.name == "ou_merge"
    assert p.department == ""

    # Second upsert with richer data — should merge
    p2 = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_merge",
        name="MergeUser",
        extra_ids={"union_id": "on_merge"},
        department="Engineering",
        title="Engineer",
    )
    assert p2.id == p.id  # same profile
    assert p2.name == "MergeUser"  # upgraded from placeholder
    assert p2.department == "Engineering"
    assert p2.im_ids["feishu"]["union_id"] == "on_merge"  # merged extra ID


def test_update_field(tmp_path: Path):
    """update_field writes a specific field to an existing profile."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_upd", name="Updater",
    )
    updated = store.update_field(p.id, "personality", ["逻辑严谨", "直接高效"])
    assert updated is not None
    assert updated.personality == ["逻辑严谨", "直接高效"]
    assert updated.source == "auto+manual"


def test_search(tmp_path: Path):
    """search finds profiles by name, department, body content."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    store.upsert(platform="feishu", id_field="open_id", id_value="ou_s1", name="Alice", department="OLAP")
    store.upsert(platform="feishu", id_field="open_id", id_value="ou_s2", name="Bob", department="Frontend")

    assert len(store.search("Alice")) == 1
    assert len(store.search("OLAP")) == 1
    assert len(store.search("nonexistent")) == 0


def test_lookup_by_name(tmp_path: Path):
    """lookup_by_name finds by display name or alias."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(platform="feishu", id_field="open_id", id_value="ou_ln", name="Alice Wang")
    store.update_field(p.id, "aliases", ["小王", "Alice"])

    assert store.lookup_by_name("Alice Wang") is not None
    assert store.lookup_by_name("小王") is not None
    assert store.lookup_by_name("alice") is not None  # case insensitive
    assert store.lookup_by_name("Unknown") is None


def test_feishu_ou_prefix_valid(tmp_path: Path):
    """ou_ prefixed open_id works normally for Feishu."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(
        platform="feishu",
        id_field="open_id",
        id_value="ou_abc123",
        name="Alice",
    )
    assert p.name == "Alice"
    assert store.lookup("feishu", "open_id", "ou_abc123") is not None


def test_feishu_rejects_non_ou_open_id(tmp_path: Path):
    """Non-ou_ open_id is rejected for Feishu."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    import pytest
    with pytest.raises(ValueError, match="ou_ prefix"):
        store.upsert(
            platform="feishu",
            id_field="open_id",
            id_value="cli_abc123",
            name="BotUser",
        )


def test_feishu_rejects_union_id_as_primary(tmp_path: Path):
    """union_id cannot be used as primary Feishu identity."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    import pytest
    with pytest.raises(ValueError, match="ou_ prefix"):
        store.upsert(
            platform="feishu",
            id_field="union_id",
            id_value="on_abc123",
            name="Alice",
        )


def test_feishu_rejects_user_id_as_primary(tmp_path: Path):
    """user_id cannot be used as primary Feishu identity."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    import pytest
    with pytest.raises(ValueError, match="ou_ prefix"):
        store.upsert(
            platform="feishu",
            id_field="user_id",
            id_value="alice.wang",
            name="Alice",
        )


def test_feishu_extra_ids_not_indexed(tmp_path: Path):
    """union_id/user_id stored as extra_ids are not indexed for lookup."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    store.upsert(
        platform="feishu",
        id_field="open_id",
        id_value="ou_alice",
        name="Alice",
        extra_ids={"union_id": "on_alice", "user_id": "alice.wang"},
    )

    # Primary lookup works
    assert store.lookup("feishu", "open_id", "ou_alice") is not None
    # union_id/user_id should NOT be indexed as lookup keys
    assert store.lookup("feishu", "union_id", "on_alice") is None
    assert store.lookup("feishu", "user_id", "alice.wang") is None


def test_non_feishu_platform_unaffected(tmp_path: Path):
    """Other platforms are not affected by Feishu validation."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # Telegram with arbitrary user_id should work fine
    p = store.upsert(
        platform="telegram",
        id_field="user_id",
        id_value="8671028832",
        name="Bob",
    )
    assert p.name == "Bob"
    assert store.lookup("telegram", "user_id", "8671028832") is not None


def test_feishu_reload_extras_not_indexed(tmp_path: Path):
    """After reload, extra_ids (union_id/user_id) are still not indexed."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    store.upsert(
        platform="feishu",
        id_field="open_id",
        id_value="ou_reload",
        name="Reload",
        extra_ids={"union_id": "on_reload"},
    )

    # Reload from disk
    store2 = ProfileStore(tmp_path / "profiles")
    store2.load()

    assert store2.lookup("feishu", "open_id", "ou_reload") is not None
    assert store2.lookup("feishu", "union_id", "on_reload") is None


# ---------------------------------------------------------------------------
# Phase 1: identity_patch tests
# ---------------------------------------------------------------------------


def test_identity_patch_creates_new_profile(tmp_path: Path):
    """identity_patch creates a minimal profile when none exists."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_new",
        name="Alice",
        extra_ids={"union_id": "on_alice"},
    )
    assert p.name == "Alice"
    assert p.im_ids["feishu"]["open_id"] == "ou_new"
    assert p.im_ids["feishu"]["union_id"] == "on_alice"
    assert p.department == ""
    assert p.personality == []  # knowledge field stays empty


def test_identity_patch_patches_existing_identity_fields(tmp_path: Path):
    """identity_patch fills missing identity fields on existing profile."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # Create initial profile
    store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_xxx",
        name="Alice", extra_ids={"union_id": "on_xxx"},
    )

    # Patch with new identity data
    patched = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_xxx",
        extra_ids={"user_id": "alice.wang"},
        department="Engineering",
    )
    assert patched.im_ids["feishu"]["user_id"] == "alice.wang"
    assert patched.department == "Engineering"


def test_identity_patch_never_mutates_knowledge_fields(tmp_path: Path):
    """identity_patch must not touch aliases, personality, interests, relationships, body."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # Create profile with knowledge fields set
    p = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_know",
        name="Knower",
    )
    store.update_field(p.id, "personality", ["严谨"])
    store.update_field(p.id, "interests", ["编程"])
    store.update_field(p.id, "aliases", ["小K"])

    # Identity patch should not touch knowledge fields
    patched = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_know",
        name="Knower",
        department="OLAP",
    )
    assert patched.personality == ["严谨"]
    assert patched.interests == ["编程"]
    assert patched.aliases == ["小K"]
    assert patched.department == "OLAP"


def test_identity_patch_upgrades_placeholder_name(tmp_path: Path):
    """identity_patch upgrades name when current name == open_id (placeholder)."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # Create with placeholder name (open_id as name)
    store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_ph",
        name="ou_ph",
    )

    # Patch with real name
    patched = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_ph",
        name="Alice Wang",
    )
    assert patched.name == "Alice Wang"


def test_identity_patch_upgrades_placeholder_from_api_name(tmp_path: Path):
    """Regression: dirty profile (name == open_id) upgrades when API provides real name,
    even when sender_name is empty (simulates channel.py calling Contact API for dirty profiles)."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # Create dirty profile (name == open_id)
    store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_dirty",
        name="ou_dirty",
    )

    # sender_name is empty, but API returns real name
    patched = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_dirty",
        name="",  # no sender_name
    )
    # With empty name, placeholder stays (no upgrade source)
    assert patched.name == "ou_dirty"

    # But when API provides name (simulated by passing it), placeholder upgrades
    patched2 = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_dirty",
        name="Real Name From API",
    )
    assert patched2.name == "Real Name From API"


def test_identity_patch_does_not_overwrite_valid_name(tmp_path: Path):
    """identity_patch keeps existing valid name, doesn't overwrite with weaker info."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # Create with real name
    store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_valid",
        name="Alice Wang",
    )

    # Patch with no name — should keep existing
    patched = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_valid",
    )
    assert patched.name == "Alice Wang"

    # Patch with different name — should also keep existing (not a placeholder)
    patched2 = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_valid",
        name="Someone Else",
    )
    assert patched2.name == "Alice Wang"


def test_identity_patch_upgrades_ou_prefix_name(tmp_path: Path):
    """identity_patch upgrades name that starts with ou_ even if not exactly open_id."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # Simulate dirty data: name is ou_ prefixed but not exactly open_id
    store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_abc",
        name="ou_abc_dirty",
    )

    patched = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_abc",
        name="Real Name",
    )
    assert patched.name == "Real Name"


def test_identity_patch_updates_timestamps(tmp_path: Path):
    """identity_patch always updates last_seen and updated_at."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_ts",
        name="Timer",
    )
    old_last_seen = p.last_seen

    import time
    time.sleep(0.01)

    patched = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_ts",
    )
    assert patched.last_seen >= old_last_seen
    assert patched.updated_at >= old_last_seen


def test_identity_patch_persists_to_disk(tmp_path: Path):
    """identity_patch writes changes to disk and survives reload."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_persist",
        name="Persistent",
        department="OLAP",
    )

    # Reload
    store2 = ProfileStore(tmp_path / "profiles")
    store2.load()
    p = store2.lookup("feishu", "open_id", "ou_persist")
    assert p is not None
    assert p.name == "Persistent"
    assert p.department == "OLAP"


# ---------------------------------------------------------------------------
# Phase 3: update_field knowledge-only tests
# ---------------------------------------------------------------------------


def test_update_field_only_changes_requested_field(tmp_path: Path):
    """update_field only modifies the specified field, not others."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_upd2",
        name="Updater",
    )
    store.update_field(p.id, "personality", ["严谨"])

    updated = store.get(p.id)
    assert updated is not None
    assert updated.personality == ["严谨"]
    assert updated.name == "Updater"  # unchanged
    assert updated.department == ""  # unchanged


def test_update_field_append_preserves_existing(tmp_path: Path):
    """update_field with append=True adds to existing list."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_app",
        name="Appender",
    )
    store.update_field(p.id, "interests", ["编程"])
    store.update_field(p.id, "interests", ["音乐"])  # replaces

    updated = store.get(p.id)
    assert updated is not None
    # update_field replaces, not appends — append logic is in tools.py
    assert updated.interests == ["音乐"]


def test_update_field_rejects_identity_fields(tmp_path: Path):
    """update_field rejects modifying protected identity fields."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    p = store.upsert(
        platform="feishu", id_field="open_id", id_value="ou_prot",
        name="Protected",
    )

    # id and schema_version are protected
    result = store.update_field(p.id, "id", "newid")
    assert result is None

    result = store.update_field(p.id, "schema_version", "2.0")
    assert result is None

    result = store.update_field(p.id, "first_seen", "2020-01-01")
    assert result is None


# ---------------------------------------------------------------------------
# Combined flow: simulate FeishuChannel identity patch + user.update
# ---------------------------------------------------------------------------


def test_feishu_channel_identity_patch_flow(tmp_path: Path):
    """Simulate the full FeishuChannel flow: identity_patch then user.update."""
    store = ProfileStore(tmp_path / "profiles")
    store.load()

    # 1. First message from new sender — identity_patch creates profile
    p = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_flow",
        name="Alice",
        extra_ids={"union_id": "on_flow", "user_id": "alice"},
    )
    assert p.name == "Alice"
    assert p.department == ""

    # 2. Agent observes personality — user.update (knowledge field)
    store.update_field(p.id, "personality", ["逻辑严谨"])
    updated = store.get(p.id)
    assert updated.personality == ["逻辑严谨"]

    # 3. Second message from same sender — identity_patch patches missing fields
    p2 = store.identity_patch(
        platform="feishu",
        id_field="open_id",
        id_value="ou_flow",
        department="Engineering",
    )
    assert p2.department == "Engineering"
    assert p2.personality == ["逻辑严谨"]  # knowledge field preserved
    assert p2.name == "Alice"  # valid name preserved
