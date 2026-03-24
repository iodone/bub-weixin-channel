"""Bub plugin entry point for WeChat channel."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.types import MessageHandler

from bub_weixin_channel.channel import WeixinChannel


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


class WeixinPlugin:
    """Plugin that provides WeChat channel for Bub framework."""

    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework

    @hookimpl
    def provide_channels(self, message_handler: MessageHandler) -> list[Any]:
        """Provide WeChat channel to Bub."""
        return [
            WeixinChannel(
                framework=self.framework,
                on_receive=message_handler,
            )
        ]
