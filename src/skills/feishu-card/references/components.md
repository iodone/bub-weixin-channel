# 飞书卡片组件参考

## chart — 图表

```json
{
  "tag": "chart",
  "chart_spec": {
    "type": "bar",
    "data": [{"id": "d", "values": [{"x": "A", "y": 20}, {"x": "B", "y": 30}]}],
    "xField": "x",
    "yField": "y",
    "color": ["#749DFA", "#5EEBAE", "#FFAB66"],
    "background": "transparent",
    "legends": {"visible": true, "orient": "bottom"},
    "tooltip": {"visible": true}
  },
  "height": "280px"
}
```

- `chart_spec` 必须是 JSON 对象，不能是字符串
- 外层 `height` 是字符串（如 `"280px"`），`chart_spec` 内的 `height` 是数字
- `color` 必须是数组
- 禁止 `formatMethod` 等 JS 函数字符串

**多系列柱状图：** 必须用 `xField: ["主维度", "系列维度"]` + `seriesField` + 长表数据，不要用 `yField` 数组。

---

## table — 表格

```json
{
  "tag": "table",
  "columns": [
    {"name": "key", "display_name": "显示名", "width": "auto", "data_type": "text"}
  ],
  "rows": [{"key": "值"}],
  "header_style": {"bold": true, "background_style": "grey", "text_align": "center"},
  "page_size": 10
}
```

- rows 中所有值必须是字符串，数字也要转 `"120"`

---

## column_set — 指标卡

```json
{
  "tag": "column_set",
  "flex_mode": "bisect",
  "columns": [
    {
      "tag": "column", "width": "weighted", "weight": 1,
      "vertical_align": "top", "background_style": "blue-50", "padding": "8px",
      "elements": [
        {"tag": "div", "text": {"tag": "lark_md", "content": "指标\n**<font color='blue'>1,200</font>**"}}
      ]
    }
  ]
}
```

- `background_style` 用浅色：`blue-50` / `green-50` / `grey-50` / `violet-50` / `orange-50`

---

## collapsible_panel — 折叠面板

```json
{
  "tag": "collapsible_panel",
  "expanded": true,
  "header": {"title": {"tag": "plain_text", "content": "标题"}},
  "elements": []
}
```

- 内部不能放 table，改用 column_set

---

## markdown — 富文本

```json
{"tag": "markdown", "content": "**加粗** <font color='blue'>蓝色</font>"}
```

颜色：`blue` / `green` / `red` / `orange` / `grey` / `violet`

---

## hr — 分割线

```json
{"tag": "hr"}
```
