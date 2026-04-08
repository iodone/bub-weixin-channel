"""Feishu-specific output format instructions appended to user messages."""

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
</output_format>

<tools>
You have access to the feishu.history tool for fetching chat history. Use it when users ask about previous messages, chat history, or what was discussed earlier.

Examples of when to use feishu.history:
- "What did we discuss yesterday?"
- "Show me messages from the last week"
- "What was the last thing John said?"
- "查一下最近1天的消息"
- "看看昨天的聊天记录"
- "最近都聊了什么"

Parameters:
- time_range: Time range for history query (e.g., '1d', '7d', '24h'). If not specified, returns recent messages.
- limit: Maximum number of messages to return (default 20, max 50).
</tools>"""
