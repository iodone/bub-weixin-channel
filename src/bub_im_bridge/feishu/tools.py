"""Feishu-specific tools for the Bub framework."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from republic import ToolContext

from bub.tools import tool

if TYPE_CHECKING:
    from bub_im_bridge.feishu.channel import FeishuChannel


def _get_feishu_channel(context: ToolContext) -> FeishuChannel:
    """Get FeishuChannel instance from tool context."""
    channel = context.state.get("_feishu_channel")
    if channel is None:
        raise RuntimeError("Feishu channel not available in tool context")
    return channel


class HistoryInput(BaseModel):
    """Input parameters for feishu.history tool."""

    time_range: str | None = Field(
        None,
        description=(
            "Time range for history query. Examples: '1d' (last 1 day), "
            "'7d' (last 7 days), '24h' (last 24 hours). "
            "If not specified, returns the most recent messages."
        ),
    )
    limit: int = Field(
        20,
        description="Maximum number of messages to return (max 50).",
        ge=1,
        le=50,
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
    - "What was the last thing John said?"
    - "查一下最近1天的消息"
    - "看看昨天的聊天记录"
    """
    channel = _get_feishu_channel(context)
    chat_id = context.state.get("_feishu_chat_id")

    if not chat_id:
        return "Error: Cannot determine the current chat. Please try again."

    # Parse time_range to start_time
    start_time = None
    if params.time_range:
        # Convert "24h" to "1d" format if needed
        time_range = params.time_range
        if time_range.endswith("h"):
            try:
                hours = int(time_range[:-1])
                days = hours / 24
                start_time = f"{days:.1f}d"
            except ValueError:
                start_time = time_range
        else:
            start_time = time_range

    history = await channel._fetch_chat_history(
        chat_id=chat_id,
        limit=params.limit,
        start_time=start_time,
    )

    if not history:
        return "No messages found for the specified time range."

    # Format history for display
    lines = [f"Found {len(history)} messages:\n"]
    for msg in history:
        sender = msg.get("sender", "unknown")
        content = msg.get("content", "")
        create_time = msg.get("create_time", "")
        lines.append(f"[{create_time}] {sender}: {content}")

    return "\n".join(lines)
