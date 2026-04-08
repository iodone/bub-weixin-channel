"""Feishu-specific tools for the Bub framework."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from republic import ToolContext

from bub.tools import tool

if TYPE_CHECKING:
    from bub_im_bridge.feishu.channel import FeishuChannel

# Global reference to the active FeishuChannel instance.
# Set by FeishuChannel.start(), read by tools at call time.
_channel_instance: FeishuChannel | None = None


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
    if _channel_instance is None:
        return "Error: Feishu channel is not available."

    # Resolve chat_id from session_id in state (format: "feishu:{chat_id}")
    session_id = context.state.get("session_id", "")
    chat_id = ""
    if isinstance(session_id, str) and session_id.startswith("feishu:"):
        chat_id = session_id.removeprefix("feishu:")

    if not chat_id:
        return "Error: Cannot determine the current chat."

    # Parse time_range to start_time
    start_time = None
    if params.time_range:
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

    history = await _channel_instance._fetch_chat_history(
        chat_id=chat_id,
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
