"""Persistent per-user profile storage as Markdown + YAML frontmatter."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


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

    # Markdown body (not stored in frontmatter)
    body: str = ""

    @classmethod
    def create(
        cls,
        *,
        name: str,
        im_ids: dict[str, dict[str, str]],
        **kwargs: Any,
    ) -> UserProfile:
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
        """Serialize profile to a Markdown file with YAML frontmatter."""
        front = {k: v for k, v in asdict(self).items() if k != "body" and v}
        content = "---\n" + yaml.dump(front, allow_unicode=True, sort_keys=False) + "---\n"
        if self.body:
            content += "\n" + self.body
        path.write_text(content, encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> UserProfile:
        """Deserialize a profile from a Markdown file with YAML frontmatter."""
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise ValueError(f"Missing YAML frontmatter in {path}")
        _, fm_raw, *rest = text.split("---", 2)
        front: dict[str, Any] = yaml.safe_load(fm_raw) or {}
        body = rest[0].strip() if rest else ""

        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in front.items() if k in known_fields}
        return cls(**filtered, body=body)


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
            **{
                **{k: v for k, v in profile.__dict__.items() if k != "last_seen" and k != "updated_at"},
                "last_seen": now,
                "updated_at": now,
            }
        )
        self._profiles[profile_id] = updated
        self._write(updated)

    def _write(self, profile: UserProfile) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{profile.id}.md"
        profile.write(path)
