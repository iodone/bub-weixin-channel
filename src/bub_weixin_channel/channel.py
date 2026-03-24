"""WeChat channel implementation for Bub framework."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from loguru import logger

from bub.channels.base import Channel
from bub.channels.message import ChannelMessage
from bub.framework import BubFramework
from bub.hookspecs import hookimpl

from bub_weixin_channel.agent_adapter import BubWeixinAgent


class WeixinChannel(Channel):
    """WeChat channel using weixin-agent-sdk."""

    name: ClassVar[str] = "weixin"

    def __init__(self, framework: BubFramework, on_receive: Any = None) -> None:
        self.framework = framework
        self._on_receive = on_receive
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._agent = BubWeixinAgent(framework)

    @property
    def needs_debounce(self) -> bool:
        """WeChat messages need debounce like Telegram."""
        return True

    async def start(self, stop_event: asyncio.Event) -> None:
        """Start WeChat bot polling."""
        self._stop_event = stop_event
        
        # Import weixin_agent here to avoid import errors if not installed
        try:
            from weixin_agent import start as weixin_start
            from weixin_agent.models import StartOptions
        except ImportError:
            logger.error("weixin-agent-sdk not installed. Run: uv add weixin-agent-sdk")
            return

        logger.info("[weixin] starting bot")
        
        # Start weixin bot in background task
        async def run_bot():
            try:
                await weixin_start(
                    self._agent,
                    options=StartOptions(
                        log=lambda msg: logger.info(f"[weixin] {msg}")
                    ),
                )
            except asyncio.CancelledError:
                logger.info("weixin.bot cancelled")
            except Exception as e:
                logger.error(f"weixin.bot error: {e}")
                if self._stop_event:
                    self._stop_event.set()

        self._task = asyncio.create_task(run_bot())
        
        # Wait for stop signal
        await stop_event.wait()
        
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        """Stop WeChat bot."""
        logger.info("weixin.stop stopping")
        if self._stop_event:
            self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send(self, message: ChannelMessage) -> None:
        """Send message through WeChat channel.
        
        Note: weixin-agent-sdk handles sending internally through the Agent.chat() response.
        This method is not used for normal flow, but kept for interface compatibility.
        """
        logger.debug(f"weixin.send called (handled by agent.chat): {message.content[:50]}...")
