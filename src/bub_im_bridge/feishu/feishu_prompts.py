"""Feishu-specific prompt instructions appended to user messages."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bub_im_bridge.profiles import UserProfile


def build_user_context_hint(profile: UserProfile | None) -> str:
    """Build a prompt hint with sender profile context and tool usage guidance."""
    tool_hints = (
        "用户相关信息有多个来源，按用途区分：\n"
        "- profile（user.lookup / user.search / user.create / user.update）用于长期记忆和结构化记录\n"
        "- Feishu 消息上下文（sender、mentions）、Feishu API 信息用于当前会话感知\n"
        "- workspace 中的 USER.md 或其他上下文文件用于理解用户或项目背景\n\n"
        "规则：\n"
        "- 当需要读取、创建、更新 profile 时，必须使用内置 user.* 工具\n"
        "- 当消息中提及其他用户（如 @某某）时，使用 user.lookup 查询\n"
        "- 当观察到用户的行为特征、兴趣爱好等信息时，使用 user.update 记录\n"
        "- profile 不存在或不完整时，不要卡住；继续结合 Feishu 信息、当前消息、"
        "USER.md 等其他来源完成任务\n"
        "- 不得用 bash、python 或直接文件编辑操作 profiles 目录\n"
        "- 不要把内部实现细节输出给终端用户"
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
