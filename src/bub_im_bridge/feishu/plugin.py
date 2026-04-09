"""Bub plugin entry point for Feishu (Lark) channel."""

from __future__ import annotations

from typing import Any

from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.types import MessageHandler

from bub_im_bridge.feishu.channel import FeishuChannel
from bub_im_bridge.feishu import tools  # noqa: F401 - import to register tools


class FeishPlugin:
    """Plugin that provides Feishu channel for Bub framework."""

    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework

    @hookimpl
    def provide_channels(self, message_handler: MessageHandler) -> list[Any]:
        """Provide Feishu channel to Bub."""
        return [FeishuChannel(on_receive=message_handler, framework=self.framework)]
