"""Feishu (Lark) channel – WebSocket long-connection adapter for the Bub framework."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)
from loguru import logger

from bub.channels.base import Channel
from bub.channels.message import ChannelMessage
from bub.framework import BubFramework
from bub.types import MessageHandler

from bub_im_bridge.feishu.api import (
    fetch_message_content,
    format_feishu_timestamp,
    _normalize_text,
)
from bub_im_bridge.profiles import ProfileStore
from bub_im_bridge.feishu.feishu_prompts import (
    FEISHU_HISTORY_HINT_GROUP,
    FEISHU_HISTORY_HINT_P2P,
    FEISHU_OUTPUT_INSTRUCTION,
    build_user_context_hint,
)
from bub_im_bridge.queue import (
    PriorityMessageQueue,
    get_queue_max_length,
    is_admin_sender,
    _parse_collection,
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeishuMention:
    """A single @-mention inside a Feishu message."""

    open_id: str | None
    name: str | None
    key: str | None


@dataclass(frozen=True)
class FeishuInboundMessage:
    """Normalized representation of an incoming Feishu message event."""

    message_id: str
    chat_id: str
    chat_type: str  # "p2p" | "group" | "topic"
    message_type: str
    text: str
    mentions: tuple[FeishuMention, ...] = ()
    parent_id: str | None = None
    root_id: str | None = None

    sender_open_id: str | None = None
    sender_union_id: str | None = None
    sender_user_id: str | None = None
    sender_name: str = ""
    sender_type: str | None = None  # "user" | "bot"
    tenant_key: str | None = None
    create_time: str | None = None

    @property
    def sender_display(self) -> str:
        return self.sender_name or self.sender_open_id or "unknown"

    @property
    def is_group(self) -> bool:
        return self.chat_type in ("group", "topic")


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


class FeishuChannel(Channel):
    """Feishu channel using *lark_oapi* SDK with WebSocket long connection."""

    name: ClassVar[str] = "feishu"

    # -- lifecycle -----------------------------------------------------------

    def __init__(
        self, on_receive: MessageHandler, *, framework: BubFramework | None = None
    ) -> None:
        self._framework = framework
        self._framework_on_receive = on_receive  # Original framework handler

        # Priority queue for ALL non-admin-DM messages
        self._queue = PriorityMessageQueue(max_length=get_queue_max_length())
        self._queue_worker_task: asyncio.Task | None = None

        # Config – read once at init
        self._app_id = os.environ.get("BUB_FEISHU_APP_ID", "")
        self._app_secret = os.environ.get("BUB_FEISHU_APP_SECRET", "")
        self._verification_token = os.environ.get("BUB_FEISHU_VERIFICATION_TOKEN", "")
        self._encrypt_key = os.environ.get("BUB_FEISHU_ENCRYPT_KEY", "")
        self._allow_users = _parse_collection(
            os.environ.get("BUB_FEISHU_ALLOW_USERS", "")
        )
        self._allow_chats = _parse_collection(
            os.environ.get("BUB_FEISHU_ALLOW_CHATS", "")
        )
        self._bot_open_id = os.environ.get("BUB_FEISHU_BOT_OPEN_ID", "")
        self._bot_name = os.environ.get("BUB_FEISHU_BOT_NAME", "").lower()

        # Runtime state
        self._api_client: lark.Client | None = None
        self._ws_client: lark.ws.Client | None = None
        self._ws_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Track last inbound message_id per chat so ``send`` can reply.
        # (The bub framework does not forward ``context`` to outbound messages.)
        self._last_message_id: dict[str, str] = {}
        
        # Track message start time for elapsed time calculation
        self._message_start_time: dict[str, float] = {}

        # User profile store
        workspace = os.environ.get("BUB_WORKSPACE", os.getcwd())
        self._profile_store = ProfileStore(Path(workspace) / "profiles")
        self._profile_store.load()

    @property
    def needs_debounce(self) -> bool:
        return True

    async def start(self, stop_event: asyncio.Event) -> None:
        if not self._app_id or not self._app_secret:
            raise RuntimeError(
                "feishu: BUB_FEISHU_APP_ID or BUB_FEISHU_APP_SECRET not set"
            )

        self._loop = asyncio.get_running_loop()

        logger.info(
            "feishu.start app_id={}... allow_users={} allow_chats={} bot_open_id={}",
            self._app_id[:8],
            len(self._allow_users),
            len(self._allow_chats),
            self._bot_open_id or "(not set)",
        )

        self._api_client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

        event_handler = (
            lark.EventDispatcherHandler.builder(
                self._verification_token,
                self._encrypt_key,
            )
            .register_p2_im_message_receive_v1(self._on_ws_event)
            .build()
        )

        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
        )

        self._ws_thread = threading.Thread(
            target=self._run_ws, name="feishu-ws", daemon=True
        )
        self._ws_thread.start()

        self._queue_worker_task = asyncio.create_task(self._queue_worker())
        logger.info(
            "feishu.start listening queue_max_length={}",
            self._queue.max_length,
        )

    async def stop(self) -> None:
        logger.info("feishu.stop")
        # Stop queue worker
        if self._queue_worker_task is not None:
            self._queue_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_worker_task
            self._queue_worker_task = None
        self._queue.drain()

        client = self._ws_client
        if client is not None:
            for name in ("stop", "close"):
                fn = getattr(client, name, None)
                if callable(fn):
                    with contextlib.suppress(Exception):
                        fn()
                    break
            self._ws_client = None

    # -- WebSocket thread ----------------------------------------------------

    def _run_ws(self) -> None:
        """Blocking call executed in a daemon thread."""
        if self._ws_client is None:
            return
        try:
            self._ws_client.start()
        except Exception:
            logger.exception("feishu.ws unexpected error")

    # -- queue worker -----------------------------------------------------------

    async def _queue_worker(self) -> None:
        """Pull messages from the priority queue and forward to framework.

        Messages are forwarded to ``ChannelManager.on_receive`` which routes them
        through the native ``BufferedMessageHandler`` (debounce + merge).
        """
        while True:
            try:
                message = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._framework_on_receive(message)
            except Exception:
                logger.exception(
                    "feishu.queue_worker error session_id={}", message.session_id
                )

    def _get_channel_manager(self) -> Any | None:
        """Access the framework's ``ChannelManager`` via internals.

        Returns ``None`` if framework is not bound or attributes changed.
        Callers must handle the ``None`` case gracefully.
        """
        if self._framework is None:
            return None
        return getattr(self._framework, "_outbound_router", None)

    def _get_framework_queue(self) -> asyncio.Queue | None:
        """Access ``ChannelManager._messages`` for direct enqueue (bypass debounce)."""
        mgr = self._get_channel_manager()
        if mgr is None:
            return None
        q = getattr(mgr, "_messages", None)
        return q if isinstance(q, asyncio.Queue) else None

    def _framework_running_sessions(self) -> set[str]:
        """Return session IDs that have in-flight framework tasks."""
        mgr = self._get_channel_manager()
        if mgr is None:
            return set()
        ongoing = getattr(mgr, "_ongoing_tasks", {})
        return {sid for sid, tasks in ongoing.items() if tasks}

    # -- inbound pipeline ----------------------------------------------------

    def _on_ws_event(self, data: Any) -> None:
        """SDK callback – runs in the WebSocket thread."""
        try:
            payload = _event_to_dict(data)
            message = _parse_event(payload)
            if message is None:
                return

            logger.info(
                "feishu.incoming chat_type={} chat_id={} sender={}({}) mentions={} text={}",
                message.chat_type,
                message.chat_id,
                message.sender_display,
                message.sender_open_id,
                len(message.mentions),
                message.text[:80],
            )

            skip_reason = self._should_skip(message)
            if skip_reason:
                logger.info(
                    "feishu.skip chat_type={} sender={}({}) reason={}",
                    message.chat_type,
                    message.sender_display,
                    message.sender_open_id,
                    skip_reason,
                )
                return

            is_active, active_reason = self._check_active(message)
            if not is_active:
                logger.info(
                    "feishu.inactive chat_type={} sender={} text={} reason={}",
                    message.chat_type,
                    message.sender_display,
                    message.text[:80],
                    active_reason,
                )
                return

            if self._loop is None:
                logger.warning("feishu: event loop not available")
                return

            # Fire-and-forget: don't block the WebSocket thread
            asyncio.run_coroutine_threadsafe(self._dispatch(message), self._loop)

        except Exception:
            logger.exception("feishu._on_ws_event error")

    def _should_skip(self, message: FeishuInboundMessage) -> str | None:
        """Return a reason string if the message should be silently skipped, else ``None``."""
        # For group chats (chat_id starts with "oc_"), check allow_chats
        # For p2p chats (chat_id is user's open_id), check allow_users
        is_group_chat = message.chat_id.startswith("oc_")
        
        if is_group_chat:
            # Group chat: check allow_chats restriction
            if self._allow_chats and message.chat_id not in self._allow_chats:
                return "chat_not_allowed"
        else:
            # P2P chat: check allow_users restriction
            if self._allow_users:
                sender_ids = {
                    t
                    for t in (
                        message.sender_open_id,
                        message.sender_union_id,
                        message.sender_user_id,
                    )
                    if t
                }
                if sender_ids.isdisjoint(self._allow_users):
                    return "user_not_allowed"

        if not message.text.strip():
            return "empty_text"

        return None

    def _check_active(self, message: FeishuInboundMessage) -> tuple[bool, str]:
        """Decide whether the message should trigger the bot.

        Returns ``(is_active, reason)`` – *reason* is always populated for logging.

        For p2p (single chat): always active.
        For group chat: only active if @mentioned.
        Quoted messages (parent_id) provide context but do not activate on their own.
        """
        if message.chat_type == "p2p":
            return True, "p2p"

        # Group chat: check for @mentions or quoted message
        text = message.text.strip()

        # Commands always trigger
        if text.startswith(",") or text.startswith("/"):
            return True, "command"

        # Exact bot open_id match (with or without quoted message)
        if self._bot_open_id and any(
            m.open_id == self._bot_open_id for m in message.mentions
        ):
            return True, "bot_mentioned"

        # Mention whose display-name matches configured bot name
        if self._bot_name and any(
            self._bot_name in (m.name or "").lower() for m in message.mentions
        ):
            return True, "bot_name_mentioned"

        if message.mentions:
            return False, "has_mentions_but_not_me"

        return False, "no_mention_in_group"

    async def _dispatch(self, message: FeishuInboundMessage) -> None:
        """Build a :class:`ChannelMessage` and route based on admin status."""
        session_id = f"feishu:{message.chat_id}"
        sender_id = message.sender_open_id or ""

        # Ensure user profile exists
        if sender_id and message.sender_type != "bot":
            profile = self._profile_store.lookup("feishu", "open_id", sender_id)
            if profile is not None:
                self._profile_store.touch(profile.id)
            else:
                extra_ids: dict[str, str] = {}
                if message.sender_union_id:
                    extra_ids["union_id"] = message.sender_union_id
                if message.sender_user_id:
                    extra_ids["user_id"] = message.sender_user_id

                info = {"name": message.sender_name or sender_id}
                if self._api_client is not None:
                    from bub_im_bridge.feishu.api import fetch_user_info
                    info = fetch_user_info(self._api_client, sender_id)

                self._profile_store.upsert(
                    platform="feishu",
                    id_field="open_id",
                    id_value=sender_id,
                    name=info.get("name", sender_id),
                    extra_ids=extra_ids,
                    department=info.get("department_id", ""),
                    title=info.get("job_title", ""),
                    avatar_url=info.get("avatar_url", ""),
                )

        # Remember for reply
        self._last_message_id[message.chat_id] = message.message_id
        
        # Send random reaction to acknowledge message received
        self._add_random_reaction(message.message_id)
        
        # Record start time for elapsed time calculation
        self._message_start_time[message.message_id] = time.time()

        text = message.text.strip()

        # Normalize slash commands to comma commands: /tape.handoff -> ,tape.handoff
        if text.startswith("/"):
            text = "," + text[1:]

        # Check if sender is admin
        is_admin = is_admin_sender(sender_id)

        # Intercept ,cancel command (global clear for admin only)
        if is_admin and text == ",cancel":
            await self._handle_cancel(message)
            return

        # Build the channel message
        channel_msg = await self._build_channel_message(
            message, text, sender_id, session_id
        )

        # Admin → bypass queue + debounce, execute immediately
        if is_admin:
            logger.info(
                "feishu.dispatch admin immediate session_id={} content={}",
                session_id,
                channel_msg.content,
            )
            fq = self._get_framework_queue()
            if fq is not None:
                await fq.put(channel_msg)
            else:
                await self._framework_on_receive(channel_msg)  # fallback (debounced)
            return

        # Normal flow: enqueue message with priority
        enqueued = await self._queue.put(channel_msg)
        if enqueued:
            logger.info(
                "feishu.dispatch enqueued session_id={} queue_size={} content={}",
                session_id,
                self._queue.size,
                channel_msg.content[:80],
            )
        else:
            logger.warning(
                "feishu.dispatch dropped (queue full) session_id={} content={}",
                session_id,
                channel_msg.content[:80],
            )
            self._send_queue_full_notification(message)

    async def _build_channel_message(
        self, message: FeishuInboundMessage, text: str, sender_id: str, session_id: str
    ) -> ChannelMessage:
        """Build a ChannelMessage from FeishuInboundMessage."""
        if text.startswith(","):
            return ChannelMessage(
                session_id=session_id,
                content=text,
                channel=self.name,
                chat_id=message.chat_id,
                kind="command",
                is_active=True,
                context={"sender_id": sender_id},
            )

        # Fetch quoted message content if this is a reply
        quoted_message = None
        if message.parent_id and self._api_client is not None:
            quoted_message = await fetch_message_content(
                self._api_client, message.parent_id
            )
            if not quoted_message:
                logger.warning(
                    "feishu.dispatch quoted message fetch returned empty parent_id={}",
                    message.parent_id,
                )

        history_hint = (
            FEISHU_HISTORY_HINT_GROUP if message.is_group else FEISHU_HISTORY_HINT_P2P
        )

        # Inject sender profile context
        sender_profile = self._profile_store.lookup("feishu", "open_id", sender_id) if sender_id else None
        user_context_hint = build_user_context_hint(sender_profile)

        payload: dict[str, Any] = {
            "message": message.text + FEISHU_OUTPUT_INSTRUCTION + history_hint + user_context_hint,
            "message_id": message.message_id,
            "chat_type": message.chat_type,
            "sender_id": sender_id,
            "sender_name": message.sender_display,
            "create_time": format_feishu_timestamp(message.create_time),
        }

        if quoted_message:
            payload["quoted_message"] = quoted_message

        local_time = format_feishu_timestamp(message.create_time)

        # Inject API client and profile store into context for tool access
        context: dict[str, Any] = {"sender_id": sender_id}
        if local_time:
            context["date"] = local_time
        if self._api_client is not None:
            context["_feishu_api_client"] = self._api_client
        context["_profile_store"] = self._profile_store

        return ChannelMessage(
            session_id=session_id,
            channel=self.name,
            chat_id=message.chat_id,
            content=json.dumps(payload, ensure_ascii=False),
            is_active=True,
            context=context,
        )

    def _send_queue_full_notification(self, message: FeishuInboundMessage) -> None:
        """Reply directly to the dropped message without touching ``_last_message_id``."""
        self._reply_message(
            message.message_id,
            "text",
            json.dumps(
                {"text": "当前排队已满，消息已被丢弃。请稍后再试。"}, ensure_ascii=False
            ),
        )

    # -- admin cancel / resume ------------------------------------------------

    async def _handle_cancel(self, message: FeishuInboundMessage) -> None:
        """Global cancel: drain ALL queued messages, cancel ALL running tasks,
        and pause ALL affected sessions.

        Replies to each cancelled message individually so users get notified.
        """
        drained = self._queue.drain()

        affected_sessions = set(msg.session_id for msg in drained)
        running_sessions = self._framework_running_sessions()
        affected_sessions.update(running_sessions)

        for sid in affected_sessions:
            if self._framework is not None:
                await self._framework.quit_via_router(sid)

        # Notify each cancelled message's sender
        for msg in drained:
            mid = self._extract_message_id(msg)
            if mid:
                self._reply_message(
                    mid,
                    "text",
                    json.dumps({"text": "此消息已被管理员取消。"}, ensure_ascii=False),
                )

        logger.info(
            "feishu.cancel sender={} drained={} sessions={}",
            message.sender_display,
            len(drained),
            len(affected_sessions),
        )

        # Confirm to admin
        session_id = f"feishu:{message.chat_id}"
        self._last_message_id[message.chat_id] = message.message_id
        await self.send(
            ChannelMessage(
                session_id=session_id,
                channel=self.name,
                chat_id=message.chat_id,
                content=f"已全局取消 {len(drained)} 条排队消息，影响 {len(affected_sessions)} 个会话。",
                is_active=True,
            )
        )

    @staticmethod
    def _extract_message_id(msg: ChannelMessage) -> str | None:
        """Extract feishu message_id from a ChannelMessage's content JSON."""
        try:
            data = json.loads(msg.content)
            if isinstance(data, dict):
                mid = data.get("message_id")
                return mid if isinstance(mid, str) and mid else None
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    # -- outbound ------------------------------------------------------------

    async def send(self, message: ChannelMessage) -> None:
        if self._api_client is None:
            return

        chat_id = message.chat_id
        if not chat_id:
            return

        text = _extract_outbound_text(message)
        if not text:
            return

        # Calculate elapsed time if we have start time
        reply_to = self._last_message_id.get(chat_id)
        elapsed_seconds = None
        if reply_to and reply_to in self._message_start_time:
            start_time = self._message_start_time[reply_to]
            elapsed_seconds = time.time() - start_time
            # Clean up start time record
            del self._message_start_time[reply_to]

        msg_type, content_json = _build_outbound_content(text, elapsed_seconds)

        if reply_to:
            self._reply_message(reply_to, msg_type, content_json)
        else:
            logger.warning(
                "feishu.send no message_id to reply, sending as new message chat_id={}",
                chat_id,
            )
            self._create_message(chat_id, msg_type, content_json)

    def _add_random_reaction(self, message_id: str) -> None:
        """Add a random emoji reaction to acknowledge message received.
        
        Uses Feishu's built-in emoji types to provide varied visual feedback.
        Reference: https://open.feishu.cn/document/server-docs/im-v1/message-reaction/emojis-introduce
        """
        if self._api_client is None:
            return
        
        # Carefully selected emojis that indicate "message received" or "processing"
        # 精选的表情，表示"已收到消息"或"正在处理"
        acknowledgment_emojis = [
            "OK",              # 👌 OK
            "THUMBSUP",        # 👍 点赞
            "DONE",            # ✅ 完成
            "Get",             # 🉐 Get到了
            "SALUTE",          # 🫡 敬礼
            "LGTM",            # 👍 LGTM (Looks Good To Me)
            "OnIt",            # 🫡 马上办
            "OneSecond",       # ⏱️ 稍等
            "CheckMark",       # ✔️ 对勾
            "Typing",          # ⌨️ 正在输入
        ]
        
        # Randomly select an emoji
        selected_emoji = random.choice(acknowledgment_emojis)
        
        logger.info("feishu.add_reaction message_id={} emoji_type={}", message_id, selected_emoji)
        
        try:
            req = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(
                        {"emoji_type": selected_emoji}
                    )
                    .build()
                )
                .build()
            )
            resp = self._api_client.im.v1.message_reaction.create(req)
            if not resp.success():
                logger.warning(
                    "feishu.add_reaction failed code={} msg={} message_id={}",
                    resp.code,
                    resp.msg,
                    message_id,
                )
            else:
                logger.info("feishu.add_reaction success message_id={} emoji={}", message_id, selected_emoji)
        except Exception:
            logger.exception("feishu.add_reaction error message_id={}", message_id)

    def _reply_message(self, message_id: str, msg_type: str, content_json: str) -> None:
        assert self._api_client is not None
        logger.info(
            "feishu.reply_message message_id={} msg_type={} content_preview={}",
            message_id,
            msg_type,
            content_json[:200],
        )
        req = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(content_json)
                .msg_type(msg_type)
                .build()
            )
            .build()
        )
        resp = self._api_client.im.v1.message.reply(req)
        if not resp.success():
            logger.error(
                "feishu.reply failed code={} msg={} message_id={}",
                resp.code,
                resp.msg,
                message_id,
            )
        else:
            logger.info("feishu.reply success message_id={}", message_id)

    def _create_message(self, chat_id: str, msg_type: str, content_json: str) -> None:
        assert self._api_client is not None
        logger.info(
            "feishu.create_message chat_id={} msg_type={} content_preview={}",
            chat_id,
            msg_type,
            content_json[:200],
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(content_json)
                .build()
            )
            .build()
        )
        resp = self._api_client.im.v1.message.create(req)
        if not resp.success():
            logger.error(
                "feishu.create failed code={} msg={} chat_id={}",
                resp.code,
                resp.msg,
                chat_id,
            )
        else:
            logger.info("feishu.create success chat_id={}", chat_id)


