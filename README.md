# Bub IM Bridge

> 还在为 openclaw 繁琐配置苦恼吗？使用 `bub-im-bridge` **3 分钟**打通微信 / 飞书 / Telegram。

为 [Bub](https://github.com/bubbuild/bub) 框架提供多渠道 IM 支持，一套代码，三端互通。

## 3 分钟快速接入

### 第一步：安装

```bash
git clone https://github.com/iodone/bub-weixin-channel.git
cd bub-weixin-channel
uv sync
```

### 第二步：配置

```bash
cp .env.example .env
```

编辑 `.env`，填入你的配置（至少需要 `BUB_MODEL` 和 `BUB_API_KEY`）：

```env
BUB_MODEL=anthropic:claude-sonnet-4-20250514
BUB_API_KEY=sk-ant-xxxxx
```

### 第三步：选择渠道启动

<details>
<summary><b>飞书</b>（推荐，无需公网 IP）</summary>

1. 在[飞书开放平台](https://open.feishu.cn/app)创建企业自建应用
2. 获取 App ID 和 App Secret，填入 `.env`：

```env
BUB_FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
BUB_FEISHU_APP_SECRET=your-app-secret
```

3. 应用后台 → 事件与回调 → 接收方式：**使用长连接接收事件**
4. 订阅事件：`im.message.receive_v1`（接收消息）

```bash
uv run bub gateway --enable-channel feishu
```

</details>

<details>
<summary><b>Telegram</b>（需要代理）</summary>

1. 通过 [@BotFather](https://t.me/BotFather) 创建 Bot，获取 Token
2. 填入 `.env`：

```env
BUB_TELEGRAM_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
BUB_TELEGRAM_ALLOW_USERS=your-telegram-user-id
# 国内网络需要配置代理
BUB_TELEGRAM_PROXY=http://127.0.0.1:1087
```

```bash
uv run bub gateway --enable-channel telegram
```

</details>

<details>
<summary><b>微信</b>（扫码登录）</summary>

```bash
# 扫码登录
uv run -m bub_im_bridge login

# 启动
uv run bub gateway --enable-channel weixin
```

</details>

<details>
<summary><b>多渠道同时启动</b></summary>

```bash
# 同时启动飞书和 Telegram
uv run bub gateway --enable-channel feishu --enable-channel telegram

# 或启动所有已配置的渠道
uv run bub gateway
```

</details>

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
| `BUB_FEISHU_ENCRYPT_KEY` | 事件加密密钥 | ❌ |
| `BUB_FEISHU_VERIFICATION_TOKEN` | 验证 Token | ❌ |
| `BUB_FEISHU_ALLOW_USERS` | 允许的用户 open_id，逗号分隔 | ❌ |

### Telegram

| 配置项 | 说明 | 必需 |
|--------|------|:----:|
| `BUB_TELEGRAM_TOKEN` | Bot Token（@BotFather 获取） | ✅ |
| `BUB_TELEGRAM_ALLOW_USERS` | 允许的用户 ID，逗号分隔 | ❌ |
| `BUB_TELEGRAM_ALLOW_CHATS` | 允许的 Chat ID，逗号分隔 | ❌ |
| `BUB_TELEGRAM_PROXY` | HTTP 代理地址 | ❌ |

> 完整配置参考 [`.env.example`](.env.example)

## 消息类型

| 类型 | 微信 | 飞书 | Telegram |
|------|:----:|:----:|:--------:|
| 文本 | ✅ | ✅ | ✅ |
| 图片 | ✅ | ✅ | ✅ |
| 文件 | ✅ | ✅ | ✅ |
| 语音 | ✅ | ✅ | ✅ |
| 视频 | ✅ | ✅ | ✅ |

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

## 常见问题

**飞书收不到消息？**
- 检查是否启用了「长连接接收事件」
- 确认订阅了 `im.message.receive_v1` 事件
- 群聊需要 @机器人 才会触发

**Telegram 连接超时？**
- 国内网络需要配置 `BUB_TELEGRAM_PROXY`

**微信登录失败？**
- 登录凭据存储在 `~/.openclaw/openclaw-weixin/`
- 重新执行 `uv run -m bub_im_bridge login`

## License

MIT
