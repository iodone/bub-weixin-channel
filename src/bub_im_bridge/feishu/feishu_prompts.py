"""Feishu-specific output format instructions appended to user messages."""

FEISHU_OUTPUT_INSTRUCTION = """\

<output_format>
Your response will be rendered in Feishu using lark_md format. Follow these rules strictly:

SUPPORTED:
- **bold**, *italic*, ~~strikethrough~~
- [link text](url)
- <font color='blue' size='4'>Large title text</font>
- <font color='grey' size='3'>Subtitle text</font>
- <font color='red'>Red text</font>, <font color='green'>Green text</font>
- Line breaks: use \\n\\n for paragraphs

NOT SUPPORTED (will show as plain text):
- # Headings → use <font color='blue' size='4'>Title</font> instead
- --- Horizontal rules
- - Lists → use • or numbered text instead
- ``` Code blocks → use plain text instead
- | Tables | → describe data in bullet points or use text layout

For titles: <font color='blue' size='4'>Main Title</font>
For subtitles: <font color='grey' size='3'>Subtitle</font>
For emphasis: **bold text**

Keep responses simple. Use font tags for structure, bold for emphasis, and plain text for data.
</output_format>"""
