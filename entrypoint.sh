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
#   /workspace                       (cow) agent workspace (COW merged view)
#   /root/.agents/skills             (ro) bub skills
#   /root/.openclaw/openclaw-weixin  (ro) weixin credentials
#   /root/.bub                       (rw) bub home (tapes, config)
#
# COW via boxsh native cow:SRC:DST:
#   SRC (/workspace-base) = read-only base (Docker volume from host workspace)
#   DST (/workspace)      = overlay mount point / merged view in sandbox
#   Writes persist to host's $BUB_BOXSH via Docker volume at /workspace (COW upper layer).

set -e

BOXSH_ARGS="--sandbox \
  --bind wr:/app \
  --bind wr:/root \
  --bind ro:/entrypoint.sh \
  --bind cow:/workspace-base:/workspace \
  --bind ro:/root/.agents/skills \
  --bind ro:/root/.openclaw/openclaw-weixin \
  --bind wr:/root/.bub"

# 如果没有参数，启动服务
if [ $# -eq 0 ]; then
  exec boxsh $BOXSH_ARGS -c "cd /app && uv run bub -w /workspace gateway"
fi

# 如果第一个参数是 "shell" 或 "sh"，启动交互式 shell
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
  shift
  exec boxsh $BOXSH_ARGS "$@"
fi

# 否则，在 boxsh 中执行传入的命令
exec boxsh $BOXSH_ARGS -c "$*"
