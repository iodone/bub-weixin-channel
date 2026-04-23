#!/bin/sh
# entrypoint.sh - Unified entrypoint for bub service and debugging
#
# Usage:
#   entrypoint.sh              - Start bub gateway (default)
#   entrypoint.sh shell        - Interactive shell (sandbox view)
#   entrypoint.sh <command>    - Run command (sandbox view)
#
# Directory layout inside the container:
#   /app                             (rw) application code
#   /root                            (rw) home directory
#   /workspace                       (cow) agent workspace (read-only base, writes go to /boxsh)
#   /boxsh                           (rw) COW write layer for /workspace
#   /root/.agents/skills             (ro) bub skills
#   /root/.openclaw/openclaw-weixin  (ro) weixin credentials
#   /root/.bub                       (rw) bub home (tapes, config)
#
# Note: Bind order matters! Later binds override earlier ones.

set -e

# Fixed paths inside container (mounted via docker-compose volumes)
WORKSPACE="/workspace"

# Service mode: boxsh sandbox with COW overlay for /workspace
BOXSH_ARGS="--sandbox \
  --bind wr:/app \
  --bind wr:/root \
  --bind ro:/entrypoint.sh \
  --bind cow:$WORKSPACE:/boxsh \
  --bind ro:/root/.agents/skills \
  --bind ro:/root/.openclaw/openclaw-weixin \
  --bind wr:/root/.bub"

# 如果没有参数，启动服务（COW 模式）
if [ $# -eq 0 ]; then
  exec boxsh $BOXSH_ARGS -c "cd /app && uv run bub -w '$WORKSPACE' gateway"
fi

# Debug modes: when called via `docker exec`, the process already runs
# inside PID 1's boxsh sandbox namespace (COW overlay, ro/wr binds all
# in effect). Nesting a second boxsh fails because fuse-overlayfs mounts
# cannot be used as bind sources for a new namespace. Just exec a shell
# directly — the sandbox protections are already inherited.
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
  shift
  exec sh "$@"
fi

# 在沙箱中执行传入的命令
exec sh -c "$*"
