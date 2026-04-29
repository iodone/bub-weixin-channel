"""Persistent per-user profile storage as Markdown + YAML frontmatter."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


def _short_uuid() -> str:
    return uuid.uuid4().hex[:8]


def _is_valid_feishu_user_id(id_field: str, id_value: str) -> bool:
    """Only open_id with ou_ prefix is a valid Feishu user canonical identity."""
    return id_field == "open_id" and id_value.startswith("ou_")


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
        front = {k: v for k, v in asdict(self).items() if k != "body"}
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
                if platform == "feishu" and not _is_valid_feishu_user_id(field, value):
                    continue
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
        if platform == "feishu" and not _is_valid_feishu_user_id(id_field, id_value):
            raise ValueError(
                f"Feishu canonical identity must be open_id with ou_ prefix, "
                f"got id_field={id_field!r}, id_value={id_value!r}"
            )
        existing = self.lookup(platform, id_field, id_value)
        if existing is not None:
            # Merge new data into existing profile
            merged_im_ids = dict(existing.im_ids)
            merged_im_ids.setdefault(platform, {})[id_field] = id_value
            if extra_ids:
                merged_im_ids[platform].update(extra_ids)

            changes: dict[str, Any] = {"im_ids": merged_im_ids, "updated_at": _now_iso()}
            if name and name != existing.name and existing.name == id_value:
                changes["name"] = name  # upgrade from placeholder
            if department and not existing.department:
                changes["department"] = department
            if title and not existing.title:
                changes["title"] = title
            if avatar_url and not existing.avatar_url:
                changes["avatar_url"] = avatar_url

            updated = replace(existing, **changes)
            self._profiles[existing.id] = updated
            self._build_index(updated)
            self._write(updated)
            return updated

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

    # Identity fields that can be patched by automatic sender handling
    _IDENTITY_FIELDS = frozenset({
        "name", "im_ids", "department", "title", "avatar_url",
        "first_seen", "last_seen", "updated_at", "source",
    })

    # Knowledge fields that must never be touched by identity patch
    _KNOWLEDGE_FIELDS = frozenset({
        "aliases", "personality", "interests", "relationships", "body",
    })

    def identity_patch(
        self,
        *,
        platform: str,
        id_field: str,
        id_value: str,
        name: str = "",
        extra_ids: dict[str, str] | None = None,
        department: str = "",
        title: str = "",
        avatar_url: str = "",
    ) -> UserProfile:
        """Patch identity fields only. Never touches knowledge fields.

        This is the canonical write path for automatic sender handling.
        - If profile does not exist, creates a minimal profile.
        - If profile exists, patches identity fields only.
        - Handles name == open_id placeholder upgrade.
        - Never writes: aliases, personality, interests, relationships, body.
        """
        if platform == "feishu" and not _is_valid_feishu_user_id(id_field, id_value):
            raise ValueError(
                f"Feishu canonical identity must be open_id with ou_ prefix, "
                f"got id_field={id_field!r}, id_value={id_value!r}"
            )

        existing = self.lookup(platform, id_field, id_value)
        if existing is not None:
            return self._patch_existing_identity(
                existing,
                platform=platform,
                id_field=id_field,
                id_value=id_value,
                name=name,
                extra_ids=extra_ids,
                department=department,
                title=title,
                avatar_url=avatar_url,
            )

        # Create minimal profile with identity fields only
        im_ids: dict[str, dict[str, str]] = {platform: {id_field: id_value}}
        if extra_ids:
            im_ids[platform].update(extra_ids)

        profile = UserProfile.create(
            name=name or id_value,
            im_ids=im_ids,
            department=department,
            title=title,
            avatar_url=avatar_url,
        )
        self._profiles[profile.id] = profile
        self._build_index(profile)
        self._write(profile)
        return profile

    def _patch_existing_identity(
        self,
        existing: UserProfile,
        *,
        platform: str,
        id_field: str,
        id_value: str,
        name: str = "",
        extra_ids: dict[str, str] | None = None,
        department: str = "",
        title: str = "",
        avatar_url: str = "",
    ) -> UserProfile:
        """Apply identity-only patches to an existing profile."""
        changes: dict[str, Any] = {"updated_at": _now_iso(), "last_seen": _now_iso()}

        # Merge im_ids
        merged_im_ids = dict(existing.im_ids)
        merged_im_ids.setdefault(platform, {})[id_field] = id_value
        if extra_ids:
            merged_im_ids[platform].update(extra_ids)
        changes["im_ids"] = merged_im_ids

        # Name upgrade: replace placeholder (name == open_id) with real display name
        if name and name != existing.name:
            is_placeholder = existing.name == id_value or existing.name.startswith("ou_")
            if is_placeholder:
                changes["name"] = name
            # else: keep existing name (don't overwrite a valid display name with weaker info)

        # Fill missing identity fields (don't overwrite existing values)
        if department and not existing.department:
            changes["department"] = department
        if title and not existing.title:
            changes["title"] = title
        if avatar_url and not existing.avatar_url:
            changes["avatar_url"] = avatar_url

        updated = replace(existing, **changes)
        self._profiles[existing.id] = updated
        self._build_index(updated)
        self._write(updated)
        return updated

    def update_field(self, profile_id: str, field_name: str, value: Any) -> UserProfile | None:
        """Update a single field on an existing profile."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            return None
        known = {f.name for f in UserProfile.__dataclass_fields__.values()}
        if field_name not in known or field_name in ("id", "first_seen", "schema_version"):
            return None
        updated = replace(profile, **{field_name: value, "updated_at": _now_iso(), "source": "auto+manual"})
        self._profiles[profile_id] = updated
        if field_name == "im_ids":
            self._build_index(updated)
        self._write(updated)
        return updated

    def search(self, query: str) -> list[UserProfile]:
        """Search profiles by name, aliases, or body content."""
        query_lower = query.lower()
        results = []
        for profile in self._profiles.values():
            if query_lower in profile.name.lower():
                results.append(profile)
                continue
            if any(query_lower in a.lower() for a in profile.aliases):
                results.append(profile)
                continue
            if query_lower in profile.body.lower():
                results.append(profile)
                continue
            if query_lower in profile.department.lower():
                results.append(profile)
                continue
            if query_lower in profile.title.lower():
                results.append(profile)
                continue
        return results

    def lookup_by_name(self, name: str) -> UserProfile | None:
        """Find a profile by display name or alias."""
        name_lower = name.lower()
        for profile in self._profiles.values():
            if profile.name.lower() == name_lower:
                return profile
            if any(a.lower() == name_lower for a in profile.aliases):
                return profile
        return None

    def touch(self, profile_id: str) -> None:
        profile = self._profiles.get(profile_id)
        if profile is None:
            return
        now = _now_iso()
        updated = replace(profile, last_seen=now, updated_at=now)
        self._profiles[profile_id] = updated
        self._write(updated)

    def _write(self, profile: UserProfile) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{profile.id}.md"
        profile.write(path)
