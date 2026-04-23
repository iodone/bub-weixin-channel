# Docker 部署指南

## 快速开始

### 1. 准备配置

复制 `.env.example` 为 `.env` 并填入实际值：

```bash
cp .env.example .env
```

编辑 `.env` 文件，**必需**修改 `BUB_WORKSPACE` 为你的实际工作空间路径。

### 2. 创建必要目录

```bash
mkdir -p ~/.bub ~/.agents/skills ~/work/boxsh/bub-im-bridge
```

### 3. 微信渠道登录（可选）

如果使用微信渠道，需要先在本地登录：

```bash
uv run -m bub_im_bridge login
```

### 4. 启动容器

```bash
docker-compose up -d
```

### 5. 查看日志

```bash
docker-compose logs -f
```

## 目录挂载说明

| 容器内路径 | 环境变量 | 默认值 | 沙箱权限 | 说明 |
|-----------|---------|-------|---------|------|
| `/workspace` | `BUB_WORKSPACE` | (必需) | (基座) | COW 只读基座（不在沙箱内直接暴露） |
| `/boxsh` | `BUB_BOXSH` | `~/work/boxsh/bub-im-bridge` | 🐄 COW | Agent 工作空间（boxsh COW merged view），写入持久化到宿主机 |
| `/root/.agents/skills` | `BUB_SKILLS` | `~/.agents/skills` | 🔒 只读 | Bub 技能目录 |
| `/root/.openclaw/openclaw-weixin` | `BUB_WEIXIN_DATA` | `~/.openclaw/openclaw-weixin` | 🔒 只读 | 微信登录凭据 |
| `/root/.bub` | `BUB_HOME` | `~/.bub` | ✏️ 可写 | Bub 运行数据（tapes、配置） |

## 沙箱保护

