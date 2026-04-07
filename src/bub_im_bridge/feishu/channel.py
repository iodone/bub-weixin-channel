"""Feishu (Lark) channel – WebSocket long-connection adapter for the Bub framework."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)
from loguru import logger

from bub.channels.base import Channel
from bub.channels.message import ChannelMessage
from bub.types import MessageHandler

from bub_im_bridge.feishu.feishu_prompts import FEISHU_OUTPUT_INSTRUCTION

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_collection(raw: str) -> set[str]:
    """Parse a comma-separated string **or** a JSON array into a ``set``."""
    if not raw:
        return set()
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return {str(item).strip() for item in parsed if str(item).strip()}
    return {item.strip() for item in raw.split(",") if item.strip()}


def _normalize_text(message_type: str, content: str) -> str:
    """Extract human-readable text from the raw Feishu message content JSON."""
    if not content:
        return ""

    parsed: dict[str, Any] | None = None
    with contextlib.suppress(json.JSONDecodeError):
        obj = json.loads(content)
        if isinstance(obj, dict):
            parsed = obj

    if message_type == "text":
        return str(parsed.get("text", "")).strip() if parsed else content.strip()
    if parsed is None:
        return f"[{message_type} message]"
    return f"[{message_type} message] {json.dumps(parsed, ensure_ascii=False)}"


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

    def __init__(self, on_receive: MessageHandler) -> None:
        self._on_receive = on_receive

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

        # Runtime state
        self._api_client: lark.Client | None = None
        self._ws_client: lark.ws.Client | None = None
        self._ws_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Track last inbound message_id per chat so ``send`` can reply.
        # (The bub framework does not forward ``context`` to outbound messages.)
        self._last_message_id: dict[str, str] = {}

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
        logger.info("feishu.start listening")

    async def stop(self) -> None:
        logger.info("feishu.stop")
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

    # -- inbound pipeline ----------------------------------------------------

    def _on_ws_event(self, data: Any) -> None:
        """SDK callback – runs in the WebSocket thread."""
        try:
            payload = _event_to_dict(data)
            message = _parse_event(payload)
            if message is None:
                return

            if message.is_group:
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

            future = asyncio.run_coroutine_threadsafe(
                self._dispatch(message), self._loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                logger.exception("feishu.dispatch error")

        except Exception:
            logger.exception("feishu._on_ws_event error")

    def _should_skip(self, message: FeishuInboundMessage) -> str | None:
        """Return a reason string if the message should be silently skipped, else ``None``."""
        if self._allow_chats and message.chat_id not in self._allow_chats:
            return "chat_not_allowed"

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
        """
        if message.chat_type == "p2p":
            return True, "p2p"

        text = message.text.strip()

        if text.startswith(",") or text.startswith("/"):
            return True, "command"
        if "bub" in text.lower():
            return True, "bub_keyword"

        # Exact bot open_id match
        if self._bot_open_id and any(
            m.open_id == self._bot_open_id for m in message.mentions
        ):
            return True, "bot_mentioned"

        # Mention whose display-name contains "bub"
        if any("bub" in (m.name or "").lower() for m in message.mentions):
            return True, "bub_name_mentioned"

        # Any @-mention in a group chat (permissive fallback)
        if message.mentions:
            return True, "has_mentions"

        return False, "no_mention_in_group"

    async def _dispatch(self, message: FeishuInboundMessage) -> None:
        """Build a :class:`ChannelMessage` and hand it to the framework."""
        session_id = f"feishu:{message.chat_id}"

        # Remember for reply
        self._last_message_id[message.chat_id] = message.message_id

        text = message.text.strip()

        # Normalize slash commands to comma commands: /tape.handoff -> ,tape.handoff
        if text.startswith("/"):
            text = "," + text[1:]

        if text.startswith(","):
            await self._on_receive(
                ChannelMessage(
                    session_id=session_id,
                    content=text,
                    channel=self.name,
                    chat_id=message.chat_id,
                    kind="command",
                    is_active=True,
                )
            )
            return

        payload = {
            "message": message.text + FEISHU_OUTPUT_INSTRUCTION,
            "message_id": message.message_id,
            "chat_type": message.chat_type,
            "sender_id": message.sender_open_id or "",
            "sender_name": message.sender_display,
            "create_time": _format_feishu_timestamp(message.create_time),
        }
        local_time = _format_feishu_timestamp(message.create_time)
        await self._on_receive(
            ChannelMessage(
                session_id=session_id,
                channel=self.name,
                chat_id=message.chat_id,
                content=json.dumps(payload, ensure_ascii=False),
                is_active=True,
                context={"date": local_time} if local_time else {},
            )
        )

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

        msg_type, content_json = _build_outbound_content(text)

        reply_to = self._last_message_id.get(chat_id)
        if reply_to:
            self._reply_message(reply_to, msg_type, content_json)
        else:
            logger.warning(
                "feishu.send no message_id to reply, sending as new message chat_id={}",
                chat_id,
            )
            self._create_message(chat_id, msg_type, content_json)

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
        sender_name=sid_obj.get("user_id", ""),
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


import re


def _format_feishu_timestamp(ts: str | None) -> str:
    """Convert Feishu millisecond timestamp to local time string."""
    if not ts:
        return ""
    try:
        epoch_ms = int(ts)
        dt = datetime.fromtimestamp(epoch_ms / 1000).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return ts or ""


# Patterns that indicate rich content needing card rendering
_RICH_CONTENT_RE = re.compile(
    r"[#|*~`>\-]"  # headings, tables, bold, strikethrough, code, quote, list, hr
    r"|<font\b"  # colored text
)


def _needs_card(text: str) -> bool:
    """Return True if text contains markdown formatting that needs card rendering."""
    return bool(_RICH_CONTENT_RE.search(text))


def _build_outbound_content(text: str) -> tuple[str, str]:
    """Build ``(msg_type, content_json)`` for a Feishu outbound message.

    Simple plain text → ``text`` message (like a normal human reply).
    Rich content (markdown formatting) → Card JSON 2.0 ``interactive`` message.
    """
    if not _needs_card(text):
        return "text", json.dumps({"text": text}, ensure_ascii=False)

    card: dict[str, Any] = {
        "schema": "2.0",
        "body": {"elements": [{"tag": "markdown", "content": text}]},
    }
    return "interactive", json.dumps(card, ensure_ascii=False)
