"""Unit tests for bub_im_bridge.queue – PriorityMessageQueue and config helpers."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from bub.channels.message import ChannelMessage
from bub_im_bridge.queue import (
    PriorityMessageQueue,
    _parse_collection,
    get_queue_max_length,
    is_admin_sender,
)

ADMIN_ID = "ou_admin_001"


def _msg(
    content: str = "hello",
    session_id: str = "s1",
    sender_id: str = "",
) -> ChannelMessage:
    ctx: dict = {}
    if sender_id:
        ctx["sender_id"] = sender_id
    return ChannelMessage(
        session_id=session_id,
        channel="test",
        content=content,
        context=ctx,
    )


@pytest.fixture(autouse=True)
def _reset_admin_cache():
    import bub_im_bridge.queue as qmod

    qmod._ADMIN_USERS = None
    yield
    qmod._ADMIN_USERS = None


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", set()),
        ("a, b ,c", {"a", "b", "c"}),
        ('["x","y"]', {"x", "y"}),
        ("only", {"only"}),
        ("  a , , b ", {"a", "b"}),
        ("[broken", {"[broken"}),
    ],
)
def test_parse_collection(raw: str, expected: set[str]):
    assert _parse_collection(raw) == expected


@patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
def test_is_admin_sender():
    assert is_admin_sender(ADMIN_ID) is True
    assert is_admin_sender("ou_nobody") is False
    assert is_admin_sender("") is False


@pytest.mark.parametrize(
    "env_val, expected",
    [("42", 42), ("bad", 0), ("", 0)],
)
def test_get_queue_max_length(env_val: str, expected: int):
    with patch.dict(os.environ, {"BUB_FEISHU_QUEUE_MAX_LENGTH": env_val}):
        assert get_queue_max_length() == expected


# ---------------------------------------------------------------------------
# put / get – FIFO and async blocking
# ---------------------------------------------------------------------------


async def test_put_get_fifo():
    q = PriorityMessageQueue()
    await q.put(_msg("first"))
    await q.put(_msg("second"))
    assert (await q.get()).content == "first"
    assert (await q.get()).content == "second"
    assert q.size == 0


async def test_get_blocks_until_put():
    q = PriorityMessageQueue()
    result: list[str] = []

    async def consumer():
        result.append((await q.get()).content)

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    assert result == []

    await q.put(_msg("wake"))
    await asyncio.sleep(0.05)
    assert result == ["wake"]
    await task


# ---------------------------------------------------------------------------
# Priority ordering – admin (0) before normal (1)
# ---------------------------------------------------------------------------


@patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
async def test_admin_priority():
    q = PriorityMessageQueue()
    await q.put(_msg("n1"))
    await q.put(_msg("n2"))
    await q.put(_msg("admin", sender_id=ADMIN_ID))

    contents = [(await q.get()).content for _ in range(3)]
    assert contents == ["admin", "n1", "n2"]


# ---------------------------------------------------------------------------
# Queue limits
# ---------------------------------------------------------------------------


async def test_normal_dropped_when_full():
    q = PriorityMessageQueue(max_length=2)
    assert await q.put(_msg("m1")) is True
    assert await q.put(_msg("m2")) is True
    assert await q.put(_msg("m3")) is False
    assert q.size == 2


@patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
async def test_admin_bypasses_normal_limit():
    q = PriorityMessageQueue(max_length=1)
    await q.put(_msg("n1"))
    assert await q.put(_msg("admin", sender_id=ADMIN_ID)) is True
    assert q.size == 2


@patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
async def test_admin_max_length():
    q = PriorityMessageQueue(admin_max_length=1)
    assert await q.put(_msg("a1", sender_id=ADMIN_ID)) is True
    assert await q.put(_msg("a2", sender_id=ADMIN_ID)) is False


# ---------------------------------------------------------------------------
# drain – global and per-session
# ---------------------------------------------------------------------------


async def test_drain_all():
    q = PriorityMessageQueue()
    await q.put(_msg("a", session_id="s1"))
    await q.put(_msg("b", session_id="s2"))
    assert len(q.drain()) == 2
    assert q.size == 0


async def test_drain_by_session():
    q = PriorityMessageQueue()
    await q.put(_msg("a", session_id="s1"))
    await q.put(_msg("b", session_id="s2"))
    await q.put(_msg("c", session_id="s1"))

    drained = q.drain(session_id="s1")
    assert len(drained) == 2 and all(m.session_id == "s1" for m in drained)
    assert q.size == 1
    assert (await q.get()).session_id == "s2"


# ---------------------------------------------------------------------------
# Worker integration – simulates _queue_worker forwarding
# ---------------------------------------------------------------------------


async def test_worker_forwards_messages():
    """Messages are forwarded to framework handler in priority order."""
    q = PriorityMessageQueue()
    received: list[str] = []

    async def fake_handler(msg: ChannelMessage) -> None:
        received.append(msg.content)

    async def worker():
        while True:
            try:
                msg = await q.get()
            except asyncio.CancelledError:
                break
            await fake_handler(msg)

    task = asyncio.create_task(worker())
    await q.put(_msg("a"))
    await q.put(_msg("b"))
    await asyncio.sleep(0.1)

    assert received == ["a", "b"]
    task.cancel()
    await task


async def test_drain_stops_pending_messages():
    """drain() removes messages before worker can process them."""
    q = PriorityMessageQueue()
    received: list[str] = []

    async def fake_handler(msg: ChannelMessage) -> None:
        received.append(msg.content)

    async def worker():
        while True:
            try:
                msg = await q.get()
            except asyncio.CancelledError:
                break
            # Simulate slow processing
            await asyncio.sleep(0.2)
            await fake_handler(msg)

    task = asyncio.create_task(worker())
    await q.put(_msg("processing"))
    await q.put(_msg("queued1"))
    await q.put(_msg("queued2"))
    await asyncio.sleep(0.05)  # worker picks up "processing", others still in queue

    drained = q.drain()
    assert len(drained) == 2
    assert q.size == 0

    await asyncio.sleep(0.3)  # wait for "processing" to finish
    assert received == ["processing"]  # queued1/queued2 never processed

    task.cancel()
    await task
