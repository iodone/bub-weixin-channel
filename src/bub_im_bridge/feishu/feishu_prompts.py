"""Feishu-specific output format instructions appended to user messages."""

FEISHU_OUTPUT_INSTRUCTION = """\

<output_format_for_feishu_markdown_guide>
You are replying on the Feishu (Lark) platform. Your output will be rendered via the Feishu card markdown component.
You MUST strictly follow the syntax below. Do NOT use any unsupported markdown syntax.

## Basic Syntax

### Text Styles
**bold text**
*italic text*
~~strikethrough text~~
***~~mixed styles~~***

### Links
[link text](https://example.com)

### Images
![hover text](https://image.url)

### Headings
# First-level heading
## Second-level heading
IMPORTANT: Only # and ## are supported. Do NOT use ### or deeper headings.

### Horizontal Rule
Place a blank line before ---

text above

---

text below

### Unordered List
- item1
- item2
IMPORTANT: Indentation/nesting is NOT supported. Only text and links are supported as item content.

### Ordered List
1. item1
2. item2
IMPORTANT: Indentation/nesting is NOT supported. Only text and links are supported as item content.

### Code Block
```json
{"key": "value"}
```
Specify language after opening ```, e.g. ```python, ```go, ```sql

## Advanced Components

### Colored Text
<font color="red">red text</font>
<font color="green">green text</font>
<font color="grey">grey text</font>
Only red, green, and grey are supported.

### Table
CRITICAL: Do NOT use standard markdown table syntax (| col1 | col2 |). It will NOT render.
You MUST use the Feishu <table> component:

<table columns={[{"tag":"plain_text","text":"Column1"},{"tag":"plain_text","text":"Column2"}]} data={[{"Column1":"value1","Column2":"value2"},{"Column1":"value3","Column2":"value4"}]} />

Rules:
- columns: array of column definitions, each with {"tag":"plain_text","text":"column name"}
- data: array of row objects, keys must match column text exactly
- Maximum 10 columns per table
- Maximum 5 tables per card

### Chart
<chart chartSpec={VEGA_LITE_SPEC_JSON} />
chartSpec follows the Vega-Lite specification.

### Column Layout
<row>
  <col flex=1> content1 </col>
  <col flex=2> content2 </col>
</row>
Use flex attribute to control width ratio.

### Record Detail
<record fields={[{"tag":"plain_text","text":"Field1"},{"tag":"plain_text","text":"Field2"}]} data={{"Field1":"value1","Field2":"value2"}} />

### Note (auxiliary text)
<note> auxiliary description text </note>

### Highlight Block
<highlight>
highlighted content line 1
highlighted content line 2
</highlight>
IMPORTANT: Multi-line content must NOT be on the same line as <highlight> or </highlight> tags. Only grey color is supported.

### Button
<button type="primary" width="default" action="navigate" url="https://example.com">
  Click to visit
</button>
type: primary | default
action: navigate (open URL) | message (send message)

### Card Title
<title style="blue">Title content</title>
Supported styles: blue, wathet, turquoise, green, yellow, orange, red, carmine, violet, purple, indigo, grey

### Mention User
<at id='all'></at>
<at id='{user_open_id}'></at>
<at email='{user_email}'></at>

## Prohibited Syntax

Do NOT use any of the following — they will NOT render correctly:

1. Standard markdown tables:
   | col1 | col2 |
   |------|------|
   | a    | b    |
   Use <table> component instead.

2. Headings level 3 and deeper:
   ### This will NOT work
   #### This will NOT work
   Only use # and ##.

3. Nested/indented lists:
   - item
     - sub-item    <-- NOT supported
   Keep lists flat.

## Complete Example

# Sales Report

## Overview

<table columns={[{"tag":"plain_text","text":"Metric"},{"tag":"plain_text","text":"Value"}]} data={[{"Metric":"Total Revenue","Value":"$1.2M"},{"Metric":"Active Users","Value":"4,740"},{"Metric":"Growth Rate","Value":"12.5%"}]} />

## Highlights

<font color="green">Revenue increased by 12.5% compared to last month.</font>

Key achievements:
1. Expanded to 3 new regions
2. Launched premium tier

<highlight>
Action items:
- Review Q2 targets
- Schedule team sync
</highlight>

<note> Data as of 2026-04-02. Source: internal analytics. </note>

</output_format_for_feishu_markdown_guide>"""
