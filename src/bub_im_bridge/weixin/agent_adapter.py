"""Adapter to convert Bub Framework into weixin-agent-sdk Agent interface."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from bub.channels.message import ChannelMessage
from bub.framework import BubFramework
from bub.envelope import field_of
from weixin_agent.models import Agent, ChatRequest, ChatResponse


class BubWeixinAgent:
    """Adapter that implements weixin-agent-sdk Agent protocol using Bub Framework."""

    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework
        self._response_futures: dict[str, asyncio.Future[str]] = {}

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Convert weixin ChatRequest to Bub inbound message and process."""
        # Create Bub ChannelMessage
        session_id = f"weixin:{request.conversation_id}"

        content = request.text or ""

        # Handle media attachment
        if request.media:
            content = f"[{request.media.type}] {request.media.file_path}\n{content}"

        # Normalize slash commands to comma commands: /tape.handoff -> ,tape.handoff
        stripped = content.strip()
        if stripped.startswith("/"):
            content = "," + stripped[1:]

        is_command = content.strip().startswith(",")
        inbound = ChannelMessage(
            session_id=session_id,
            channel="weixin",
            content=content,
            chat_id=request.conversation_id,
            kind="command" if is_command else "normal",
            context={
                "sender_id": request.conversation_id,
                "channel": "$weixin",
            },
            output_channel="weixin",
        )

        # Process through Bub framework
        result = await self.framework.process_inbound(inbound)

        # Extract response text from outbounds
        response_text = ""
        for outbound in result.outbounds:
            text = field_of(outbound, "content", "")
            if text:
                response_text = text
                break

        return ChatResponse(text=response_text or None)
