#!/bin/sh
# run-host.sh - Run bub with boxsh sandbox directly on the host (no Docker)
#
# Usage:
#   run-host.sh              - Start bub gateway
#   run-host.sh shell        - Interactive shell in boxsh sandbox
#   run-host.sh <command>    - Run command in boxsh sandbox
#
# Requires:
#   - boxsh >= 2.1.0 (https://github.com/xicilion/boxsh)
#   - uv (https://github.com/astral-sh/uv)
#   - .env file with required configuration
#
# Environment variables (loaded from .env):
#   BUB_WORKSPACE   - Workspace base directory (COW lower layer, read-only)
#   BUB_BOXSH_HOST  - Host mode COW upper layer + runtime workspace (MUST differ from BUB_BOXSH)
#   BUB_SKILLS      - Skills directory (read-only in sandbox)
#   BUB_WEIXIN_DATA - WeChat credentials directory (read-only, optional)
#   BUB_HOME        - Bub home directory for tapes/config (read-write)
#
# COW path mapping (Host mode vs Docker mode):
#
#   Role                  Docker mode                    Host mode
#   ----                  -----------                    ---------
#   Lower (read-only)     /workspace-base ($BUB_WORKSPACE)  $BUB_WORKSPACE
#   Upper (writes)        /workspace ($BUB_BOXSH)            $BUB_BOXSH_HOST
#   Runtime workspace     /workspace                         $BUB_BOXSH_HOST
#   bub -w flag           /workspace                         $BUB_BOXSH_HOST
#
#   IMPORTANT: Host and Docker modes use SEPARATE upper directories to avoid
#   mixing COW artifacts. Docker uses BUB_BOXSH, Host uses BUB_BOXSH_HOST.
#
#   boxsh cow:SRC:DST mounts an overlayfs at DST with SRC as read-only base.
#   Writes go to DST. App code uses framework.workspace (from -w flag),
#   never hardcodes paths.

set -e

# Resolve project root (directory containing this script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check boxsh is available and version >= 2.1.0
if ! command -v boxsh >/dev/null 2>&1; then
    echo "Error: boxsh not found. Install from https://github.com/xicilion/boxsh" >&2
    exit 1
fi

BOXSH_VER="$(boxsh --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0.0.0")"
BOXSH_MAJOR="$(echo "$BOXSH_VER" | cut -d. -f1)"
BOXSH_MINOR="$(echo "$BOXSH_VER" | cut -d. -f2)"
if [ "$BOXSH_MAJOR" -lt 2 ] || { [ "$BOXSH_MAJOR" -eq 2 ] && [ "$BOXSH_MINOR" -lt 1 ]; }; then
    echo "Error: boxsh >= 2.1.0 required (found $BOXSH_VER)." >&2
    echo "  Host mode requires boxsh 2.1.0+ for non-empty COW DST support." >&2
    echo "  Upgrade: https://github.com/xicilion/boxsh/releases" >&2
    exit 1
fi

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
BUB_BOXSH_HOST="$(expand_path "${BUB_BOXSH_HOST:?BUB_BOXSH_HOST not set}")"
BUB_SKILLS="$(expand_path "${BUB_SKILLS:-$HOME/.agents/skills}")"
BUB_WEIXIN_DATA="$(expand_path "${BUB_WEIXIN_DATA:-$HOME/.openclaw/openclaw-weixin}")"
BUB_HOME="$(expand_path "${BUB_HOME:-$HOME/.bub}")"

# Ensure required directories exist
mkdir -p "$BUB_WORKSPACE" "$BUB_BOXSH_HOST" "$BUB_HOME"

# Pre-create profiles directory in both COW layers (avoids EXDEV)
mkdir -p "$BUB_WORKSPACE/profiles"
mkdir -p "$BUB_BOXSH_HOST/profiles"

# Build boxsh arguments
BOXSH_ARGS="--sandbox \
  --bind ro:$SCRIPT_DIR \
  --bind cow:$BUB_WORKSPACE:$BUB_BOXSH_HOST \
  --bind wr:$BUB_HOME"

# Optional read-only binds (only if directories exist)
[ -d "$BUB_SKILLS" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_SKILLS"
[ -d "$BUB_WEIXIN_DATA" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_WEIXIN_DATA"

# If no arguments, start the gateway
if [ $# -eq 0 ]; then
    exec boxsh $BOXSH_ARGS -c "cd $SCRIPT_DIR && uv run bub -w $BUB_BOXSH_HOST gateway"
fi

# If first argument is "shell" or "sh", start interactive shell
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
    shift
    exec boxsh $BOXSH_ARGS "$@"
fi

# Otherwise, run the given command in the sandbox
exec boxsh $BOXSH_ARGS -c "$*"
