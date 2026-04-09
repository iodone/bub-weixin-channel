"""Feishu-specific tools for the Bub framework."""

from __future__ import annotations

import os
from functools import lru_cache

import lark_oapi as lark
from pydantic import BaseModel, Field
from republic import ToolContext

from bub.tools import tool

from bub_im_bridge.feishu.api import fetch_chat_history


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _build_client() -> lark.Client:
    """Lazily build a shared Feishu API client from environment variables."""
    app_id = os.environ.get("BUB_FEISHU_APP_ID", "")
    app_secret = os.environ.get("BUB_FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("BUB_FEISHU_APP_ID / BUB_FEISHU_APP_SECRET not set")
    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )


def _session_to_chat_id(context: ToolContext) -> str | None:
    """Extract ``chat_id`` from the session id stored in tool context state."""
    session_id = context.state.get("session_id", "")
    if isinstance(session_id, str) and session_id.startswith("feishu:"):
        return session_id.removeprefix("feishu:")
    return None


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


class HistoryInput(BaseModel):
    """Input parameters for feishu.history tool."""

    time_range: str | None = Field(
        None,
        description=(
            "Time range for history query. Examples: '1d' (last 1 day), "
            "'7d' (last 7 days), '3h' (last 3 hours). "
            "If not specified, returns the most recent messages."
        ),
    )


@tool(name="feishu.history", model=HistoryInput, context=True)
async def feishu_history(params: HistoryInput, *, context: ToolContext) -> str:
    """Fetch chat history from the current Feishu conversation.

    Use this tool when the user asks about previous messages, chat history,
    or wants to see what was discussed earlier. Supports time range queries
    like 'last 1 day' or 'last 7 days'.

    Examples of when to use:
    - "What did we discuss yesterday?"
    - "Show me messages from the last week"
    - "查一下最近1天的消息"
    - "看看昨天的聊天记录"
    """
    client = _build_client()

    chat_id = _session_to_chat_id(context)
    if not chat_id:
        return "Error: Cannot determine the current chat."

    history = await fetch_chat_history(
        client,
        chat_id,
        start_time=params.time_range,
    )

    if not history:
        return "No messages found for the specified time range."

    lines = [f"Found {len(history)} messages:\n"]
    for msg in history:
        sender = msg.get("sender", "unknown")
        content = msg.get("content", "")
        create_time = msg.get("create_time", "")
        lines.append(f"[{create_time}] {sender}: {content}")

    return "\n".join(lines)
