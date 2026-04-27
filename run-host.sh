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
#   BUB_WEIXIN_DATA - WeChat data directory (read-write, optional)
#   BUB_FEISHU_HOME - Feishu CLI auth directory (read-write, optional, default ~/.feishu)
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
BUB_FEISHU_HOME="$(expand_path "${BUB_FEISHU_HOME:-$HOME/.feishu}")"
BUB_HOME="$(expand_path "${BUB_HOME:-$HOME/.bub}")"
BUB_REAL_CONFIG="$(expand_path "${BUB_REAL_CONFIG:-$HOME/.config}")"
BUB_KYUUBI_HOME="$(expand_path "${BUB_KYUUBI_HOME:-$HOME/.kyuubi}")"

# Ensure required directories exist
# NOTE: BUB_BOXSH_HOST must be empty (or non-existent) for boxsh cow:SRC:DST —
# boxsh rmdir's DST before mounting overlay. Do NOT create files inside it here.
mkdir -p "$BUB_WORKSPACE" "$BUB_BOXSH_HOST" "$BUB_HOME" \
  "$BUB_HOME/.local/share" "$BUB_HOME/.local/state" "$BUB_HOME/tmp"

# Symlink real host directories into $BUB_HOME so tools that resolve ~ find them.
# Same pattern as skills and feishu: bind at original path, symlink from $BUB_HOME.
# These must be created before mkdir -p would turn them into plain directories.
make_home_link() {
    local real_path="$1" link_path="$2"
    if [ -d "$real_path" ]; then
        mkdir -p "$(dirname "$link_path")"
        if [ -d "$link_path" ] && [ ! -L "$link_path" ]; then
            # Plain directory left from a previous run — back it up and replace with symlink
            local backup="${link_path}.bak.$(date +%s)"
            echo "Migrating $link_path to symlink (backup at $backup)"
            mv "$link_path" "$backup"
        fi
        if [ ! -e "$link_path" ]; then
            ln -s "$real_path" "$link_path"
        elif [ ! -L "$link_path" ] || [ "$(readlink "$link_path")" != "$real_path" ]; then
            echo "Error: $link_path exists but does not point to $real_path" >&2
            exit 1
        fi
    fi
}
make_home_link "$BUB_REAL_CONFIG" "$BUB_HOME/.config"
make_home_link "$BUB_KYUUBI_HOME" "$BUB_HOME/.kyuubi"

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
# Real host directories: bind at original path, symlink from $BUB_HOME (via make_home_link above).
[ -d "$BUB_REAL_CONFIG" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$BUB_REAL_CONFIG"
[ -d "$BUB_KYUUBI_HOME" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$BUB_KYUUBI_HOME"
# Skills directory: bind at original path, then symlink from $BUB_HOME/.agents/skills
# so bub (which follows $HOME) can find it. Same pattern as feishu below.
if [ -d "$BUB_SKILLS" ]; then
    BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_SKILLS"
    SKILLS_LINK="$BUB_HOME/.agents/skills"
    mkdir -p "$(dirname "$SKILLS_LINK")"
    if [ ! -e "$SKILLS_LINK" ]; then
        ln -s "$BUB_SKILLS" "$SKILLS_LINK"
    elif [ ! -L "$SKILLS_LINK" ] || [ "$(readlink "$SKILLS_LINK")" != "$BUB_SKILLS" ]; then
        echo "Error: $SKILLS_LINK exists but does not point to $BUB_SKILLS" >&2
        exit 1
    fi
fi
# Weixin parent dir (ro for path resolution) and data dir (wr for sync state)
BUB_WEIXIN_STATE_DIR="$(dirname "$BUB_WEIXIN_DATA")"
[ -d "$BUB_WEIXIN_STATE_DIR" ] && BOXSH_ARGS="$BOXSH_ARGS --bind ro:$BUB_WEIXIN_STATE_DIR"
[ -d "$BUB_WEIXIN_DATA" ] && BOXSH_ARGS="$BOXSH_ARGS --bind wr:$BUB_WEIXIN_DATA"
# Feishu CLI auth directory (writable for token refresh)
# Bind at original path, then symlink from $BUB_HOME/.feishu so the CLI
# (which follows $HOME) can find it. boxsh wr binds don't support SRC:DST.
if [ -d "$BUB_FEISHU_HOME" ]; then
    BOXSH_ARGS="$BOXSH_ARGS --bind wr:$BUB_FEISHU_HOME"
    FEISHU_LINK="$BUB_HOME/.feishu"
    if [ ! -e "$FEISHU_LINK" ]; then
        ln -s "$BUB_FEISHU_HOME" "$FEISHU_LINK"
    elif [ ! -L "$FEISHU_LINK" ] || [ "$(readlink "$FEISHU_LINK")" != "$BUB_FEISHU_HOME" ]; then
        echo "Error: $FEISHU_LINK exists but does not point to $BUB_FEISHU_HOME" >&2
        exit 1
    fi
fi

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
    run_supervised "$SANDBOX_INIT && cd $SCRIPT_DIR && uv run bub -w $BUB_BOXSH_HOST gateway"
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
run_supervised "$SANDBOX_INIT && sh -c \"$*\""
