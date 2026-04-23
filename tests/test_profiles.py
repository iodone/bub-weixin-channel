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
