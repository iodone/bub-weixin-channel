"""Feishu (Lark) channel implementation for Bub framework."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
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


def _normalize_text(message_type: str, content: str) -> str:
    """Normalize message content to text."""
    if not content:
        return ""
    parsed: dict[str, Any] | None = None
    with contextlib.suppress(json.JSONDecodeError):
        maybe_dict = json.loads(content)
        if isinstance(maybe_dict, dict):
            parsed = maybe_dict

    if message_type == "text":
        if parsed is not None:
            return str(parsed.get("text", "")).strip()
        return content.strip()
    if parsed is None:
        return f"[{message_type} message]"
    return f"[{message_type} message] {json.dumps(parsed, ensure_ascii=False)}"


class FeishuChannel(Channel):
    """Feishu channel using lark_oapi SDK with WebSocket long connection."""

    name: ClassVar[str] = "feishu"

    def __init__(self, on_receive: MessageHandler) -> None:
        self._on_receive = on_receive
        self._app_id = _get_env("BUB_FEISHU_APP_ID")
        self._app_secret = _get_env("BUB_FEISHU_APP_SECRET")
        self._verification_token = _get_env("BUB_FEISHU_VERIFICATION_TOKEN")
        self._encrypt_key = _get_env("BUB_FEISHU_ENCRYPT_KEY")
        self._allow_users = _parse_collection(_get_env("BUB_FEISHU_ALLOW_USERS"))
        self._allow_chats = _parse_collection(_get_env("BUB_FEISHU_ALLOW_CHATS"))
        self._bot_open_id = _get_env("BUB_FEISHU_BOT_OPEN_ID")
        self._api_client: Any | None = None
        self._ws_client: Any | None = None
        self._ws_thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    @property
    def needs_debounce(self) -> bool:
        return True

    async def start(self, stop_event: asyncio.Event) -> None:
        if not self._app_id or not self._app_secret:
            raise RuntimeError(
                "feishu: BUB_FEISHU_APP_ID or BUB_FEISHU_APP_SECRET not set"
            )

        self._stop_event = stop_event
        self._main_loop = asyncio.get_running_loop()

        logger.info(
            "feishu.start app_id={} allow_users={} allow_chats={} bot_open_id={}",
            self._app_id[:8] + "...",
            len(self._allow_users),
            len(self._allow_chats),
            self._bot_open_id or "(not set)",
        )

        # API client
        self._api_client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # Event handler
        event_handler = (
            lark.EventDispatcherHandler.builder(
                self._verification_token,
                self._encrypt_key,
            )
            .register_p2_im_message_receive_v1(self._on_message_event)
            .build()
        )

        # WebSocket client
        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        # Start WebSocket in daemon thread
        self._ws_thread = threading.Thread(
            target=self._run_ws_client,
            name="feishu-ws",
            daemon=True,
        )
        self._ws_thread.start()

        logger.info("feishu.start listening")

        # Wait for stop event
        await self._stop_event.wait()

    async def stop(self) -> None:
        logger.info("feishu.stop stopping")
        if self._ws_client is not None:
            for method_name in ("stop", "close"):
                method = getattr(self._ws_client, method_name, None)
                if callable(method):
                    with contextlib.suppress(Exception):
                        method()
                    break
            self._ws_client = None

    def _run_ws_client(self) -> None:
        if self._ws_client is None:
            return
        try:
            logger.info("feishu.ws starting")
            self._ws_client.start()
        except RuntimeError as e:
            logger.error(f"feishu.ws.runtime_error: {e}")
        except Exception as e:
            logger.error(f"feishu.ws.error: {e}")

    def _on_message_event(self, data: Any) -> None:
        """Handle incoming message event from WebSocket."""
        try:
            # Convert to dict for easier access
            payload = self._to_payload_dict(data)

            # Log event type
            event_type = payload.get("header", {}).get("event_type", "unknown")
            logger.debug(f"feishu.event received: {event_type}")

            # Normalize event
            message = self._normalize_event(payload)
            if message is None:
                return

            chat_type = message["chat_type"]

            # Log incoming message (only for group chats)
            if chat_type != "p2p":
                logger.info(
                    "feishu.incoming chat_type={} chat_id={} sender={} mentions={} text={}",
                    chat_type,
                    message["chat_id"],
                    message["sender_open_id"],
                    len(message["mentions"]),
                    message["text"][:50] if message["text"] else "",
                )

            # Check permissions
            if not self._is_allowed(message):
                return

            if not message["text"].strip():
                return

            # Check if should be active
            is_active = self._is_active(message)

            if not is_active:
                logger.debug(
                    "feishu.inactive chat_type={} text={} mentions={}",
                    chat_type,
                    message["text"][:50],
                    message["mentions"],
                )
                return

            # Build and send message
            if self._main_loop is None:
                logger.warning("feishu.inbound no main loop")
                return

            logger.debug("feishu.active dispatching message")
            future = asyncio.run_coroutine_threadsafe(
                self._dispatch_message(message), self._main_loop
            )
            # Wait for result to ensure message is processed
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.error(f"feishu.dispatch error: {e}")

        except Exception as e:
            logger.exception(f"feishu._on_message_event error: {e}")

    async def _dispatch_message(self, message: dict[str, Any]) -> None:
        """Build and dispatch the message to bub framework."""
        session_id = f"feishu:{message['chat_id']}"

        # Command message (starts with ,)
        if message["text"].strip().startswith(","):
            inbound = ChannelMessage(
                session_id=session_id,
                content=message["text"].strip(),
                channel=self.name,
                chat_id=message["chat_id"],
                is_active=True,
            )
            await self._on_receive(inbound)
            return

        # Regular message
        inbound = ChannelMessage(
            session_id=session_id,
            channel=self.name,
            chat_id=message["chat_id"],
            content=json.dumps(
                {
                    "message": message["text"],
                    "message_id": message["message_id"],
                    "chat_type": message["chat_type"],
                    "sender_id": message["sender_open_id"] or "",
                },
                ensure_ascii=False,
            ),
            is_active=True,
            context={"feishu_root_id": message.get("root_id") or message["message_id"]},
        )
        await self._on_receive(inbound)

    def _is_allowed(self, message: dict[str, Any]) -> bool:
        """Check if message is allowed based on user/chat filters."""
        if self._allow_chats and message["chat_id"] not in self._allow_chats:
            return False

        if self._allow_users:
            sender_tokens = {
                token
                for token in (
                    message.get("sender_id"),
                    message.get("sender_open_id"),
                    message.get("sender_union_id"),
                    message.get("sender_user_id"),
                )
                if token
            }
            if sender_tokens.isdisjoint(self._allow_users):
                return False

        return True

    def _is_active(self, message: dict[str, Any]) -> bool:
        """Determine if message should be processed (is_active)."""
        chat_type = message["chat_type"]
        text = message["text"].strip()
        mentions = message["mentions"]
        parent_id = message.get("parent_id")

        # Private chat: always active
        if chat_type == "p2p":
            return True

        # Text starts with "," (command)
        if text.startswith(","):
            return True

        # Contains "bub" keyword
        if "bub" in text.lower():
            return True

        # Mentions bot (by open_id)
        if self._bot_open_id:
            for m in mentions:
                if m.get("open_id") == self._bot_open_id:
                    return True

        # Mentions someone named "bub"
        for m in mentions:
            name = (m.get("name") or "").lower()
            if "bub" in name:
                return True

        # Any mention in group chat (more permissive)
        if mentions:
            return True

        return False

    def _to_payload_dict(self, data: Any) -> dict[str, Any]:
        """Convert event data to dict."""
        if isinstance(data, dict):
            return data
        try:
            raw = lark.JSON.marshal(data)
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass
        value = getattr(data, "__dict__", None)
        if isinstance(value, dict):
            return value
        return {}

    def _normalize_event(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize event payload to a standard format."""
        event = payload.get("event")
        if not isinstance(event, dict):
            return None

        message = event.get("message")
        sender = event.get("sender")
        if not isinstance(message, dict) or not isinstance(sender, dict):
            return None

        # Parse sender
        sender_id = sender.get("sender_id")
        sender_id_obj = sender_id if isinstance(sender_id, dict) else {}

        # Parse mentions
        mentions: list[dict[str, Any]] = []
        raw_mentions = message.get("mentions")
        if isinstance(raw_mentions, list):
            for raw in raw_mentions:
                if not isinstance(raw, dict):
                    continue
                mention_id = raw.get("id")
                mention_id_obj = mention_id if isinstance(mention_id, dict) else {}
                mentions.append(
                    {
                        "open_id": mention_id_obj.get("open_id"),
                        "name": raw.get("name"),
                        "key": raw.get("key"),
                    }
                )

        # Normalize content
        message_type = str(message.get("message_type") or "unknown")
        raw_content = str(message.get("content") or "")
        text = _normalize_text(message_type, raw_content)

        result = {
            "message_id": str(message.get("message_id") or ""),
            "chat_id": str(message.get("chat_id") or ""),
            "chat_type": str(message.get("chat_type") or ""),
            "message_type": message_type,
            "raw_content": raw_content,
            "text": text,
            "mentions": mentions,
            "parent_id": message.get("parent_id"),
            "root_id": message.get("root_id"),
            "sender_id": sender_id_obj.get("open_id")
            or sender_id_obj.get("union_id")
            or sender_id_obj.get("user_id"),
            "sender_open_id": sender_id_obj.get("open_id"),
            "sender_union_id": sender_id_obj.get("union_id"),
            "sender_user_id": sender_id_obj.get("user_id"),
            "sender_type": sender.get("sender_type"),
            "tenant_key": sender.get("tenant_key"),
            "create_time": message.get("create_time"),
            "event_type": (payload.get("header") or {}).get("event_type"),
        }

        if not result["chat_id"] or not result["message_id"]:
            return None

        return result

    async def send(self, message: ChannelMessage) -> None:
        if not self._api_client:
            return

        chat_id = message.chat_id
        if not chat_id:
            return

        try:
            data = json.loads(message.content) if message.content else {}
            text = data.get("message", "") if data else ""
        except (json.JSONDecodeError, AttributeError):
            text = message.content or ""

        if not text.strip():
            return

        root_id = message.context.get("feishu_root_id", "")

        # Use post message type for markdown rendering
        content_json = json.dumps(
            {
                "zh_cn": {
                    "title": "",
                    "content": [[{"tag": "md", "text": text}]],
                }
            },
            ensure_ascii=False,
        )

        if root_id:
            req = (
                ReplyMessageRequest.builder()
                .message_id(root_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .content(content_json)
                    .msg_type("post")
                    .build()
                )
                .build()
            )
            resp = self._api_client.im.v1.message.reply(req)
        else:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("post")
                    .content(content_json)
                    .build()
                )
                .build()
            )
            resp = self._api_client.im.v1.message.create(req)

        if not resp.success():
            logger.error(f"feishu.send failed: code={resp.code} msg={resp.msg}")


def _get_env(key: str) -> str:
    """Get environment variable with empty string default."""
    import os

    return os.environ.get(key, "")


def _parse_collection(value: str) -> set[str]:
    """Parse comma-separated or JSON array string to set."""
    if not value:
        return set()
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return {str(item).strip() for item in parsed if str(item).strip()}
    return {item.strip() for item in value.split(",") if item.strip()}