# ---------------------------------------------------------------------------
# Pure-function event parsing (stateless, easy to test)
# ---------------------------------------------------------------------------


def _event_to_dict(data: Any) -> dict[str, Any]:
    """Convert a *lark_oapi* event object to a plain ``dict``."""
    if isinstance(data, dict):
        return data
    with contextlib.suppress(Exception):
        raw = lark.JSON.marshal(data)
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
    return getattr(data, "__dict__", None) or {}


def _parse_event(payload: dict[str, Any]) -> FeishuInboundMessage | None:
    """Parse a raw event dict into a :class:`FeishuInboundMessage`."""
    event = payload.get("event")
    if not isinstance(event, dict):
        return None

    raw_message = event.get("message")
    raw_sender = event.get("sender")
    if not isinstance(raw_message, dict) or not isinstance(raw_sender, dict):
        return None

    # Sender
    sid = raw_sender.get("sender_id")
    sid_obj: dict[str, Any] = sid if isinstance(sid, dict) else {}

    # Mentions
    mentions: list[FeishuMention] = []
    for raw in raw_message.get("mentions") or []:
        if not isinstance(raw, dict):
            continue
        mid = raw.get("id")
        mid_obj: dict[str, Any] = mid if isinstance(mid, dict) else {}
        mentions.append(
            FeishuMention(
                open_id=mid_obj.get("open_id"),
                name=raw.get("name"),
                key=raw.get("key"),
            )
        )

    # Text
    msg_type = str(raw_message.get("message_type") or "unknown")
    raw_content = str(raw_message.get("content") or "")
    text = _normalize_text(msg_type, raw_content)

    # Replace mention placeholder keys with display names
    for m in mentions:
        if m.key and m.name:
            text = text.replace(m.key, f"@{m.name}")

    message_id = str(raw_message.get("message_id") or "")
    chat_id = str(raw_message.get("chat_id") or "")
    if not message_id or not chat_id:
        return None

    return FeishuInboundMessage(
        message_id=message_id,
        chat_id=chat_id,
        chat_type=str(raw_message.get("chat_type") or ""),
        message_type=msg_type,
        text=text,
        mentions=tuple(mentions),
        parent_id=raw_message.get("parent_id"),
        root_id=raw_message.get("root_id"),
        sender_open_id=sid_obj.get("open_id"),
        sender_union_id=sid_obj.get("union_id"),
        sender_user_id=sid_obj.get("user_id"),
        sender_name=raw_sender.get("name", ""),
        sender_type=raw_sender.get("sender_type"),
        tenant_key=raw_sender.get("tenant_key"),
        create_time=str(raw_message.get("create_time") or ""),
    )


