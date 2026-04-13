"""Async priority queue for channel message handling."""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import json
import os

from loguru import logger

from bub.channels.message import ChannelMessage


class PriorityMessageQueue:
    """Async priority queue backed by heapq.

    - Admin messages (priority 0) are processed first.
    - Normal messages (priority 1) follow FIFO within their tier.
    - Bounded by *max_length*; overflow drops the new normal message.
    - ``cancelled`` flag makes the worker block until explicitly resumed.
    """

    def __init__(self, max_length: int = 0, admin_max_length: int = 100) -> None:
        self._heap: list[tuple[int, int, ChannelMessage]] = []
        self._counter = 0
        self._max_length = max_length
        self._admin_max_length = admin_max_length
        self._event = asyncio.Event()
        # Per-session cancel state and resume events
        self._cancelled: dict[str, bool] = {}
        self._resume_events: dict[str, asyncio.Event] = {}

    # -- public interface (called from channel) --------------------------------

    async def put(self, message: ChannelMessage) -> bool:
        """Enqueue *message*.  Admin messages jump to the front.

        Returns True if enqueued successfully, False if dropped due to queue full.
        """
        priority = 0 if self._is_admin(message) else 1

        # Check admin queue limit
        if priority == 0 and self._admin_max_length > 0:
            admin_count = sum(1 for p, _, _ in self._heap if p == 0)
            if admin_count >= self._admin_max_length:
                logger.warning(
                    "queue.admin_full dropped session_id={} content={}",
                    message.session_id,
                    message.content[:80],
                )
                return False

        # Check normal message queue limit
        if (
            self._max_length > 0
            and len(self._heap) >= self._max_length
            and priority > 0
        ):
            logger.warning(
                "queue.full dropped session_id={} content={}",
                message.session_id,
                message.content[:80],
            )
            return False

        heapq.heappush(self._heap, (priority, self._counter, message))
        self._counter += 1
        self._event.set()
        return True

    async def get(self) -> ChannelMessage:
        """Block until an item is available, then return the highest-priority one."""
        while not self._heap:
            self._event.clear()
            await self._event.wait()
        _, _, msg = heapq.heappop(self._heap)
        if not self._heap:
            self._event.clear()
        return msg

    def drain(self, session_id: str | None = None) -> list[ChannelMessage]:
        """Remove and return pending messages.

        If session_id is provided, only drain messages for that session.
        Otherwise drain all messages (for backward compatibility).
        """
        if session_id is None:
            # Drain all messages
            items = [heapq.heappop(self._heap)[2] for _ in range(len(self._heap))]
            self._event.clear()
            return items

        # Drain only messages for specific session
        remaining = []
        drained = []
        while self._heap:
            priority, counter, msg = heapq.heappop(self._heap)
            if msg.session_id == session_id:
                drained.append(msg)
            else:
                remaining.append((priority, counter, msg))

        # Rebuild heap with remaining messages
        self._heap = remaining
        heapq.heapify(self._heap)
        if not self._heap:
            self._event.clear()

        return drained

    # -- cancel / resume --------------------------------------------------------

    def is_cancelled(self, session_id: str) -> bool:
        """Check if a specific session is cancelled."""
        return self._cancelled.get(session_id, False)

    def cancelled_sessions(self) -> list[str]:
        """Return list of currently cancelled session IDs."""
        return [sid for sid, v in self._cancelled.items() if v]

    def set_cancelled(self, session_id: str, value: bool) -> None:
        """Set cancel state for a specific session."""
        self._cancelled[session_id] = value
        if value:
            # Ensure a per-session event exists and is cleared (blocked)
            if session_id not in self._resume_events:
                self._resume_events[session_id] = asyncio.Event()
            self._resume_events[session_id].clear()
        else:
            # Wake up anyone waiting on this session
            ev = self._resume_events.get(session_id)
            if ev is not None:
                ev.set()
            # Clean up
            self._cancelled.pop(session_id, None)

    async def wait_for_resume(self, session_id: str) -> None:
        """Block until *session_id* is resumed."""
        ev = self._resume_events.get(session_id)
        if ev is None:
            return
        await ev.wait()

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _is_admin(message: ChannelMessage) -> bool:
        return is_admin_sender(message.context.get("sender_id", ""))

    @property
    def size(self) -> int:
        return len(self._heap)

    @property
    def max_length(self) -> int:
        return self._max_length


# ---------------------------------------------------------------------------
# Configuration helpers (exported for use in channel modules)
# ---------------------------------------------------------------------------


def _parse_collection(raw: str) -> set[str]:
    """Parse comma-separated string or JSON array into a set."""
    if not raw:
        return set()
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return {str(item).strip() for item in parsed if str(item).strip()}
    return {item.strip() for item in raw.split(",") if item.strip()}


_ADMIN_USERS: set[str] | None = None


def _get_admin_users() -> set[str]:
    global _ADMIN_USERS
    if _ADMIN_USERS is None:
        _ADMIN_USERS = _parse_collection(os.environ.get("BUB_ADMIN_USERS", ""))
    return _ADMIN_USERS


def is_admin_sender(sender_id: str) -> bool:
    """Check whether *sender_id* belongs to an admin user."""
    return sender_id in _get_admin_users() if sender_id else False


def get_queue_max_length() -> int:
    """Read BUB_QUEUE_MAX_LENGTH from env.  0 means unlimited."""
    raw = os.environ.get("BUB_QUEUE_MAX_LENGTH", "0")
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0
