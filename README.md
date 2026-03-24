# Bub WeChat Channel Plugin

为 [Bub](https://github.com/bubbuild/bub) 框架提供微信支持，基于 [weixin-agent-sdk](https://github.com/frostming/weixin-agent-sdk) 实现。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置环境
cp .env.example .env
# 编辑 .env，填入 BUB_API_KEY

# 3. 微信登录（扫码）
uv run -m bub_weixin_channel login

# 4. 启动 Gateway
uv run bub gateway --enable-channel weixin
```

## 工作流程

```
微信用户 → weixin-agent-sdk → WeixinChannel → Bub Framework → Agent → 响应回复
```

## 配置

`.env.example` 包含所有配置项说明。必需配置：

| 配置项 | 说明 |
|--------|------|
| `BUB_MODEL` | LLM 模型，格式 `provider:model_id` |
| `BUB_API_KEY` | API 密钥 |
| `BUB_API_BASE` | API 端点（可选） |

其他可选配置参考 `.env.example` 文件。

## 项目结构

```
src/bub_weixin_channel/
├── __init__.py         # 模块标识
├── __main__.py         # CLI 入口（login 命令）
├── plugin.py           # 插件入口
├── channel.py          # 通道实现
└── agent_adapter.py    # 协议适配
```

## 注意事项

- 登录凭据：`~/.openclaw/openclaw-weixin/`
- 支持消息类型：文本、图片、视频、文件、语音
- 语音格式：`audio/silk`（无转录）
