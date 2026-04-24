"""Feishu-specific tools for the Bub framework."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import lark_oapi as lark
from pydantic import BaseModel, Field
from republic import ToolContext

from bub.tools import tool

from bub_im_bridge.feishu.api import fetch_chat_history
from bub_im_bridge.profiles import ProfileStore


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


# ---------------------------------------------------------------------------
# Profile store singleton
# ---------------------------------------------------------------------------


def _get_profile_store(context: ToolContext) -> ProfileStore:
    """Get the shared ProfileStore from ToolContext (injected by FeishuChannel)."""
    store = context.state.get("_profile_store")
    if store is not None:
        return store
    # Fallback: require _runtime_workspace; never use os.getcwd() which may
    # resolve to an unrelated directory (e.g. ~/.bub) inside the sandbox.
    workspace = context.state.get("_runtime_workspace")
    if not workspace:
        raise RuntimeError("profile tools require _profile_store or _runtime_workspace in context")
    store = ProfileStore(Path(workspace) / "profiles")
    store.load()
    return store


# ---------------------------------------------------------------------------
# User profile tools
# ---------------------------------------------------------------------------


class UserLookupInput(BaseModel):
    """Input for user.lookup tool."""

    name: str | None = Field(None, description="用户显示名或别名，如 'Alice' 或 '小王'")
    platform: str | None = Field(None, description="IM 平台，如 'feishu'")
    id_field: str | None = Field(None, description="ID 字段名，如 'open_id'")
    id_value: str | None = Field(None, description="ID 值，如 'ou_xxx'")


@tool(name="user.lookup", model=UserLookupInput, context=True)
async def user_lookup(params: UserLookupInput, *, context: ToolContext) -> str:
    """查找用户 profile。可以按名字或 IM ID 查找。

    当消息中提及某个用户（如 @某某），或需要了解某人的信息时使用此工具。
    按名字查找时使用 name 参数，按 IM ID 查找时使用 platform + id_field + id_value。
    """
    store = _get_profile_store(context)

    profile = None
    if params.name:
        profile = store.lookup_by_name(params.name)
    elif params.platform and params.id_field and params.id_value:
        profile = store.lookup(params.platform, params.id_field, params.id_value)
    else:
        return "错误：需要提供 name 或 platform+id_field+id_value"

    if profile is None:
        return f"未找到用户 profile（查询: name={params.name}, platform={params.platform}）"

    return _format_profile(profile)


class UserSearchInput(BaseModel):
    """Input for user.search tool."""

    query: str = Field(..., description="搜索关键词，匹配名字、别名、部门、职位、profile 内容")


@tool(name="user.search", model=UserSearchInput, context=True)
async def user_search(params: UserSearchInput, *, context: ToolContext) -> str:
    """搜索用户 profile。按关键词在名字、别名、部门、职位、profile 内容中搜索。

    当需要查找"谁负责某事"、搜索特定领域的人、或模糊查找用户时使用此工具。
    """
    store = _get_profile_store(context)
    results = store.search(params.query)

    if not results:
        return f"未找到匹配 '{params.query}' 的用户"

    lines = [f"找到 {len(results)} 个匹配用户:\n"]
    for p in results[:10]:
        dept = f" ({p.department})" if p.department else ""
        lines.append(f"- **{p.name}**{dept} [id: {p.id}]")
    return "\n".join(lines)


class UserUpdateInput(BaseModel):
    """Input for user.update tool."""

    user_id: str | None = Field(None, description="用户 profile ID（8位 hex）")
    user_name: str | None = Field(None, description="用户显示名（如果不知道 ID，可以用名字查找）")
    field: str = Field(..., description="要更新的字段: personality, interests, aliases, relationships, body")
    value: str = Field(..., description="新值。列表字段用 JSON 数组格式，如 '[\"特征1\", \"特征2\"]'")
    append: bool = Field(False, description="是否追加到现有列表（仅对列表字段有效）")


@tool(name="user.update", model=UserUpdateInput, context=True)
async def user_update(params: UserUpdateInput, *, context: ToolContext) -> str:
    """更新用户 profile 的字段。

    当观察到用户的行为特征、兴趣爱好、人际关系等信息时，使用此工具记录到对应 profile。
    支持更新: personality（个性特征）, interests（兴趣爱好）, aliases（别名）,
    relationships（人际关系）, body（自由文本，如评价、观察日志）。
    """
    store = _get_profile_store(context)

    # Resolve profile
    profile = None
    if params.user_id:
        profile = store.get(params.user_id)
    elif params.user_name:
        profile = store.lookup_by_name(params.user_name)

    if profile is None:
        return f"未找到用户 (id={params.user_id}, name={params.user_name})"

    allowed_fields = {"personality", "interests", "aliases", "relationships", "body"}
    if params.field not in allowed_fields:
        return f"不允许更新字段 '{params.field}'。允许的字段: {', '.join(sorted(allowed_fields))}"

    # Parse value
    if params.field == "body":
        if params.append:
            new_value = profile.body + "\n" + params.value if profile.body else params.value
        else:
            new_value = params.value
    else:
        # List fields
        try:
            parsed = json.loads(params.value) if params.value.startswith("[") else [params.value]
        except json.JSONDecodeError:
            parsed = [params.value]

        if params.append:
            existing = getattr(profile, params.field, [])
            new_value = list(existing) + parsed
        else:
            new_value = parsed

    updated = store.update_field(profile.id, params.field, new_value)
    if updated is None:
        return "更新失败"

    return f"已更新 {updated.name} 的 {params.field}"


class UserCreateInput(BaseModel):
    """Input for user.create tool."""

    name: str = Field(..., description="用户显示名")
    platform: str = Field("feishu", description="IM 平台，如 'feishu'")
    id_field: str = Field("open_id", description="ID 字段名，如 'open_id'")
    id_value: str = Field(..., description="ID 值，如 'ou_xxx'")
    department: str = Field("", description="部门")
    title: str = Field("", description="职位")


@tool(name="user.create", model=UserCreateInput, context=True)
async def user_create(params: UserCreateInput, *, context: ToolContext) -> str:
    """创建新用户 profile。

    当需要手动创建一个新的用户 profile 时使用此工具。
    如果用户已存在（相同 platform + id_field + id_value），会更新已有 profile。
    """
    store = _get_profile_store(context)

    profile = store.upsert(
        platform=params.platform,
        id_field=params.id_field,
        id_value=params.id_value,
        name=params.name,
        department=params.department,
        title=params.title,
    )
    return f"已创建/更新 profile: {profile.name} (id: {profile.id})"


def _format_profile(profile) -> str:
    """Format a profile for display to the agent."""
    lines = [f"## {profile.name}"]
    if profile.department or profile.title:
        lines.append(f"部门/职位: {profile.department} / {profile.title}")
    if profile.aliases:
        lines.append(f"别名: {', '.join(profile.aliases)}")
    if profile.personality:
        lines.append(f"个性特征: {', '.join(profile.personality)}")
    if profile.interests:
        lines.append(f"兴趣爱好: {', '.join(profile.interests)}")
    if profile.relationships:
        for r in profile.relationships:
            lines.append(f"关系: {r.get('relation', '')} — {r.get('notes', '')}")
    lines.append(f"ID: {profile.id}")
    lines.append(f"最近活跃: {profile.last_seen}")
    if profile.body:
        lines.append(f"\n{profile.body}")
    return "\n".join(lines)
