# 图表选择决策树

```
用户想看什么？
│
├─ 趋势/变化
│  ├─ 单指标 → line（折线图）
│  └─ 需要量感 → area（面积图）
│
├─ 对比/排名
│  ├─ ≤12 类，标签短 → bar 竖向（柱状图）
│  ├─ 标签长 → bar 水平（条形图）
│  └─ 多维度 3-10 维 → radar（雷达图）
│
├─ 占比/构成
│  ├─ ≤7 类 → pie（饼图）
│  └─ >7 类 → treemap（矩阵树图）
│
├─ 转化/流程
│  └─ 阶段递减 → funnel（漏斗图）
│
├─ 分布/相关
│  ├─ 两维数值 → scatter（散点图）
│  └─ 词频 → wordCloud（词云）
│
└─ 无法判断 → bar 竖向（默认）
```

## 类目数量与图表适配

| 类目数 | 策略 |
|-------|------|
| ≤12 | 正常渲染 |
| 13-15 | X 轴标签可旋转 |
| 16-30 | 注入 dataZoom（见 vchart-style-guide.md） |
| >30 | 改用横向条形图或 table |

## 多系列数据：宽表 → 长表

多系列柱状图/折线图必须用长表格式：

```
宽表: [{region: "A", "Q1": 100, "Q2": 200}]
  ↓
长表: [{region: "A", quarter: "Q1", value: 100},
       {region: "A", quarter: "Q2", value: 200}]
```

对应 spec: `xField: ["region","quarter"]`, `yField: "value"`, `seriesField: "quarter"`
