"""Tool execution stats collected per-message via bub.tools loguru events.

Used by the Feishu channel to render a footer line like::

    ⏱️ 38.77秒 · 🔧 6 步 · bash×6 · ⚠️ 失败×1

The collector listens to Bub's built-in ``bub.tools`` logger (tool.call.start /
tool.call.error events) and forwards counts into the currently active
``ToolStats`` instance.  The channel is responsible for registering / popping
the stats instance around each inbound message lifecycle.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import dataclass, field

try:
    from loguru import logger
    HAS_LOGURU = True
except ImportError:  # pragma: no cover
    HAS_LOGURU = False


@dataclass
class ToolStats:
    """Aggregates tool execution counters for a single inbound message."""

    tool_counts: Counter = field(default_factory=Counter)
    failed_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def on_start(self, tool_name: str) -> None:
        with self._lock:
            self.tool_counts[tool_name] += 1

    def on_error(self, tool_name: str) -> None:
        with self._lock:
            self.failed_count += 1

    def snapshot(self) -> tuple[int, dict[str, int], int]:
        """Return (step_count, tool_counts, failed_count) as a snapshot."""
        with self._lock:
            total = sum(self.tool_counts.values())
            tools = dict(self.tool_counts)
            failed = self.failed_count
        return total, tools, failed


def format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as ``38.77秒`` or ``1分23.4秒``."""
    if seconds < 60:
        return f"{seconds:.2f}秒"
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}分{remaining:.1f}秒"


def render_footer(elapsed_seconds: float, stats: ToolStats | None) -> str:
    """Render the complete footer text.

    Always includes elapsed time.  When *stats* is provided and non-empty,
    appends step count, per-tool breakdown, and failure count.
    """
    parts = [f"⏱️ {format_elapsed(elapsed_seconds)}"]

    if stats is not None:
        total, tools, failed = stats.snapshot()
        if total > 0:
            parts.append(f"🔧 {total} 步")
            breakdown = "、".join(
                f"{name}×{count}"
                for name, count in sorted(tools.items(), key=lambda x: (-x[1], x[0]))
            )
            if breakdown:
                parts.append(breakdown)
        if failed > 0:
            parts.append(f"⚠️ 失败×{failed}")

    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Active-stats registry: channel registers on inbound, pops on outbound.
# ---------------------------------------------------------------------------

_active_stats: dict[str, ToolStats] = {}
_stats_lock = threading.Lock()
_sink_installed = False


def register(key: str) -> ToolStats:
    """Create and register a fresh ToolStats for the given key (usually message_id)."""
    stats = ToolStats()
    with _stats_lock:
        _active_stats[key] = stats
    return stats


def pop(key: str) -> ToolStats | None:
    """Remove and return the stats associated with *key*, if any."""
    with _stats_lock:
        return _active_stats.pop(key, None)


def _get_active() -> ToolStats | None:
    """Return the currently active stats (assumes at most one in flight).

    The Feishu channel processes messages through a per-chat serial queue,
    so there is normally a single active entry at a time.  When multiple
    are present (concurrent chats), the most recently registered wins.
    """
    with _stats_lock:
        if not _active_stats:
            return None
        # dict preserves insertion order; grab the last inserted
        return next(reversed(_active_stats.values()))


# Pre-compiled patterns for bub.tools log messages.
_START_RE = re.compile(r"tool\.call\.start name=(\w+)")
_ERROR_RE = re.compile(r"tool\.call\.error name=(\w+)")


def install_sink() -> None:
    """Install a loguru sink (once) that forwards tool events to active stats."""
    global _sink_installed
    if _sink_installed or not HAS_LOGURU:
        return
    _sink_installed = True

    def _sink(message):  # noqa: ANN001 — loguru handler signature
        record = message.record
        if record["name"] != "bub.tools":
            return
        level = record["level"].name
        if level not in ("INFO", "ERROR"):
            return

        stats = _get_active()
        if stats is None:
            return

        msg = record["message"]

        if level == "INFO":
            m = _START_RE.match(msg)
            if m:
                stats.on_start(m.group(1))
                return

        if level == "ERROR":
            m = _ERROR_RE.match(msg)
            if m:
                stats.on_error(m.group(1))
                return

    logger.add(
        _sink,
        level="INFO",
        filter=lambda r: r["name"] == "bub.tools",
    )
