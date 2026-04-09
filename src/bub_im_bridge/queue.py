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

    def __init__(self, max_length: int = 0) -> None:
        self._heap: list[tuple[int, int, ChannelMessage]] = []
        self._counter = 0
        self._max_length = max_length
        self._event = asyncio.Event()
        self._cancelled = False

    # -- public interface (called from channel) --------------------------------

    async def put(self, message: ChannelMessage) -> None:
        """Enqueue *message*.  Admin messages jump to the front."""
        priority = 0 if self._is_admin(message) else 1

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
            return

        heapq.heappush(self._heap, (priority, self._counter, message))
        self._counter += 1
        self._event.set()

    async def get(self) -> ChannelMessage:
        """Block until an item is available, then return the highest-priority one."""
        while not self._heap:
            self._event.clear()
            await self._event.wait()
        _, _, msg = heapq.heappop(self._heap)
        if not self._heap:
            self._event.clear()
        return msg

    def drain(self) -> list[ChannelMessage]:
        """Remove and return all pending messages."""
        items = [heapq.heappop(self._heap)[2] for _ in range(len(self._heap))]
        self._event.clear()
        return items

    # -- cancel / resume --------------------------------------------------------

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def set_cancelled(self, value: bool) -> None:
        self._cancelled = value
        if not value:
            self._event.set()  # wake worker on resume

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _is_admin(message: ChannelMessage) -> bool:
        return PriorityMessageQueue._is_admin_sender(
            message.context.get("sender_id", "")
        )

    @staticmethod
    def _is_admin_sender(sender_id: str) -> bool:
        return sender_id in _get_admin_users() if sender_id else False

    @property
    def size(self) -> int:
        return len(self._heap)

    @property
    def max_length(self) -> int:
        return self._max_length


# ---------------------------------------------------------------------------
# Configuration helpers
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


def get_queue_max_length() -> int:
    """Read BUB_QUEUE_MAX_LENGTH from env.  0 means unlimited."""
    raw = os.environ.get("BUB_QUEUE_MAX_LENGTH", "0")
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0
