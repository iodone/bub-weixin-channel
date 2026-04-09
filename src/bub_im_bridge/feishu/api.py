"""Feishu API helpers — thin wrappers around lark_oapi for use by tools."""

from __future__ import annotations

import contextlib
import json
import re
import time
from datetime import datetime
from typing import Any

import lark_oapi as lark
from loguru import logger


# ---------------------------------------------------------------------------
# Public API functions (no dependency on Channel)
# ---------------------------------------------------------------------------


async def fetch_message_content(client: lark.Client, message_id: str) -> str | None:
    """Fetch the text content of a single message by ID."""
    api = _get_message_api(client)
    if api is None or not message_id:
        return None

    try:
        from lark_oapi.api.im.v1 import GetMessageRequest

        req = GetMessageRequest.builder().message_id(message_id).build()
        resp = api.get(req)

        if not resp.success():
            logger.warning(
                "feishu.api.fetch_message failed message_id={} code={} msg={}",
                message_id,
                resp.code,
                resp.msg,
            )
            return None

        data = getattr(resp, "data", None)
        if data:
            body = getattr(data, "body", None)
            content = getattr(body, "content", None) if body else None
            if content:
                msg_type = getattr(data, "msg_type", None) or "text"
                return _normalize_text(msg_type, content)

    except Exception:
        logger.exception("feishu.api.fetch_message error message_id={}", message_id)

    return None


async def fetch_chat_history(
    client: lark.Client,
    chat_id: str,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
    resolve_names: bool = True,
    user_name_cache: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Fetch chat messages, optionally filtered by time range.

    Returns all pages of results.  Uses :func:`parse_time_range` to convert
    human-friendly strings like ``"1d"`` or ``"3h"`` into timestamps.
    """
    api = _get_message_api(client)
    if api is None or not chat_id:
        return []

    start_ts = parse_time_range(start_time)
    end_ts = parse_time_range(end_time)
    history: list[dict[str, str]] = []
    page_token: str | None = None
    cache = user_name_cache if user_name_cache is not None else {}

    try:
        from lark_oapi.api.im.v1 import ListMessageRequest

        while True:
            builder = (
                ListMessageRequest.builder()
                .container_id_type("chat")
                .container_id(chat_id)
                .page_size(50)
            )
            if start_ts:
                builder.start_time(str(int(start_ts)))
            if end_ts:
                builder.end_time(str(int(end_ts)))
            if page_token:
                builder.page_token(page_token)

            resp = api.list(builder.build())

            if not resp.success():
                logger.warning(
                    "feishu.api.fetch_history failed chat_id={} code={} msg={}",
                    chat_id,
                    resp.code,
                    resp.msg,
                )
                break

            data = getattr(resp, "data", None)
            for item in getattr(data, "items", None) or []:
                body = getattr(item, "body", None)
                content = getattr(body, "content", None) if body else None
                if not content:
                    continue
                msg_type = getattr(item, "msg_type", None) or "text"
                sender = getattr(item, "sender", None)
                sender_id = (getattr(sender, "id", "") or "") if sender else ""
                sender_name = (
                    resolve_user_name(client, sender_id, cache=cache)
                    if resolve_names
                    else sender_id
                )
                history.append(
                    {
                        "message_id": getattr(item, "message_id", "") or "",
                        "sender_id": sender_id,
                        "sender": sender_name,
                        "content": _normalize_text(msg_type, content),
                        "create_time": format_feishu_timestamp(
                            getattr(item, "create_time", None)
                        ),
                    }
                )

            has_more = getattr(data, "has_more", False) if data else False
            page_token = getattr(data, "page_token", None) if data else None
            if not has_more or not page_token:
                break

    except Exception:
        logger.exception("feishu.api.fetch_history error chat_id={}", chat_id)

    return history


def resolve_user_name(
    client: lark.Client,
    open_id: str,
    *,
    cache: dict[str, str] | None = None,
) -> str:
    """Resolve an open_id to a display name (with optional cache)."""
    if not open_id:
        return ""
    if cache is not None and open_id in cache:
        return cache[open_id]

    name = _fetch_user_name(client, open_id)
    if cache is not None:
        cache[open_id] = name
    return name


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_message_api(client: lark.Client) -> Any | None:
    """Return the ``im.v1.message`` API handle, or ``None``."""
    im = getattr(client, "im", None)
    v1 = getattr(im, "v1", None) if im else None
    return getattr(v1, "message", None) if v1 else None


def _fetch_user_name(client: lark.Client, open_id: str) -> str:
    """Call Feishu contact API to get user's display name."""
    try:
        from lark_oapi.api.contact.v3 import GetUserRequest

        req = GetUserRequest.builder().user_id(open_id).user_id_type("open_id").build()
        resp = client.contact.v3.user.get(req)
        if resp.success():
            user = getattr(resp, "data", None)
            user_obj = getattr(user, "user", None) if user else None
            if user_obj:
                return getattr(user_obj, "name", None) or open_id
        else:
            logger.debug(
                "feishu.api.fetch_user_name failed open_id={} code={} msg={}",
                open_id,
                resp.code,
                resp.msg,
            )
    except Exception:
        logger.debug("feishu.api.fetch_user_name error open_id={}", open_id)
    return open_id


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


def parse_time_range(time_str: str | None) -> float | None:
    """Parse time range string to Unix timestamp (seconds).

    Supports:
    - Relative: "3h" (hours), "1d", "7d", "30d" (days)
    - ISO format: "2024-01-01", "2024-01-01T10:00:00"
    - Unix timestamp (seconds or milliseconds)
    """
    if not time_str:
        return None
    time_str = time_str.strip()

    # Relative time: hours
    if time_str.endswith("h"):
        try:
            hours = int(time_str[:-1])
            return time.time() - (hours * 3600)
        except ValueError:
            pass

    # Relative time: days
    if time_str.endswith("d"):
        try:
            days = int(time_str[:-1])
            return time.time() - (days * 86400)
        except ValueError:
            pass

    # Try parsing as integer (Unix timestamp)
    try:
        ts = int(time_str)
        if ts > 1e12:
            ts = ts / 1000
        return float(ts)
    except ValueError:
        pass

    # Try ISO format
    try:
        dt = datetime.fromisoformat(time_str)
        return dt.timestamp()
    except ValueError:
        pass

    return None


def format_feishu_timestamp(ts: str | int | None) -> str:
    """Convert Feishu millisecond timestamp to local time string."""
    if not ts:
        return ""
    try:
        epoch_ms = int(ts)
        dt = datetime.fromtimestamp(epoch_ms / 1000).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return str(ts) if ts else ""
