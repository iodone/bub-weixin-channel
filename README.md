# Bub IM Bridge

> 还在为 openclaw 繁琐配置苦恼吗？使用 `bub-im-bridge` **3 分钟**打通微信 / 飞书 / Telegram。

为 [Bub](https://github.com/bubbuild/bub) 框架提供多渠道 IM 支持，一套代码，三端互通。

## 3 分钟快速接入

### 第一步：安装

```bash
uv pip install "git+https://github.com/iodone/bub-im-bridge.git"
```

### 第二步：配置

创建 `.env` 文件，填入你的配置（至少需要 `BUB_MODEL` 和 `BUB_API_KEY`）：

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

## Docker 部署

容器内通过 [boxsh](https://github.com/xicilion/boxsh) 沙箱运行，Agent 对工作空间的写入通过 COW（写时复制）隔离到独立目录，原始工作空间不受影响。

### 快速开始

```bash
# 1. 准备配置
cp .env.example .env
# 编辑 .env，填入 BUB_WORKSPACE 等配置

# 2. 创建必要目录
mkdir -p ~/.bub ~/.agents/skills ~/work/boxsh/bub-im-bridge

# 3. 微信渠道需要先登录
uv run -m bub_im_bridge login

# 4. 启动容器
docker-compose up -d

# 5. 查看日志
docker-compose logs -f
```

### 沙箱保护

| 目录 | 权限 | 说明 |
|------|------|------|
| `/workspace` | 🐄 COW | Agent 工作空间（只读基座，写入落到 /boxsh） |
| `/boxsh` | ✏️ 可写 | COW 写层，持久化 agent 对 workspace 的修改 |
| `/root/.agents/skills` | 🔒 只读 | Bub 技能目录 |
| `/root/.openclaw/openclaw-weixin` | 🔒 只读 | 微信登录凭据 |
| `/root/.bub` | ✏️ 可写 | Bub 运行数据（tapes、配置） |

### 调试

```bash
# 进入容器调试（已在沙箱内）
docker-compose exec bub sh

# 验证 COW 写入（成功，但原始 workspace 不变）
echo test > /workspace/test.txt  # COW 写入到 /boxsh
touch /root/.bub/test.txt  # 直接可写
```

📖 **详细文档**：[docs/DOCKER_USAGE.md](docs/DOCKER_USAGE.md)

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
| `BUB_FEISHU_VERIFICATION_TOKEN` | Webhook 验证 Token（可选） | ❌ |
| `BUB_FEISHU_ENCRYPT_KEY` | Webhook 事件加密密钥（可选） | ❌ |
| `BUB_FEISHU_ALLOW_USERS` | 允许的用户 open_id，逗号分隔 | ❌ |
| `BUB_FEISHU_ALLOW_CHATS` | 允许的 Chat ID，逗号分隔 | ❌ |
| `BUB_FEISHU_BOT_OPEN_ID` | 机器人 open_id，用于群聊 @检测 | ❌ |

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

> 完整配置参考 [`.env.example`](https://github.com/iodone/bub-im-bridge/blob/main/.env.example)

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