def _extract_outbound_text(message: ChannelMessage) -> str:
    """Best-effort extraction of the text to send from an outbound ``ChannelMessage``."""
    content = message.content
    if not content:
        return ""
    with contextlib.suppress(json.JSONDecodeError, AttributeError):
        data = json.loads(content)
        if isinstance(data, dict):
            text = data.get("message", "")
            if isinstance(text, str) and text.strip():
                return text
    return content.strip() if isinstance(content, str) else ""


# Patterns that indicate rich content needing card rendering
_RICH_CONTENT_RE = re.compile(
    r"[#|*~`>\-]"  # headings, tables, bold, strikethrough, code, quote, list, hr
    r"|<font\b"  # colored text
)


def _needs_card(text: str) -> bool:
    """Return True if text contains markdown formatting that needs card rendering."""
    return bool(_RICH_CONTENT_RE.search(text))


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)


def _extract_card_json(text: str) -> str | None:
    """Try to extract a schema 2.0 card JSON from *text*.

    Handles three cases:
    1. Pure JSON: ``{"schema": "2.0", "body": {...}}``
    2. Code-fenced: ``\\`\\`\\`json\\n{...}\\n\\`\\`\\`\\``
    3. JSON embedded in surrounding text (first ``{`` to last ``}``)
    """
    # Case 1: entire text is JSON
    stripped = text.strip()
    if stripped.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError):
            obj = json.loads(stripped)
            if isinstance(obj, dict) and obj.get("schema") == "2.0" and "body" in obj:
                return stripped

    # Case 2: JSON wrapped in code fences
    m = _CODE_FENCE_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        with contextlib.suppress(json.JSONDecodeError):
            obj = json.loads(candidate)
            if isinstance(obj, dict) and obj.get("schema") == "2.0" and "body" in obj:
                return candidate

    # Case 3: JSON embedded in surrounding text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        with contextlib.suppress(json.JSONDecodeError):
            obj = json.loads(candidate)
            if isinstance(obj, dict) and obj.get("schema") == "2.0" and "body" in obj:
                return candidate

    return None


