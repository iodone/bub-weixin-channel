"""Feishu-specific output format instructions appended to user messages."""

FEISHU_OUTPUT_INSTRUCTION = """\

<output_format>
Your response will be rendered in Feishu. Use standard Markdown with these rules:

1. Headings: start from ### (max level), then ####, #####, ###### for sub-levels. Do NOT use # or ##.
2. Tables: standard markdown | col1 | col2 | syntax
3. Text: **bold**, *italic*, ~~strikethrough~~, [link](url)
4. Lists: - unordered, 1. ordered (nesting with 4 spaces)
5. Code: ```language ... ``` or `inline`
6. Quote: > text
7. Divider: --- on its own line
8. Color: <font color='green'>text</font> (red, green, grey, blue)

For simple conversational replies, respond naturally without formatting — like a normal person chatting.
Only use rich formatting (headings, tables, lists) when the content benefits from structure.
</output_format>"""
