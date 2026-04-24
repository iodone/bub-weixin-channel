#!/bin/sh
# run-host.sh - Run bub with boxsh sandbox directly on the host (no Docker)
#
# Usage:
#   run-host.sh              - Start bub gateway
#   run-host.sh shell        - Interactive shell in boxsh sandbox
#   run-host.sh <command>    - Run command in boxsh sandbox
#
# Requires:
#   - boxsh installed (https://github.com/xicilion/boxsh)
#   - uv installed (https://github.com/astral-sh/uv)
#   - .env file with required configuration
#
# Environment variables (loaded from .env):
#   BUB_WORKSPACE   - Agent workspace base directory (read-only lower layer)
#   BUB_BOXSH       - COW upper layer directory (persists agent writes)
#   BUB_SKILLS      - Skills directory (read-only)
#   BUB_WEIXIN_DATA - WeChat credentials directory (read-only, optional)
#   BUB_HOME        - Bub home directory for tapes/config (read-write)
#
# Directory layout inside the sandbox:
#   /workspace   (cow) agent workspace (COW merged view)
#   /skills      (ro)  bub skills
#   /bub-home    (rw)  bub home (tapes, config)
#   Project dir  (ro)  application code

set -e

# Resolve project root (directory containing this script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
    # Export variables from .env, skipping comments and empty lines
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
fi

# Expand ~ in paths
expand_path() {
    eval echo "$1"
}

BUB_WORKSPACE="$(expand_path "${BUB_WORKSPACE:?BUB_WORKSPACE not set}")"
BUB_BOXSH="$(expand_path "${BUB_BOXSH:?BUB_BOXSH not set}")"
BUB_SKILLS="$(expand_path "${BUB_SKILLS:-$HOME/.agents/skills}")"
BUB_WEIXIN_DATA="$(expand_path "${BUB_WEIXIN_DATA:-$HOME/.openclaw/openclaw-weixin}")"
BUB_HOME="$(expand_path "${BUB_HOME:-$HOME/.bub}")"

# Ensure required directories exist
mkdir -p "$BUB_WORKSPACE" "$BUB_BOXSH" "$BUB_HOME"

# Pre-create profiles directory in both COW layers (avoids EXDEV)
mkdir -p "$BUB_WORKSPACE/profiles"
mkdir -p "$BUB_BOXSH/profiles"

# Build boxsh arguments
BOXSH_ARGS="--sandbox \
  --bind ro:$SCRIPT_DIR \
  --bind cow:$BUB_WORKSPACE:$BUB_BOXSH \
  --bind wr:$BUB_HOME"

# Optional read-only binds (only if directories exist)
[ -d "$BUB_SKILLS" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_SKILLS"
[ -d "$BUB_WEIXIN_DATA" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_WEIXIN_DATA"

# If no arguments, start the gateway
if [ $# -eq 0 ]; then
    exec boxsh $BOXSH_ARGS -c "cd $SCRIPT_DIR && uv run bub -w $BUB_BOXSH gateway"
fi

# If first argument is "shell" or "sh", start interactive shell
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
    shift
    exec boxsh $BOXSH_ARGS "$@"
fi

# Otherwise, run the given command in the sandbox
exec boxsh $BOXSH_ARGS -c "$*"
