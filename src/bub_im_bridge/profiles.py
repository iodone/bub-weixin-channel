"""Persistent per-user profile storage as Markdown + YAML frontmatter."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
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