容器内使用 [boxsh](https://github.com/xicilion/boxsh) 沙箱运行 bub 服务，提供进程级别的文件系统隔离：

- ✅ Agent 可以读写 `/boxsh`（COW merged view，基座来自 $BUB_WORKSPACE）
- ✅ Agent 可以在 `/root/.bub` 中写入 tapes 和配置
- ✅ Agent 对 `/boxsh` 的写操作通过 COW 持久化到宿主机 `$BUB_BOXSH`，原始 workspace 不受影响
- ❌ Agent **无法**修改 skills 和 weixin 配置（防止意外覆盖）

即使 AI agent 生成了 `rm -rf /boxsh` 这样的危险命令，也不会对宿主机的原始 workspace 造成影响。所有写入、删除、覆盖都沉淀到宿主机 `$BUB_BOXSH` 目录。

## 调试和运维

### 进入容器调试

entrypoint 通过 `exec boxsh --sandbox ...` 启动服务，boxsh 使用 `cow:/workspace:/boxsh` 建立 COW overlay 并创建独立的 mount namespace（沙箱视图）。`docker-compose exec` 新起的进程会进入该 namespace。

```bash
# 1. 进入沙箱视图的调试 shell（与 agent 运行时视角一致）
#    /boxsh 可读写（COW merged view），skills/weixin 只读
docker-compose exec bub /entrypoint.sh shell

# 2. 进入容器运行环境（同样在 boxsh 的 mount namespace 内）
#    适合看进程、环境变量、运行中挂载状态
docker-compose exec bub bash

# 3. 进入原始镜像环境（绕过 boxsh，启动新容器）
#    适合排查镜像内容、确认文件是否被正确打包
docker-compose run --rm --entrypoint sh bub
```

在沙箱内，你可以验证 COW 和只读保护：

```bash
# 测试 COW 写入（应该成功，但不修改原始 workspace）
echo "test" > /boxsh/test.txt
cat /boxsh/test.txt
# 输出：test（通过 COW 层读取）

# 在宿主机验证原始 workspace 未被修改
# ls $BUB_WORKSPACE/test.txt → 不存在
# ls $BUB_BOXSH/test.txt → 存在（COW 写层）

# 测试 skills 目录只读（应该失败）
touch /root/.agents/skills/test.txt  
# 输出：Read-only file system

# 测试可写目录（应该成功）
touch /root/.bub/test.txt
echo "success" > /root/.bub/test.txt
```

### 执行单个命令

```bash
# 在沙箱内查看文件（通过 entrypoint）
docker-compose exec bub /entrypoint.sh ls -la /boxsh

# 在沙箱内查看 bub 配置
docker-compose exec bub /entrypoint.sh cat /root/.bub/config.yaml
```

### 查看日志

```bash
# 查看实时日志
docker-compose logs -f bub

# 查看最近 100 行
docker-compose logs --tail 100 bub
```

### 重启容器

```bash
docker-compose restart bub
```

### 停止容器

```bash
docker-compose down
```

## 环境变量配置

在 `.env` 文件中配置：

### 必需配置

```bash
# Agent 工作空间路径（必需修改为实际路径）
BUB_WORKSPACE=/path/to/your/workspace

# LLM 模型配置
BUB_MODEL=anthropic:claude-sonnet-4-20250514
BUB_API_KEY=sk-ant-xxxxx
```

### 可选配置

```bash
# Bub 相关目录（使用默认值即可）
BUB_BOXSH=~/work/boxsh/bub-im-bridge
BUB_SKILLS=~/.agents/skills
BUB_WEIXIN_DATA=~/.openclaw/openclaw-weixin
BUB_HOME=~/.bub

# 渠道配置（根据需要启用）
# 飞书
BUB_FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
BUB_FEISHU_APP_SECRET=your-app-secret

# Telegram
BUB_TELEGRAM_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
BUB_TELEGRAM_PROXY=http://127.0.0.1:1087

# 其他配置...
```

完整配置参考项目根目录的 `.env.example` 文件。

## 验证沙箱是否生效

进入 boxsh 沙箱后，运行以下命令验证：

```bash
docker-compose exec bub /entrypoint.sh shell

# 在沙箱内执行：

# 1. 测试 COW 写入（成功，但原始 workspace 不变）
echo test > /boxsh/test.txt
cat /boxsh/test.txt
# 预期输出：test

# 2. 测试可写目录
touch /root/.bub/test.txt
echo "success" > /root/.bub/test.txt
cat /root/.bub/test.txt
# 预期输出：success

# 3. 查看当前用户（在沙箱内显示为 root，但实际上是普通用户）
whoami
# 预期输出：root

# 4. 查看挂载信息（会看到 boxsh 的挂载）
mount | grep -E "bind|overlay" | grep -v "lowerdir=/var/lib/docker"
```

## 架构说明

### 容器结构

```
宿主机
 ├── $BUB_WORKSPACE (原始工作区，不被修改)
 ├── $BUB_BOXSH (COW 写层，持久化 agent 写入)
 └── Docker 容器
      ├── /workspace ← $BUB_WORKSPACE (只读基座)
      ├── /boxsh     ← $BUB_BOXSH (COW upper layer)
      └── boxsh 沙箱 (cow:/workspace:/boxsh)
           ├── /boxsh = COW merged view (agent workspace)
           └── bub gateway 进程 (bub -w /boxsh)
```

### entrypoint.sh 用法

容器的入口点 `/entrypoint.sh` 支持多种使用方式：

```bash
# 1. 默认启动服务（无参数）
/entrypoint.sh
# → 在 boxsh 沙箱内启动 bub gateway

# 2. 进入交互式 shell（继承沙箱保护）
/entrypoint.sh shell
# → 在沙箱视图下启动交互式 shell

# 3. 执行单个命令（继承沙箱保护）
/entrypoint.sh <command>
# → 在沙箱视图下执行命令
```

## 常见问题

### Q: 为什么要使用 boxsh 沙箱？

A: boxsh 提供进程级别的文件系统隔离，防止 AI agent 执行的命令意外修改重要文件。即使 agent 生成了 `rm -rf /boxsh` 这样的危险命令，也不会对宿主机的原始 workspace 造成影响。

### Q: 沙箱会影响性能吗？

A: 几乎没有影响。boxsh 使用 OS 原生的 overlay 机制（Linux 上是 overlayfs，macOS 上是 APFS clonefile），读取操作是零开销的，直接访问原始文件。

### Q: 如何临时禁用沙箱？

A: 修改 `entrypoint.sh`，去掉 `--sandbox` 和所有 `--bind` 参数，或者直接用 `docker exec -it bub bash` 进入非沙箱环境进行调试。

### Q: 沙箱内的进程能访问网络吗？

A: 可以。当前配置没有使用 `--new-net-ns` 参数。如需隔离网络，在 `entrypoint.sh` 的 `BOXSH_ARGS` 中添加 `--new-net-ns`。

### Q: 容器启动失败怎么办？

A: 检查以下几点：
1. `.env` 文件中的 `BUB_WORKSPACE` 路径是否正确
2. 挂载的目录是否存在
3. 查看容器日志：`docker logs bub`

### Q: 如何更新镜像？

A: 拉取最新代码后重新构建：

```bash
git pull
docker-compose down
docker-compose build
docker-compose up -d
```

### Q: 数据会丢失吗？

A: 不会。所有重要数据都通过 volume 挂载，存储在宿主机上：
- `/root/.bub` → `$BUB_HOME`（tapes、配置）
- `/root/.openclaw/openclaw-weixin` → `$BUB_WEIXIN_DATA`（微信凭据）
- `/boxsh` → `$BUB_BOXSH`（agent 对 workspace 的 COW 写入）

容器删除重建后，这些数据仍然存在。

### Q: 如何查看 bub 的会话记录（tapes）？

A: tapes 存储在 `$BUB_HOME` 目录（默认 `~/.bub`）：

```bash
# 直接在宿主机查看
ls -la ~/.bub/tapes/

# 或在容器内查看
docker exec -it bub /entrypoint.sh ls -la /root/.bub/tapes/
```

## 高级配置

### 自定义沙箱配置

如需修改沙箱挂载，编辑 `entrypoint.sh` 中的 `BOXSH_ARGS`：

```bash
BOXSH_ARGS="--sandbox \
  --bind wr:/app \
  --bind wr:/root \
  --bind ro:/entrypoint.sh \
  --bind cow:/workspace:/boxsh \
  --bind ro:/root/.agents/skills \
  --bind ro:/root/.openclaw/openclaw-weixin \
  --bind wr:/root/.bub"
```

支持的 boxsh 挂载模式：
- `ro:PATH` - 只读挂载
- `wr:PATH` - 读写挂载
- `cow:SRC:DST` - 写时复制（SRC 为只读基座，DST 为沙箱内 merged view）

### 隔离网络访问

如需阻止 agent 访问外部网络，在 `entrypoint.sh` 中添加 `--new-net-ns` 参数：

```bash
BOXSH_ARGS="--sandbox \
  --new-net-ns \
  --bind cow:$WORKSPACE:/boxsh \
  ..."
```

这样沙箱内的进程将无法访问外部网络（包括 `curl`、`wget`、`npm install` 等）。

### 多实例部署

如需在同一台机器上运行多个 bub 实例，修改 `docker-compose.yml`：

```yaml
services:
  bub-1:
    build: .
    env_file: .env.bub1
    volumes:
      - ${BUB_WORKSPACE_1}:/workspace
      - ${BUB_BOXSH_1}:/boxsh
      - ${BUB_HOME_1}:/root/.bub
    container_name: bub-1

  bub-2:
    build: .
    env_file: .env.bub2
    volumes:
      - ${BUB_WORKSPACE_2}:/workspace
      - ${BUB_BOXSH_2}:/boxsh
      - ${BUB_HOME_2}:/root/.bub
    container_name: bub-2
```

每个实例的 `BUB_BOXSH` 必须指向不同的项目专属目录（如 `~/work/boxsh/project-1`、`~/work/boxsh/project-2`），避免 COW 写层互相污染。

## 技术细节

### boxsh 工作原理

boxsh 使用 Linux namespaces（或 macOS Seatbelt）创建进程级别的隔离环境：

- **User namespace**：进程内显示为 root，但实际上是普通用户
- **Mount namespace**：私有的挂载表，不影响宿主机
- **Overlayfs**：零拷贝的写时复制文件系统

### 性能特性

- ✅ 启动时间：< 5ms（相比 Docker 的 500ms-2s）
- ✅ 读取性能：零开销（直接访问原始文件）
- ✅ 写入性能：仅写入的文件会占用额外空间
- ✅ 内存占用：几乎无额外开销

### 安全边界

boxsh 提供的是**进程级别的文件系统隔离**，不是完整的容器隔离：

- ✅ 防止意外修改文件
- ✅ 防止路径遍历攻击
- ❌ 不防止恶意代码逃逸（需配合 Docker 的容器隔离）
- ❌ 不限制 CPU/内存资源（需配合 Docker 的资源限制）

因此建议：
- 开发/测试环境：boxsh 沙箱足够安全
- 生产环境：boxsh + Docker 双重隔离更安全
