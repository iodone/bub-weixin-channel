#!/bin/sh
# entrypoint.sh - Unified entrypoint for bub service and debugging
#
# Usage:
#   entrypoint.sh              - Start bub gateway (default)
#   entrypoint.sh shell        - Interactive shell in boxsh sandbox
#   entrypoint.sh <command>    - Run command in boxsh sandbox
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

BOXSH_ARGS="--sandbox \
  --bind wr:/app \
  --bind wr:/root \
  --bind ro:/entrypoint.sh \
  --bind wr:/boxsh \
  --bind cow:$WORKSPACE:/boxsh \
  --bind ro:/root/.agents/skills \
  --bind ro:/root/.openclaw/openclaw-weixin \
  --bind wr:/root/.bub"

# 如果没有参数，启动服务
if [ $# -eq 0 ]; then
  exec boxsh $BOXSH_ARGS -c "cd /app && uv run bub -w '$WORKSPACE' gateway"
fi

# 如果第一个参数是 "shell" 或 "sh"，启动交互式 shell
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
  shift
  exec boxsh $BOXSH_ARGS "$@"
fi

# 否则，在 boxsh 中执行传入的命令
exec boxsh $BOXSH_ARGS -c "$*"
