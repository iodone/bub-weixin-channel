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
#   BUB_WORKSPACE   - Host mode runtime workspace (read-write bind inside sandbox)
#   BUB_BOXSH_HOST  - Legacy host mode COW path (no longer used, kept for backward compatibility)
#   BUB_SKILLS      - Skills directory (read-only in sandbox)
#   BUB_WEIXIN_DATA - WeChat data directory (read-write, optional)
#   BUB_FEISHU_HOME - Feishu CLI auth directory (read-write, optional, default ~/.feishu)
#
# Workspace mapping:
#
#   Docker mode: entrypoint.sh still uses boxsh COW (`cow:/workspace-base:/workspace`)
#   Host mode:   run-host.sh exposes the real BUB_WORKSPACE as read-write
#
# Host mode intentionally does NOT use COW anymore. Several tools expect the
# real workspace path to exist and be writable, and the overlay path caused
# behavior drift versus running directly on the host.
#
# HOME strategy (plan B):
#   HOME is set to the real user home directory (not BUB_HOME).
#   Tools that resolve paths via ~ (skills, feishu, kyuubi, etc.) work naturally.
#   BUB_HOME is used only for bub-specific state (tapes, config).
#   Path protection is maintained by selective --bind, not by remapping HOME.

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
BUB_BOXSH_HOST="$(expand_path "${BUB_BOXSH_HOST:-}")"
BUB_SKILLS="$(expand_path "${BUB_SKILLS:-$HOME/.agents/skills}")"
BUB_WEIXIN_DATA="$(expand_path "${BUB_WEIXIN_DATA:-$HOME/.openclaw/openclaw-weixin}")"
BUB_FEISHU_HOME="$(expand_path "${BUB_FEISHU_HOME:-$HOME/.feishu}")"
# BUB_HOME is always $HOME/.bub — bub resolves its state directory via ~.
# Not configurable: changing it would require also changing bub's own path resolution.
BUB_HOME="$HOME/.bub"

# Ensure required directories exist
mkdir -p "$BUB_WORKSPACE/profiles"
mkdir -p "$BUB_HOME" "$BUB_HOME/tmp"

# Resolve uv toolchain paths for sandbox bind
UV_BIN_DIR="$(cd "$(dirname "$(command -v uv)")" && pwd)"
UV_DATA_DIR="$(expand_path "${XDG_DATA_HOME:-$HOME/.local/share}/uv")"

# Build boxsh arguments
# HOME is the real user home — no remapping. Path protection via selective binds.
BOXSH_ARGS="--sandbox --bind wr:$BUB_WORKSPACE --bind wr:$BUB_HOME"

# If the project repo itself is outside BUB_WORKSPACE, it still needs to be
# writable in host mode because `uv run` may update the repo-local `.venv`.
case "$SCRIPT_DIR" in
  "$BUB_WORKSPACE"|"$BUB_WORKSPACE"/*) ;;
  *) BOXSH_ARGS="$BOXSH_ARGS --bind wr:$SCRIPT_DIR" ;;
esac

# uv binary and toolchain (Python installs, caches)
[ -d "$UV_BIN_DIR" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$UV_BIN_DIR"
[ -d "$UV_DATA_DIR" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$UV_DATA_DIR"
# pipx venvs (for tools installed via pipx, e.g. kyuubi)
PIPX_HOME="${PIPX_HOME:-$HOME/.local/pipx}"
[ -d "$PIPX_HOME" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$PIPX_HOME"

# Optional binds — real user directories, accessed at their real paths via ~
# Skills directory (read-only)
[ -d "$BUB_SKILLS" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_SKILLS"
# Weixin parent dir (ro for path resolution) and data dir (wr for sync state)
BUB_WEIXIN_STATE_DIR="$(dirname "$BUB_WEIXIN_DATA")"
[ -d "$BUB_WEIXIN_STATE_DIR" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_WEIXIN_STATE_DIR"
[ -d "$BUB_WEIXIN_DATA" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$BUB_WEIXIN_DATA"
# Feishu CLI auth directory (writable for token refresh)
[ -d "$BUB_FEISHU_HOME" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$BUB_FEISHU_HOME"
# User config, cache, and kyuubi (writable, tools resolve via ~)
[ -d "$HOME/.config" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$HOME/.config"
[ -d "$HOME/.cache" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$HOME/.cache"
[ -d "$HOME/.kyuubi" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$HOME/.kyuubi"
[ -d "$HOME/.opencli" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$HOME/.opencli"

# Sandbox init: HOME is the real user home, TMPDIR in BUB_HOME for isolation
SANDBOX_INIT="export HOME=$HOME \
  TMPDIR=$BUB_HOME/tmp TEMP=$BUB_HOME/tmp TMP=$BUB_HOME/tmp \
  OPENCLAW_STATE_DIR=$BUB_WEIXIN_STATE_DIR \
  CLAWDBOT_STATE_DIR=$BUB_WEIXIN_STATE_DIR \
  PATH=$UV_BIN_DIR:\$PATH \
  && mkdir -p $BUB_HOME/tmp $BUB_WORKSPACE/profiles"

# Run boxsh with signal forwarding for clean Ctrl+C.
#
# IMPORTANT: The command passed to boxsh must NOT use `exec`.  Keeping the
# inner shell alive (as a wrapper around the real command) ensures that
# all descendants remain findable via `pgrep -P` even after intermediate
# processes exit.  If `exec` is used, an intermediate process (e.g. uv)
# can exit and its children get reparented to PID 1, making them invisible
# to the tree walk.
run_supervised() {
    boxsh $BOXSH_ARGS -c "$1" &
    child=$!

    kill_tree() {
        for cpid in $(pgrep -P "$1" 2>/dev/null); do
            kill_tree "$cpid" "$2"
        done
        kill "-$2" "$1" 2>/dev/null || true
    }

    cleanup() {
        kill_tree "$child" TERM
        sleep 0.3
        kill_tree "$child" KILL 2>/dev/null || true
    }

    trap cleanup INT TERM HUP
    set +e
    wait "$child"
    set -e
    cleanup
    exit 0
}

# If no arguments, start the gateway
if [ $# -eq 0 ]; then
    run_supervised "$SANDBOX_INIT && cd $SCRIPT_DIR && uv run bub -w $BUB_WORKSPACE gateway"
fi

# If first argument is "shell" or "sh", launch boxsh native interactive shell
if [ "$1" = "shell" ] || [ "$1" = "sh" ]; then
    shift
    exec env \
      HOME="$HOME" \
      TMPDIR="$BUB_HOME/tmp" TEMP="$BUB_HOME/tmp" TMP="$BUB_HOME/tmp" \
      OPENCLAW_STATE_DIR="$BUB_WEIXIN_STATE_DIR" \
      CLAWDBOT_STATE_DIR="$BUB_WEIXIN_STATE_DIR" \
      PATH="$UV_BIN_DIR:$PATH" \
      boxsh $BOXSH_ARGS
fi

# Otherwise, run the given command in the sandbox
run_supervised "$SANDBOX_INIT && sh -c \"$*\""
