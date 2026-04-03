"""Feishu-specific output format instructions appended to user messages."""

FEISHU_OUTPUT_INSTRUCTION = """\

<output_format>
Your response will be rendered in a Feishu card (Card JSON 2.0) which supports standard Markdown.

Supported syntax:
- # Heading 1 through ###### Heading 6
- **bold**, *italic*, ~~strikethrough~~
- [link text](url)
- Standard markdown tables: | col1 | col2 |
- Ordered lists (1. item) and unordered lists (- item), with nesting (4 spaces indent)
- Code blocks: ```language ... ```
- Inline code: `code`
- Blockquote: > text
- Divider: --- (on its own line)
- Colored text: <font color='green'>text</font> (red, green, grey, blue, etc.)

Use standard Markdown freely. Keep responses well-structured with headings and tables where appropriate.
</output_format>"""
