# Bub IM Bridge

为 [Bub](https://github.com/bubbuild/bub) 框架提供多渠道 IM 支持的 channel plugin。

## 安装

```bash
uv pip install "git+https://github.com/iodone/bub-im-bridge.git"
```

## 渠道配置

### 飞书

在[飞书开放平台](https://open.feishu.cn/app)创建企业自建应用，获取 App ID 和 App Secret。

```env
BUB_FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
BUB_FEISHU_APP_SECRET=your-app-secret
```

应用后台 → 事件与回调 → 接收方式：**使用长连接接收事件**，订阅 `im.message.receive_v1` 事件。

### Telegram

通过 [@BotFather](https://t.me/BotFather) 创建 Bot，获取 Token。

```env
BUB_TELEGRAM_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
BUB_TELEGRAM_ALLOW_USERS=your-telegram-user-id
BUB_TELEGRAM_PROXY=http://127.0.0.1:1087  # 国内网络需要
```

### 微信

微信渠道需要先扫码登录：`uv run -m bub_im_bridge login`

## 配置参考

### 通用配置

| 配置项 | 说明 | 必需 |
|--------|------|:----:|
| `BUB_MODEL` | LLM 模型，格式 `provider:model_id` | ✅ |
| `BUB_API_KEY` | API 密钥 | ✅ |
| `BUB_API_BASE` | API 端点（自定义模型时使用） | ❌ |

### 飞书

| 配置项 | 说明 | 必需 |
|--------|------|:----:|
| `BUB_FEISHU_APP_ID` | 应用 App ID | ✅ |
| `BUB_FEISHU_APP_SECRET` | 应用 App Secret | ✅ |
| `BUB_FEISHU_VERIFICATION_TOKEN` | Webhook 验证 Token | ❌ |
| `BUB_FEISHU_ENCRYPT_KEY` | Webhook 事件加密密钥 | ❌ |
| `BUB_FEISHU_ALLOW_USERS` | 允许的用户 open_id，逗号分隔 | ❌ |
| `BUB_FEISHU_ALLOW_CHATS` | 允许的 Chat ID，逗号分隔 | ❌ |
| `BUB_FEISHU_BOT_OPEN_ID` | 机器人 open_id，用于群聊 @检测 | ❌ |
| `BUB_FEISHU_BOT_NAME` | 机器人显示名称，用于 @名称 匹配（大小写不敏感） | ❌ |
| `BUB_FEISHU_QUEUE_MAX_LENGTH` | 消息队列最大长度，0=不限制 | 0 |
| `BUB_FEISHU_ADMIN_USERS` | 管理员 open_id，逗号分隔；管理员消息绕过排队，可发送 `,cancel` 取消任务 | ❌ |

> **获取机器人 open_id 的方式**：
>
> 方式一：启动服务后在群聊中 @机器人，查看日志输出的 `mentions.id.open_id`
>
> 方式二：通过 API 获取：
> ```bash
> curl -X GET "https://open.feishu.cn/open-apis/bot/v3/info/" \
>   -H "Authorization: Bearer <tenant_access_token>"
> ```

### Telegram

| 配置项 | 说明 | 必需 |
|--------|------|:----:|
| `BUB_TELEGRAM_TOKEN` | Bot Token（@BotFather 获取） | ✅ |
| `BUB_TELEGRAM_ALLOW_USERS` | 允许的用户 ID，逗号分隔 | ❌ |
| `BUB_TELEGRAM_ALLOW_CHATS` | 允许的 Chat ID，逗号分隔 | ❌ |
| `BUB_TELEGRAM_PROXY` | HTTP 代理地址 | ❌ |

### 微信

| 配置项 | 说明 | 必需 |
|--------|------|:----:|
| `WEIXIN_BASE_URL` | 微信 API 基础地址 | ❌ |
| `WEIXIN_ACCOUNT_ID` | 微信账号 ID | ❌ |

## 消息类型

| 类型 | 微信 | 飞书 | Telegram |
|------|:----:|:----:|:--------:|
| 文本 | ✅ | ✅ | ✅ |
| 图片 | ✅ | ✅ | ✅ |
| 文件 | ✅ | ✅ | ✅ |
| 语音 | ✅ | ✅ | ✅ |
| 视频 | ✅ | ✅ | ✅ |

## 架构

```
┌─────────────┐
│   微信用户   │──→ weixin-agent-sdk ──→ WeixinChannel  ──┐
├─────────────┤                                            │
│   飞书用户   │──→ lark.ws.Client   ──→ FeishuChannel   ──┼──→ Bub Framework ──→ Agent
├─────────────┤                                            │
│ Telegram用户 │──→ python-telegram-bot──→ TelegramChannel──┘
└─────────────┘
```

## 项目结构

```
src/bub_im_bridge/
├── __init__.py          # 共享模块（自动加载 .env）
├── __main__.py          # CLI 入口
├── weixin/
│   ├── channel.py       # WeixinChannel
│   ├── plugin.py        # WeixinPlugin
│   └── agent_adapter.py
└── feishu/
    ├── channel.py        # FeishuChannel（WebSocket 长连接）
    └── plugin.py         # FeishPlugin
```

> Telegram 通道由 Bub 框架内置提供。

## 开发

```bash
# 安装开发依赖
uv pip install -e ".[dev]"

# 运行测试
uv run pytest
```

## 常见问题

**飞书收不到消息？**
- 检查是否启用了「长连接接收事件」
- 确认订阅了 `im.message.receive_v1` 事件
- 群聊需要 @机器人 才会触发

**飞书群聊 @机器人 不响应？**
- 需要配置 `BUB_FEISHU_BOT_OPEN_ID`（机器人 open_id）
- 获取方式：在群聊中 @机器人，查看日志中的 `mentions.id.open_id`
- 或使用 API：`GET /open-apis/bot/v3/info/`

**Telegram 连接超时？**
- 国内网络需要配置 `BUB_TELEGRAM_PROXY`

**微信登录失败？**
- 登录凭据存储在 `~/.openclaw/openclaw-weixin/`
- 重新执行 `uv run -m bub_im_bridge login`

## License

MIT
