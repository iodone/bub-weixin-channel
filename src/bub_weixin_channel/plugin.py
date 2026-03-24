"""Bub plugin entry point for WeChat channel."""

from __future__ import annotations

from typing import Any

from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.types import MessageHandler

from bub_weixin_channel.channel import WeixinChannel


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
