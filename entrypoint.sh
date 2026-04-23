#!/bin/sh
# entrypoint.sh - Unified entrypoint for bub service and debugging
#
# Usage:
#   entrypoint.sh              - Start bub gateway (default)
#   entrypoint.sh shell        - Interactive shell (sandbox view)
#   entrypoint.sh <command>    - Run command (sandbox view)
#
# Directory layout inside the sandbox:
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

# --- Debug modes (via docker exec) ---
# docker exec enters PID 1's sandbox namespace. Just exec a shell.
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
  shift
  exec sh "$@"
fi

if [ $# -gt 0 ]; then
  exec sh -c "$*"
fi

# --- Service startup (no args) ---
BOXSH_ARGS="--sandbox \
  --bind wr:/app \
  --bind wr:/root \
  --bind ro:/entrypoint.sh \
  --bind cow:/workspace-base:/workspace \
  --bind ro:/root/.agents/skills \
  --bind ro:/root/.openclaw/openclaw-weixin \
  --bind wr:/root/.bub"

exec boxsh $BOXSH_ARGS -c "cd /app && uv run bub -w /workspace gateway"
