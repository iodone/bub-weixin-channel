# VChart 样式规范

## 配色

**主色板（多系列）：**
```json
["#749DFA", "#5EEBAE", "#BDC3CD", "#06C3B7", "#FFE566", "#FFAB66", "#889ABD"]
```

**饼图（6色）：**
```json
["#FFAB66", "#749DFA", "#5EEBAE", "#889ABD", "#6ED6F9", "#FFA3C9"]
```

**单色/面积图：** `["#327BE6"]`

**语义色：** 轴标签 `#9199A6`，图例文字 `#5A6575`，轴线 `#EDEDED`

---

## 背景

始终 `"background": "transparent"`

---

## 坐标轴

**Y 轴：**
```json
{
  "orient": "left",
  "tick": {"visible": false},
  "domainLine": {"visible": false},
  "grid": {"visible": false},
  "label": {"style": {"fontSize": 10, "fill": "#9199A6"}}
}
```

**X 轴：**
```json
{
  "orient": "bottom",
  "type": "band",
  "trimPadding": true,
  "tick": {"visible": false},
  "domainLine": {"visible": true, "style": {"lineWidth": 0.5, "stroke": "#EDEDED"}},
  "label": {"flush": true, "minGap": 4, "style": {"fontSize": 10, "fill": "#9199A6"}}
}
```

---

## 图例

```json
{
  "visible": true,
  "orient": "bottom",
  "position": "middle",
  "padding": [12, 0],
  "select": false,
  "hover": false,
  "item": {
    "label": {"style": {"fill": "#5A6575", "fontSize": 12}},
    "shape": {"style": {"symbolType": "circle", "size": 6}}
  }
}
```

---

## 高密度类目轴（>15 类）

类目 >15 时注入 dataZoom：

```json
{
  "dataZoom": [{"orient": "bottom", "start": 0, "end": 0.4, "filterMode": "axis", "height": 20}],
  "padding": {"top": 20, "right": 20, "bottom": 60, "left": 15},
  "height": 360
}
```

同时底部轴加 `"label": {"autoRotate": true, "style": {"fontSize": 9}}`。

类目 >30 时优先改用横向条形图或表格。
