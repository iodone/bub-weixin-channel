"""Unit tests for bub_im_bridge.queue module."""

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(
    content: str = "hello",
    session_id: str = "s1",
    sender_id: str = "",
) -> ChannelMessage:
    """Build a minimal ChannelMessage for testing."""
    ctx: dict = {}
    if sender_id:
        ctx["sender_id"] = sender_id
    return ChannelMessage(
        session_id=session_id,
        channel="test",
        content=content,
        context=ctx,
    )


ADMIN_ID = "ou_admin_001"


@pytest.fixture(autouse=True)
def _reset_admin_cache():
    """Reset the module-level _ADMIN_USERS cache before each test."""
    import bub_im_bridge.queue as qmod

    qmod._ADMIN_USERS = None
    yield
    qmod._ADMIN_USERS = None


# ---------------------------------------------------------------------------
# _parse_collection
# ---------------------------------------------------------------------------


class TestParseCollection:
    def test_empty_string(self):
        assert _parse_collection("") == set()

    def test_comma_separated(self):
        assert _parse_collection("a, b ,c") == {"a", "b", "c"}

    def test_json_array(self):
        assert _parse_collection('["x","y"]') == {"x", "y"}

    def test_single_value(self):
        assert _parse_collection("only") == {"only"}

    def test_strips_whitespace(self):
        assert _parse_collection("  a , , b ") == {"a", "b"}

    def test_invalid_json_falls_back_to_csv(self):
        assert _parse_collection("[broken") == {"[broken"}


# ---------------------------------------------------------------------------
# is_admin_sender / get_queue_max_length
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    @patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
    def test_is_admin_sender_true(self):
        assert is_admin_sender(ADMIN_ID) is True

    @patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
    def test_is_admin_sender_false(self):
        assert is_admin_sender("ou_nobody") is False

    def test_is_admin_sender_empty(self):
        assert is_admin_sender("") is False

    @patch.dict(os.environ, {"BUB_FEISHU_QUEUE_MAX_LENGTH": "42"})
    def test_get_queue_max_length(self):
        assert get_queue_max_length() == 42

    @patch.dict(os.environ, {"BUB_FEISHU_QUEUE_MAX_LENGTH": "bad"})
    def test_get_queue_max_length_invalid(self):
        assert get_queue_max_length() == 0

    @patch.dict(os.environ, {}, clear=False)
    def test_get_queue_max_length_default(self):
        os.environ.pop("BUB_FEISHU_QUEUE_MAX_LENGTH", None)
        assert get_queue_max_length() == 0


# ---------------------------------------------------------------------------
# PriorityMessageQueue – basic put / get
# ---------------------------------------------------------------------------


class TestQueuePutGet:
    @pytest.fixture
    def queue(self):
        return PriorityMessageQueue()

    @pytest.mark.asyncio
    async def test_put_get_fifo(self, queue: PriorityMessageQueue):
        await queue.put(_msg("first"))
        await queue.put(_msg("second"))
        m1 = await queue.get()
        m2 = await queue.get()
        assert m1.content == "first"
        assert m2.content == "second"

    @pytest.mark.asyncio
    async def test_size(self, queue: PriorityMessageQueue):
        assert queue.size == 0
        await queue.put(_msg("a"))
        assert queue.size == 1
        await queue.get()
        assert queue.size == 0

    @pytest.mark.asyncio
    async def test_get_blocks_until_put(self, queue: PriorityMessageQueue):
        result: list[str] = []

        async def consumer():
            msg = await queue.get()
            result.append(msg.content)

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        assert result == []  # still blocked

        await queue.put(_msg("wake"))
        await asyncio.sleep(0.05)
        assert result == ["wake"]
        await task


# ---------------------------------------------------------------------------
# PriorityMessageQueue – priority ordering
# ---------------------------------------------------------------------------


class TestQueuePriority:
    @pytest.mark.asyncio
    @patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
    async def test_admin_messages_processed_first(self):
        q = PriorityMessageQueue()
        await q.put(_msg("normal1"))
        await q.put(_msg("normal2"))
        await q.put(_msg("admin", sender_id=ADMIN_ID))

        m1 = await q.get()
        assert m1.content == "admin"
        m2 = await q.get()
        assert m2.content == "normal1"
        m3 = await q.get()
        assert m3.content == "normal2"

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
    async def test_fifo_within_same_priority(self):
        q = PriorityMessageQueue()
        await q.put(_msg("n1"))
        await q.put(_msg("n2"))
        await q.put(_msg("n3"))
        contents = [((await q.get()).content) for _ in range(3)]
        assert contents == ["n1", "n2", "n3"]


# ---------------------------------------------------------------------------
# PriorityMessageQueue – max_length / admin_max_length
# ---------------------------------------------------------------------------


