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

# Check boxsh is available (tested with boxsh 2.1.0)
if ! command -v boxsh >/dev/null 2>&1; then
    echo "Error: boxsh not found. Install from https://github.com/xicilion/boxsh" >&2
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
# NOTE: BUB_BOXSH_HOST must be empty (or non-existent) for boxsh cow:SRC:DST —
# boxsh rmdir's DST before mounting overlay. Do NOT create files inside it here.
mkdir -p "$BUB_WORKSPACE" "$BUB_BOXSH_HOST" "$BUB_HOME" \
  "$BUB_HOME/.config" "$BUB_HOME/.local/share" "$BUB_HOME/.local/state" "$BUB_HOME/tmp"

# Pre-create profiles in lower layer only (BUB_WORKSPACE).
# Upper layer profiles is created inside the sandbox after boxsh mounts COW.
mkdir -p "$BUB_WORKSPACE/profiles"

# Resolve uv toolchain paths for sandbox bind
UV_BIN_DIR="$(cd "$(dirname "$(command -v uv)")" && pwd)"
UV_DATA_DIR="$(expand_path "${XDG_DATA_HOME:-$HOME/.local/share}/uv")"

# Build boxsh arguments
BOXSH_ARGS="--sandbox \
  --bind ro:$SCRIPT_DIR \
  --bind cow:$BUB_WORKSPACE:$BUB_BOXSH_HOST \
  --bind wr:$BUB_HOME"

# uv binary and toolchain (Python installs, caches)
[ -d "$UV_BIN_DIR" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$UV_BIN_DIR"
[ -d "$UV_DATA_DIR" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$UV_DATA_DIR"

# Optional read-only binds (only if directories exist)
[ -d "$BUB_SKILLS" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_SKILLS"
# Bind parent dir (~/.openclaw) so weixin-agent can resolve its state path
BUB_WEIXIN_STATE_DIR="$(dirname "$BUB_WEIXIN_DATA")"
[ -d "$BUB_WEIXIN_STATE_DIR" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_WEIXIN_STATE_DIR"

# Sandbox init: set HOME/XDG to writable BUB_HOME, ensure PATH includes uv,
# create profiles in COW upper layer
SANDBOX_INIT="export HOME=$BUB_HOME \
  XDG_CONFIG_HOME=$BUB_HOME/.config \
  XDG_DATA_HOME=$BUB_HOME/.local/share \
  XDG_STATE_HOME=$BUB_HOME/.local/state \
  TMPDIR=$BUB_HOME/tmp TEMP=$BUB_HOME/tmp TMP=$BUB_HOME/tmp \
  OPENCLAW_STATE_DIR=$BUB_WEIXIN_STATE_DIR \
  CLAWDBOT_STATE_DIR=$BUB_WEIXIN_STATE_DIR \
  PATH=$UV_BIN_DIR:\$PATH \
  && mkdir -p \$HOME \$XDG_CONFIG_HOME \$XDG_DATA_HOME \$XDG_STATE_HOME \
  \$TMPDIR $BUB_BOXSH_HOST/profiles"

# Shell to use inside sandbox (default: sh; override with BOXSH_SHELL=fish etc.)
BOXSH_SHELL="${BOXSH_SHELL:-sh}"

# Run boxsh as supervised child with signal forwarding for clean Ctrl+C
run_supervised() {
    boxsh $BOXSH_ARGS -c "$1" &
    child=$!
    trap 'kill -INT "$child" 2>/dev/null; sleep 0.2; kill -TERM "$child" 2>/dev/null || true' INT
    trap 'kill -TERM "$child" 2>/dev/null || true' TERM HUP
    wait "$child" 2>/dev/null
    exit $?
}

# If no arguments, start the gateway
if [ $# -eq 0 ]; then
    run_supervised "$SANDBOX_INIT && cd $SCRIPT_DIR && exec uv run bub -w $BUB_BOXSH_HOST gateway"
fi

# If first argument is "shell" or "sh", launch boxsh native interactive shell
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
    shift
    exec env \
      HOME="$BUB_HOME" \
      XDG_CONFIG_HOME="$BUB_HOME/.config" \
      XDG_DATA_HOME="$BUB_HOME/.local/share" \
      XDG_STATE_HOME="$BUB_HOME/.local/state" \
      TMPDIR="$BUB_HOME/tmp" TEMP="$BUB_HOME/tmp" TMP="$BUB_HOME/tmp" \
      OPENCLAW_STATE_DIR="$BUB_WEIXIN_STATE_DIR" \
      CLAWDBOT_STATE_DIR="$BUB_WEIXIN_STATE_DIR" \
      PATH="$UV_BIN_DIR:$PATH" \
      boxsh $BOXSH_ARGS
fi

# Otherwise, run the given command in the sandbox
run_supervised "$SANDBOX_INIT && exec $*"
