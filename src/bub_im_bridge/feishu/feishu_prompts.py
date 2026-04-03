"""Feishu-specific output format instructions appended to user messages."""

FEISHU_OUTPUT_INSTRUCTION = """\

<output_format>
Your response will be rendered in a Feishu card. The card's markdown element supports LIMITED syntax only.

SUPPORTED:
- **bold**, *italic*, ~~strikethrough~~
- [link text](url)
- Newlines (use \\n\\n for paragraphs)

NOT SUPPORTED (will show as plain text):
- # Headings (use **bold** instead)
- --- Horizontal rules
- - Lists (use • or numbered text instead)
- ``` Code blocks (use inline text instead)
- Tables (describe data in text or use bullet points)

Keep responses simple and use only bold, italic, links, and paragraphs.
</output_format>"""
