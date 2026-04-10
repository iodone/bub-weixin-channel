---
name: feishu-card
description: |
  生成飞书 Interactive Card（schema 2.0）可视化卡片，支持 chart / table / column_set 等组件。
  当用户请求数据可视化、图表、趋势图、对比、排名、占比、报表、仪表盘、饼图、柱状图、
  折线图时必须使用。即使用户只说"画个图"、"帮我可视化"、"做个图表"也要触发。
  Use when: visualization, chart, trend, comparison, ranking, proportion, dashboard, report.
---

**HARD GATE：** 本 skill 只做一件事：生成飞书 schema 2.0 card JSON 并作为回复直接输出。
不执行数据查询，不修改文件，不调用外部 API。输出必须是**纯 JSON**，不含任何非 JSON 文本。

---

# Feishu Card — 可视化卡片生成器

## 逃生舱

- 用户已给出明确图表类型 + 完整数据 → 跳过 Phase 1，直接进入 Phase 2
- 用户说"简单画个图" → 使用最简配置，跳过样式精调

---

## Phase 1：数据理解与选图

**入口：** 用户提供了数据（JSON / 文字 / 表格 / CSV）或可从上下文中获取数据。
**如果数据不足 →** 回复文字询问，不要生成空卡片。状态：NEEDS_CONTEXT。

分析数据并决定图表类型：

| 用户意图 | 数据特征 | 图表 | VChart type |
|---------|---------|------|------------|
| 占比/构成 | ≤7 类 | 饼图 | `pie` |
| 占比/构成 | >7 类 | 矩阵树图 | `treemap` |
| 对比/排名 | 标签短 ≤12 类 | 柱状图 | `bar` 竖向 |
| 对比/排名 | 标签长 | 条形图 | `bar` 水平 |
| 趋势/变化 | 单指标 | 折线图 | `line` |
| 趋势/量感 | 面积强调 | 面积图 | `area` |
| 多维对比 | 3-10 维 | 雷达图 | `radar` |
| 转化漏斗 | 阶段递减 | 漏斗图 | `funnel` |
| 词频 | 文本+频次 | 词云 | `wordCloud` |

详细决策树 → `references/chart-decision-tree.md`

**出口：** 确定图表类型 + 结构化数据，进入 Phase 2。

---

## Phase 2：生成卡片

查阅参考文档（不要凭记忆）：
- 组件格式 → `references/components.md`
- 样式规范 → `references/vchart-style-guide.md`

### 卡片结构

```
{
  "schema": "2.0",
  "header": { "title": {"tag": "plain_text", "content": "标题"} },
  "body": {
    "elements": [
      // [可选] 指标卡 column_set
      // 主图表 chart
      {"tag": "hr"},
      // 文字总结 markdown
      {"tag": "hr"},
      // 页脚
      {"tag": "markdown", "content": "<font color='grey'>feishu-card</font>", "text_align": "center"}
    ]
  }
}
```

### 关键约束（违反会导致白屏或渲染错误）

| 约束 | 正确 | 错误 |
|------|------|------|
| schema | `"schema": "2.0"` (字符串) | `"schema": 2.0` (数字) |
| chart 外层 height | `"height": "280px"` (字符串) | `"height": 280` |
| chart_spec 内 height | `"height": 280` (数字) | `"height": "280px"` |
| chart_spec | JSON 对象 | 字符串 |
| color | `["#1664FF"]` (数组) | `"#1664FF"` |
| legends 拼写 | `"legends"` | `"legend"` |
| table rows 值 | `"120"` (字符串) | `120` (数字) |
| chart_spec.data | `[{"id":"d","values":[...]}]` | 其他结构 |
| JS 函数 | 禁止 | `formatMethod` 等会白屏 |
| background | `"transparent"` | 深色/黑色 |
| 多系列柱状图 | `xField:["主维度","系列"]` + `seriesField` + 长表 | `yField` 数组（不触发多色） |

GOOD: `{"tag":"chart","chart_spec":{"type":"bar","data":[{"id":"d","values":[...]}],"xField":"x","yField":"y"},"height":"280px"}`
BAD: `{"tag":"chart","spec":"{\"type\":\"bar\"...}","height":280}` — chart_spec 写成字符串、字段名错、height 类型错

GOOD: 坐标轴 label 不做格式化，直接省略 `formatMethod`
BAD: `"formatMethod": "(v) => (v/1000).toFixed(0) + 'K'"` — **任何 JS 函数字符串都会导致图表白屏，绝对禁止**

### 输出方式

**整个回复内容必须是纯 card JSON。** Channel 层自动检测 `schema: "2.0"` 并透传为飞书 interactive 消息。

GOOD: 直接输出 `{"schema":"2.0","body":{"elements":[...]}}`
BAD: 在 JSON 前后加文字说明
BAD: 用 ```json 代码块包裹
BAD: 加 `{"msg_type":"interactive",...}` 外层包裹

文字总结放在 card body 的 `{"tag":"markdown","content":"..."}` element 中。

---

## 自我调节

- 生成的 JSON 超过 30KB → 简化数据（采样/聚合），不要硬塞
- 数据量 >100 条 → 聚合后再生成图表
- 如果不确定图表类型是否适合 → 默认用柱状图，不要猜冷门图表

---

## 完成状态

- **DONE** — card JSON 已作为回复输出
- **DONE_WITH_CONCERNS** — 已输出但数据被截断或聚合，在 markdown 总结中说明
- **BLOCKED** — 无法生成（数据格式无法解析、依赖缺失）
- **NEEDS_CONTEXT** — 数据不足，已回复文字询问用户
