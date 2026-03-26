# Bub WeChat & Feishu Channel Plugin

为 [Bub](https://github.com/bubbuild/bub) 框架提供微信和飞书支持。

## 快速开始

### 微信

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

### 飞书

```bash
# 1. 在飞书开放平台创建企业自建应用
#    https://open.feishu.cn/app

# 2. 配置 .env
BUB_FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
BUB_FEISHU_APP_SECRET=your-app-secret

# 3. 启用事件订阅（长连接模式，无需公网 IP）
#    应用后台 → 事件与回调 → 接收方式：使用长连接接收事件
#    订阅事件：im.message.receive_v1（接收消息）

# 4. 启动 Gateway
uv run bub gateway --enable-channel feishu
```

## 工作流程

```
微信用户 → weixin-agent-sdk → WeixinChannel ─┐
                                              ├→ Bub Framework → Agent
飞书用户 → lark.ws.Client  → FeishuChannel  ─┘
```

## 配置

`.env.example` 包含所有配置项说明。必需配置：

| 配置项 | 说明 |
|--------|------|
| `BUB_MODEL` | LLM 模型，格式 `provider:model_id` |
| `BUB_API_KEY` | API 密钥 |
| `BUB_API_BASE` | API 端点（可选） |

### 飞书配置

| 配置项 | 说明 | 必需 |
|--------|------|------|
| `BUB_FEISHU_APP_ID` | 应用 App ID | ✅ |
| `BUB_FEISHU_APP_SECRET` | 应用 App Secret | ✅ |
| `BUB_FEISHU_ENCRYPT_KEY` | 事件加密密钥 | ❌ |
| `BUB_FEISHU_VERIFICATION_TOKEN` | 验证 Token | ❌ |
| `BUB_FEISHU_ALLOW_USERS` | 允许的用户 open_id，逗号分隔 | ❌ |

其他可选配置参考 `.env.example` 文件。

## 项目结构

```
src/bub_weixin_channel/
├── __init__.py         # 模块标识
├── __main__.py         # CLI 入口（login 命令）
├── plugin.py           # 微信插件入口
├── channel.py          # 微信通道实现
├── agent_adapter.py    # 协议适配
└── feishu/
    ├── __init__.py     # 模块标识
    ├── channel.py      # 飞书通道实现（WebSocket 长连接）
    └── plugin.py       # 飞书插件入口
```

## 消息类型支持

| 类型 | 微信 | 飞书 |
|------|:----:|:----:|
| 文本 | ✅ | ✅ |
| 图片 | ✅ | ✅ |
| 文件 | ✅ | ✅ |
| 语音 | ✅ | ✅ |
| 视频 | ✅ | ✅ |

## 注意事项

- 微信登录凭据：`~/.openclaw/openclaw-weixin/`
- 飞书使用 WebSocket 长连接模式，无需公网 IP
- 飞书群聊需 @机器人 才会触发响应
- 语音格式：`audio/silk`（无转录）