class TestQueueLimits:
    @pytest.mark.asyncio
    async def test_normal_messages_dropped_when_full(self):
        q = PriorityMessageQueue(max_length=2)
        assert await q.put(_msg("m1")) is True
        assert await q.put(_msg("m2")) is True
        assert await q.put(_msg("m3")) is False  # dropped
        assert q.size == 2

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
    async def test_admin_not_blocked_by_normal_limit(self):
        q = PriorityMessageQueue(max_length=1)
        assert await q.put(_msg("n1")) is True
        # Queue full for normal messages, but admin bypasses
        assert await q.put(_msg("admin", sender_id=ADMIN_ID)) is True
        assert q.size == 2

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"BUB_FEISHU_ADMIN_USERS": ADMIN_ID})
    async def test_admin_max_length(self):
        q = PriorityMessageQueue(admin_max_length=2)
        assert await q.put(_msg("a1", sender_id=ADMIN_ID)) is True
        assert await q.put(_msg("a2", sender_id=ADMIN_ID)) is True
        assert await q.put(_msg("a3", sender_id=ADMIN_ID)) is False  # dropped
        assert q.size == 2

    @pytest.mark.asyncio
    async def test_unlimited_when_max_length_zero(self):
        q = PriorityMessageQueue(max_length=0)
        for i in range(100):
            assert await q.put(_msg(f"m{i}")) is True
        assert q.size == 100


# ---------------------------------------------------------------------------
# PriorityMessageQueue – drain
# ---------------------------------------------------------------------------


class TestQueueDrain:
    @pytest.mark.asyncio
    async def test_drain_all(self):
        q = PriorityMessageQueue()
        await q.put(_msg("a", session_id="s1"))
        await q.put(_msg("b", session_id="s2"))
        await q.put(_msg("c", session_id="s1"))

        drained = q.drain()
        assert len(drained) == 3
        assert q.size == 0

    @pytest.mark.asyncio
    async def test_drain_by_session(self):
        q = PriorityMessageQueue()
        await q.put(_msg("a", session_id="s1"))
        await q.put(_msg("b", session_id="s2"))
        await q.put(_msg("c", session_id="s1"))

        drained = q.drain(session_id="s1")
        assert len(drained) == 2
        assert all(m.session_id == "s1" for m in drained)
        assert q.size == 1  # s2 still there

        remaining = await q.get()
        assert remaining.session_id == "s2"

    @pytest.mark.asyncio
    async def test_drain_empty_queue(self):
        q = PriorityMessageQueue()
        assert q.drain() == []

    @pytest.mark.asyncio
    async def test_drain_nonexistent_session(self):
        q = PriorityMessageQueue()
        await q.put(_msg("a", session_id="s1"))
        drained = q.drain(session_id="s_none")
        assert drained == []
        assert q.size == 1


# ---------------------------------------------------------------------------
# PriorityMessageQueue – cancel / resume (per-session)
# ---------------------------------------------------------------------------


class TestQueueCancelResume:
    def test_initial_state_not_cancelled(self):
        q = PriorityMessageQueue()
        assert q.is_cancelled("s1") is False
        assert q.cancelled_sessions() == []

    def test_set_cancelled_per_session(self):
        q = PriorityMessageQueue()
        q.set_cancelled("s1", True)
        q.set_cancelled("s2", True)

        assert q.is_cancelled("s1") is True
        assert q.is_cancelled("s2") is True
        assert q.is_cancelled("s3") is False
        assert set(q.cancelled_sessions()) == {"s1", "s2"}

    def test_resume_clears_session(self):
        q = PriorityMessageQueue()
        q.set_cancelled("s1", True)
        q.set_cancelled("s2", True)

        q.set_cancelled("s1", False)
        assert q.is_cancelled("s1") is False
        assert q.is_cancelled("s2") is True
        assert q.cancelled_sessions() == ["s2"]

    @pytest.mark.asyncio
    async def test_wait_for_resume_blocks_and_wakes(self):
        q = PriorityMessageQueue()
        q.set_cancelled("s1", True)

        woke_up = False

        async def waiter():
            nonlocal woke_up
            await q.wait_for_resume("s1")
            woke_up = True

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert woke_up is False  # still blocked

        q.set_cancelled("s1", False)  # resume
        await asyncio.sleep(0.05)
        assert woke_up is True
        await task

    @pytest.mark.asyncio
    async def test_wait_for_resume_per_session_isolation(self):
        """Resuming s1 should NOT wake a waiter blocked on s2."""
        q = PriorityMessageQueue()
        q.set_cancelled("s1", True)
        q.set_cancelled("s2", True)

        s2_woke = False

        async def waiter_s2():
            nonlocal s2_woke
            await q.wait_for_resume("s2")
            s2_woke = True

        task = asyncio.create_task(waiter_s2())
        await asyncio.sleep(0.05)

        q.set_cancelled("s1", False)  # resume s1 only
        await asyncio.sleep(0.05)
        assert s2_woke is False  # s2 still blocked

        q.set_cancelled("s2", False)  # now resume s2
        await asyncio.sleep(0.05)
        assert s2_woke is True
        await task

    @pytest.mark.asyncio
    async def test_wait_for_resume_unknown_session_returns_immediately(self):
        q = PriorityMessageQueue()
        # Should not block for a session that was never cancelled
        await asyncio.wait_for(q.wait_for_resume("never_cancelled"), timeout=0.1)
