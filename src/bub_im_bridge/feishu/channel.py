"""Feishu (Lark) channel implementation for Bub framework."""

from __future__ import annotations

import asyncio
import json
import os
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
from bub.channels.message import ChannelMessage, MediaItem, MediaType
from bub.types import MessageHandler


_MSG_TYPE_MAP: dict[str, MediaType] = {
    "image": "image",
    "audio": "audio",
    "video": "video",
    "file": "document",
}


class FeishuChannel(Channel):
    """Feishu channel using lark_oapi SDK with WebSocket long connection."""

    name: ClassVar[str] = "feishu"

    def __init__(self, on_receive: MessageHandler) -> None:
        import os

        self._on_receive = on_receive
        self._app_id = os.environ.get("BUB_FEISHU_APP_ID", "")
        self._app_secret = os.environ.get("BUB_FEISHU_APP_SECRET", "")
        self._allow_users = {
            u.strip()
            for u in os.environ.get("BUB_FEISHU_ALLOW_USERS", "").split(",")
            if u.strip()
        }
        self._api_client: lark.Client | None = None
        self._ws_thread: threading.Thread | None = None
        self._last_msg: dict[str, dict[str, str]] = {}

    @property
    def needs_debounce(self) -> bool:
        return True

    async def start(self, stop_event: asyncio.Event) -> None:
        if not self._app_id or not self._app_secret:
            logger.error("feishu: BUB_FEISHU_APP_ID or BUB_FEISHU_APP_SECRET not set")
            return

        logger.info("feishu.start allow_users_count={}", len(self._allow_users))

        # API client for sending
        self._api_client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .build()
        )

        # WebSocket client for receiving (runs in daemon thread)
        encrypt_key = os.environ.get("BUB_FEISHU_ENCRYPT_KEY", "")
        verification_token = os.environ.get("BUB_FEISHU_VERIFICATION_TOKEN", "")
        handler = (
            lark.EventDispatcherHandler.builder(encrypt_key, verification_token)
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )
        ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )

        def run_ws():
            try:
                ws_client.start()
            except Exception:
                pass

        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("feishu.start listening")

    async def stop(self) -> None:
        logger.info("feishu.stop stopping")

    def _on_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        try:
            msg = data.event.message
            sender = data.event.sender
            if not msg or not sender:
                return

            sender_id = sender.sender_id or {}
            open_id = getattr(sender_id, "open_id", None) or sender_id.get(
                "open_id", ""
            )

            if self._allow_users and open_id not in self._allow_users:
                return

            chat_type = msg.chat_type or "p2p"
            chat_id = msg.chat_id or open_id

            # Group: skip if bot not mentioned
            if chat_type in ("group", "topic"):
                mentions = msg.mentions or []
                if not any(getattr(m, "is_bot", False) for m in mentions):
                    return

            # Parse content
            msg_type = msg.message_type or "text"
            try:
                content = json.loads(msg.content or "{}")
            except json.JSONDecodeError:
                content = {"text": msg.content}

            text = ""
            media: list[MediaItem] = []
            if msg_type == "text":
                text = content.get("text", "")
            elif msg_type == "post":
                text = self._extract_post(content)
            elif msg_type in _MSG_TYPE_MAP:
                text = f"[{msg_type}]"
                media.append(
                    MediaItem(
                        type=_MSG_TYPE_MAP[msg_type],
                        mime_type=content.get("mime_type", "application/octet-stream"),
                        filename=content.get("file_name"),
                    )
                )
            else:
                text = f"[{msg_type}]"

            # Store for reply
            root_id = msg.root_id or msg.message_id
            self._last_msg[chat_id] = {"root_id": root_id, "chat_type": chat_type}

            inbound = ChannelMessage(
                session_id=f"feishu:{chat_id}",
                channel="feishu",
                chat_id=chat_id,
                content=json.dumps(
                    {
                        "message": text,
                        "message_id": msg.message_id,
                        "chat_type": chat_type,
                        "sender_id": open_id,
                    },
                    ensure_ascii=False,
                ),
                media=media,
                is_active=True,
                context={"feishu_root_id": root_id},
            )
            asyncio.get_event_loop().call_soon_threadsafe(
                lambda: asyncio.create_task(self._on_receive(inbound))
            )
        except Exception as e:
            logger.exception(f"feishu._on_message error: {e}")

    def _extract_post(self, content: dict) -> str:
        zh_cn = content.get("zh_cn", content.get("en_us", {}))
        lines = []
        if title := zh_cn.get("title"):
            lines.append(title)
        for para in zh_cn.get("content", []):
            parts = []
            for elem in para:
                tag = elem.get("tag", "")
                if tag == "text":
                    parts.append(elem.get("text", ""))
                elif tag == "a":
                    parts.append(elem.get("text") or elem.get("href", ""))
                elif tag == "at":
                    parts.append(f"@{elem.get('user_name', elem.get('user_id', ''))}")
            if parts:
                lines.append("".join(parts))
        return "\n".join(lines)

    async def send(self, message: ChannelMessage) -> None:
        if not self._api_client:
            return

        try:
            data = json.loads(message.content)
            text = data.get("message", "")
        except json.JSONDecodeError:
            text = message.content

        if not text.strip():
            return

        root_id = message.context.get("feishu_root_id", "")
        if not root_id and (info := self._last_msg.get(message.chat_id)):
            root_id = info.get("root_id", "")

        # 使用post消息类型支持markdown渲染
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
            chat_type = self._last_msg.get(message.chat_id, {}).get("chat_type", "p2p")
            id_type = "chat_id" if chat_type in ("group", "topic") else "open_id"
            req = (
                CreateMessageRequest.builder()
                .receive_id_type(id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(message.chat_id)
                    .msg_type("post")
                    .content(content_json)
                    .build()
                )
                .build()
            )
            resp = self._api_client.im.v1.message.create(req)

        if not resp.success():
            logger.error(f"feishu.send failed: code={resp.code} msg={resp.msg}")
