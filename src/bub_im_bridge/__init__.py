"""Bub IM Bridge - Multi-channel support for Bub framework."""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv_to_environ() -> None:
    """Load .env file into os.environ so subprocess calls inherit env vars."""
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_to_environ()
