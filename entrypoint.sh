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
# COW setup:
#   fuse-overlayfs is set up BEFORE boxsh, with allow_other, so the
#   merged view at /workspace is accessible to all processes (including
#   docker exec). boxsh then binds /workspace as writable — it's already
#   the overlay.
#
# Docker volumes:
#   /workspace ← $BUB_WORKSPACE (original data, becomes overlay lower layer)
#   /boxsh     ← $BUB_BOXSH (persistent write layer, becomes overlay upper)

set -e

WORKSPACE="/workspace"

# --- Debug modes (via docker exec) ---
# docker exec enters PID 1's sandbox namespace where the COW overlay
# is already set up. Just exec a shell — no overlay init needed.
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
  shift
  exec sh "$@"
fi

if [ $# -gt 0 ]; then
  exec sh -c "$*"
fi

# --- Service startup (no args) ---

# COW overlay: set up fuse-overlayfs so /workspace becomes the merged view.
# allow_other lets docker exec processes access the overlay.
# workdir must be on the same filesystem as upperdir (/boxsh).
mkdir -p /tmp/overlay-lower /boxsh/.overlay-work
mount --bind $WORKSPACE /tmp/overlay-lower
fuse-overlayfs \
  -o "lowerdir=/tmp/overlay-lower,upperdir=/boxsh,workdir=/boxsh/.overlay-work,allow_other" \
  $WORKSPACE

# boxsh sandbox: /workspace is now the COW overlay, bind it as writable.
BOXSH_ARGS="--sandbox \
  --bind wr:/app \
  --bind wr:/root \
  --bind ro:/entrypoint.sh \
  --bind wr:$WORKSPACE \
  --bind ro:/root/.agents/skills \
  --bind ro:/root/.openclaw/openclaw-weixin \
  --bind wr:/root/.bub"

exec boxsh $BOXSH_ARGS -c "cd /app && uv run bub -w '$WORKSPACE' gateway"
