"""Feishu-specific prompt instructions appended to user messages."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bub_im_bridge.profiles import UserProfile


def build_user_context_hint(profile: UserProfile | None) -> str:
    """Build a prompt hint with sender profile context and tool usage guidance."""
    tool_hints = (
        "当需要处理用户 profile 时，必须使用以下内置工具：\n"
        "- 创建新 profile：使用 user.create（如果用户已存在会自动更新）\n"
        "- 查询 profile：使用 user.lookup（按名字或 IM ID）或 user.search（按关键词搜索）\n"
        "- 更新已有 profile 的字段：使用 user.update\n"
        "- 当消息中提及其他用户（如 @某某）时，使用 user.lookup 查询该用户的 profile\n"
        "- 当观察到用户的行为特征、兴趣爱好等信息时，使用 user.update 记录到对应 profile\n\n"
        "严禁事项：\n"
        "- 严禁使用 bash、python 或直接编辑文件的方式操作 profiles 目录下的文件\n"
        "- 严禁手工构造 ProfileStore 或调用其内部方法\n"
        "- 严禁向终端用户输出 ProfileStore、upsert、工具封装等内部实现细节；"
        "如果操作失败，只返回简短的面向用户的错误信息"
    )

    if profile is None:
        return f"\n\n<user_context>\n{tool_hints}\n</user_context>"

    parts = [f"\n\n<user_context>\n发送者: {profile.name}"]
    if profile.department or profile.title:
        parts.append(f"部门/职位: {profile.department} / {profile.title}")
    if profile.personality:
        parts.append(f"个性特征: {', '.join(profile.personality)}")
    if profile.interests:
        parts.append(f"兴趣爱好: {', '.join(profile.interests)}")
    parts.append("")
    parts.append(tool_hints)
    parts.append("</user_context>")
    return "\n".join(parts)

FEISHU_OUTPUT_INSTRUCTION = """\

<output_format>
Your response will be rendered in Feishu. Use standard Markdown with these rules:

1. Headings: start from #### (max level), then #####, ###### for sub-levels. Do NOT use #, ##, or ###.
2. Tables: standard markdown | col1 | col2 | syntax
3. Text: **bold**, *italic*, ~~strikethrough~~, [link](url)
4. Lists: - unordered, 1. ordered (nesting with 4 spaces)
5. Code: ```language ... ``` or `inline`
6. Quote: > text
7. Divider: --- on its own line
8. Color: <font color='green'>text</font> (red, green, grey, blue)

For simple conversational replies, respond naturally without formatting — like a normal person chatting.
Only use rich formatting (headings, tables, lists) when the content benefits from structure.

When the user asks for data visualization (charts, trends, comparisons, rankings, proportions, \
dashboards, reports), load the `feishu-card` skill and follow its instructions to generate a \
Feishu Interactive Card (schema 2.0) with chart/table components. Output the card JSON directly \
as your entire reply — the channel will automatically detect and send it as an interactive card.
</output_format>"""

FEISHU_HISTORY_HINT_P2P = """\

<important>
Your conversation history (tape) only contains messages processed by this bot session. \
It does NOT include the full Feishu chat history (e.g. messages before the bot started, \
or messages outside this session). \
When the user asks about chat history, previous messages, or past conversations, \
you MUST use the feishu_history tool to fetch the actual messages from Feishu. \
Do NOT rely solely on your conversation tape or guess chat history.
</important>"""

FEISHU_HISTORY_HINT_GROUP = """\

<important>
You are in a GROUP chat. You can ONLY see messages where you are @mentioned. \
You CANNOT see other messages in this group. \
When the user asks about chat history, previous messages, or what others said, \
you MUST use the feishu_history tool to fetch the actual messages. \
Do NOT guess or make up chat history.
</important>"""