def _build_outbound_content(text: str, elapsed_seconds: float | None = None) -> tuple[str, str]:
    """Build ``(msg_type, content_json)`` for a Feishu outbound message.

    If *text* is already a valid schema 2.0 card JSON, pass it through as-is.
    Simple plain text → ``text`` message (like a normal human reply).
    Rich content (markdown formatting) → Card JSON 2.0 ``interactive`` message.
    
    If elapsed_seconds is provided, append elapsed time info to the content.
    """
    # Detect complete card JSON produced by LLM (e.g. via feishu-card skill).
    # LLM may wrap the JSON in ```json ... ``` code fences or add surrounding text.
    card_json = _extract_card_json(text)
    if card_json is not None:
        # If elapsed time is provided, add it to the card
        if elapsed_seconds is not None:
            card_json = _add_elapsed_to_card(card_json, elapsed_seconds)
        return "interactive", card_json

    # Check if content needs card rendering (has markdown syntax)
    needs_card = _needs_card(text)
    
    # Build elapsed time element if provided
    elapsed_element = None
    if elapsed_seconds is not None:
        elapsed_text = f"<font color='grey'>⏱️ 耗时: {elapsed_seconds:.2f}秒</font>"
        elapsed_element = {
            "tag": "markdown",
            "content": elapsed_text,
            "text_size": "notation"  # Small font (12px)
        }

    # If no card needed and no elapsed time, return simple text
    if not needs_card and elapsed_element is None:
        return "text", json.dumps({"text": text}, ensure_ascii=False)

    # Build card with main content
    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": text}]
    
    # Add elapsed time to card if provided
    if elapsed_element is not None:
        elements.append({"tag": "hr"})  # Divider
        elements.append(elapsed_element)

    card: dict[str, Any] = {
        "schema": "2.0",
        "body": {"elements": elements},
    }
    return "interactive", json.dumps(card, ensure_ascii=False)


def _add_elapsed_to_card(card_json: str, elapsed_seconds: float) -> str:
    """Add elapsed time info to an existing card JSON.
    
    Adds a small grey text at the bottom of the card body.
    """
    try:
        card = json.loads(card_json)
        if not isinstance(card, dict):
            return card_json
        
        # Ensure body exists
        if "body" not in card:
            card["body"] = {}
        if not isinstance(card["body"], dict):
            return card_json
            
        # Ensure elements array exists
        if "elements" not in card["body"]:
            card["body"]["elements"] = []
        if not isinstance(card["body"]["elements"], list):
            return card_json
        
        # Add horizontal rule (divider)
        card["body"]["elements"].append({
            "tag": "hr"
        })
        
        # Add elapsed time as markdown text with grey color and small font
        elapsed_text = f"<font color='grey'>⏱️ 耗时: {elapsed_seconds:.2f}秒</font>"
        card["body"]["elements"].append({
            "tag": "markdown",
            "content": elapsed_text,
            "text_size": "notation"  # Small font (12px)
        })
        
        return json.dumps(card, ensure_ascii=False)
    except Exception:
        # If anything goes wrong, return original card
        logger.exception("Failed to add elapsed time to card")
        return card_json
