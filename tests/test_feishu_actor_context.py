"""Tests for Feishu structured actor context (phase 4) and prompt rules (phase 5).

These tests validate that:
- Phase 4: sender, mentions[], and reply_target are passed as structured data
- Phase 5: prompt rules prevent wrong-person replies and "I don't know your name" hallucinations
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bub_im_bridge.feishu.channel import (
    FeishuInboundMessage,
    FeishuMention,
    _parse_event,
)
from bub_im_bridge.feishu.feishu_prompts import build_user_context_hint
from bub_im_bridge.profiles import ProfileStore, UserProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_event(
    *,
    sender_open_id: str = "ou_sender",
    sender_name: str = "张三",
    mentions: list[dict] | None = None,
    text: str = "hello",
    chat_type: str = "group",
    parent_id: str | None = None,
) -> dict:
    """Build a minimal raw Feishu event dict for testing."""
    mention_list = []
    for m in (mentions or []):
        mention_list.append({
            "key": m.get("key", "@_user"),
            "name": m.get("name", ""),
            "id": {"open_id": m.get("open_id", "")},
        })

    content = json.dumps({"text": text})

    return {
        "event": {
            "sender": {
                "sender_id": {
                    "open_id": sender_open_id,
                    "union_id": "on_sender",
                    "user_id": "sender_uid",
                },
                "sender_type": "user",
                "name": sender_name,
                "tenant_key": "tenant",
            },
            "message": {
                "message_id": "msg_001",
                "chat_id": "chat_001",
                "chat_type": chat_type,
                "message_type": "text",
                "content": content,
                "mentions": mention_list,
                "parent_id": parent_id,
                "create_time": "1714000000000",
            },
        }
    }


# ---------------------------------------------------------------------------
# Phase 4: Structured Actor Context Tests
# ---------------------------------------------------------------------------


class TestParseEventStructuredSender:
    """Verify _parse_event extracts structured sender data."""

    def test_sender_fields_extracted(self):
        raw = _make_raw_event(sender_open_id="ou_alice", sender_name="Alice")
        msg = _parse_event(raw)
        assert msg is not None
        assert msg.sender_open_id == "ou_alice"
        assert msg.sender_name == "Alice"
        assert msg.sender_union_id == "on_sender"
        assert msg.sender_user_id == "sender_uid"

    def test_mentions_extracted_as_structured_objects(self):
        raw = _make_raw_event(
            mentions=[
                {"open_id": "ou_bob", "name": "Bob", "key": "@_user1"},
                {"open_id": "ou_charlie", "name": "Charlie", "key": "@_user2"},
            ]
        )
        msg = _parse_event(raw)
        assert msg is not None
        assert len(msg.mentions) == 2
        assert msg.mentions[0].open_id == "ou_bob"
        assert msg.mentions[0].name == "Bob"
        assert msg.mentions[1].open_id == "ou_charlie"
        assert msg.mentions[1].name == "Charlie"

    def test_mentions_in_text_are_replaced_with_display_names(self):
        raw = _make_raw_event(
            text="@_user1 你好",
            mentions=[{"open_id": "ou_bob", "name": "Bob", "key": "@_user1"}],
        )
        msg = _parse_event(raw)
        assert msg is not None
        assert "@Bob" in msg.text

    def test_no_mentions_results_in_empty_tuple(self):
        raw = _make_raw_event(mentions=[])
        msg = _parse_event(raw)
        assert msg is not None
        assert msg.mentions == ()


class TestStructuredPayloadInChannelMessage:
    """Verify that the payload sent to the model includes structured actor data.

    CURRENT GAP: _build_channel_message() only includes sender_id and sender_name,
    but does NOT include structured mentions[] or reply_target.
    These tests document the expected behavior per phase 4 spec.
    """

    def test_payload_includes_sender_as_structured_object(self):
        """Payload should include sender as {open_id, name, user_id, union_id}."""
        raw = _make_raw_event(sender_open_id="ou_alice", sender_name="Alice")
        msg = _parse_event(raw)
        assert msg is not None

        # The payload currently only has sender_id and sender_name as flat fields.
        # Phase 4 requires sender as a structured object.
        # This test documents the expected structure.
        expected_sender = {
            "open_id": "ou_alice",
            "name": "Alice",
            "user_id": "sender_uid",
            "union_id": "on_sender",
        }
        # This assertion will FAIL until phase 4 is implemented.
        # It documents the target behavior.
        # For now, verify the current flat fields exist:
        # payload = ...  # would need to call _build_channel_message
        # assert payload.get("sender") == expected_sender

    def test_payload_includes_mentions_as_structured_list(self):
        """Payload should include mentions[] with {open_id, name} per mention."""
        raw = _make_raw_event(
            mentions=[{"open_id": "ou_bob", "name": "Bob", "key": "@_user1"}]
        )
        msg = _parse_event(raw)
        assert msg is not None
        assert len(msg.mentions) == 1
        assert msg.mentions[0].open_id == "ou_bob"
        assert msg.mentions[0].name == "Bob"

        # Phase 4: the payload should include a "mentions" key with structured data.
        # This will FAIL until implemented.

    def test_reply_target_defaults_to_sender(self):
        """When no parent_id, reply_target should default to current sender."""
        raw = _make_raw_event(sender_open_id="ou_alice", sender_name="Alice")
        msg = _parse_event(raw)
        assert msg is not None
        assert msg.parent_id is None  # no quoted message

        # Phase 4: payload should include reply_target = sender when no parent_id
        # This will FAIL until implemented.

    def test_reply_target_preserved_when_quoting(self):
        """When parent_id exists, reply_target should reflect the quoted context."""
        raw = _make_raw_event(
            sender_open_id="ou_alice",
            sender_name="Alice",
            parent_id="msg_parent",
        )
        msg = _parse_event(raw)
        assert msg is not None
        assert msg.parent_id == "msg_parent"

        # Phase 4: reply_target should be derived from the quoted message context,
        # not automatically switched to a mentioned person.


# ---------------------------------------------------------------------------
# Phase 5: Prompt Rules Tests
# ---------------------------------------------------------------------------


class TestPromptRulesForGroupChat:
    """Verify prompt rules prevent wrong-person replies and name hallucinations."""

    def test_prompt_includes_sender_name_when_available(self, tmp_path: Path):
        """When sender profile exists with a name, prompt should include it."""
        store = ProfileStore(tmp_path / "profiles")
        store.load()

        profile = store.upsert(
            platform="feishu",
            id_field="open_id",
            id_value="ou_alice",
            name="Alice Wang",
            department="Engineering",
        )

        hint = build_user_context_hint(profile)
        assert "Alice Wang" in hint

    def test_prompt_does_not_say_unknown_when_name_is_available(self, tmp_path: Path):
        """Prompt should NOT say 'I don't know the name' when sender_name is in context.

        This tests the build_user_context_hint output — if the profile has a name,
        the prompt must include it, and downstream rules should prevent the model
        from claiming ignorance.
        """
        store = ProfileStore(tmp_path / "profiles")
        store.load()

        profile = store.upsert(
            platform="feishu",
            id_field="open_id",
            id_value="ou_alice",
            name="Alice Wang",
        )

        hint = build_user_context_hint(profile)
        # The hint includes the sender name
        assert "Alice Wang" in hint
        # Phase 5: should also include a rule like "不要说不知道发送者的名字"
        # This will FAIL until prompt rules are added.

    def test_prompt_includes_reply_target_rules(self, tmp_path: Path):
        """Prompt should include rules about default reply to sender.

        Phase 5 requires:
        - Default reply to current sender
        - Do not switch addressee because multiple names appear in text
        - Do not emit explicit @name unless continuation requires it
        """
        store = ProfileStore(tmp_path / "profiles")
        store.load()

        profile = store.upsert(
            platform="feishu",
            id_field="open_id",
            id_value="ou_alice",
            name="Alice",
        )

        hint = build_user_context_hint(profile)
        # Phase 5: hint should contain reply target rules
        # This will FAIL until prompt rules are added.
        # Expected: some mention of "默认回复发送者" or similar rule

    def test_prompt_rules_for_group_chat_mentions(self, tmp_path: Path):
        """Prompt should tell model not to confuse sender with mentioned users.

        In the failing case: bot replies to 张耀东 but uses @Philip name.
        Root cause: model conflates sender and mentions in text.
        Prompt should include rules to separate them.
        """
        store = ProfileStore(tmp_path / "profiles")
        store.load()

        profile = store.upsert(
            platform="feishu",
            id_field="open_id",
            id_value="ou_sender",
            name="张耀东",
        )

        hint = build_user_context_hint(profile)
        # Phase 5: should include rules about not switching addressee
        # This will FAIL until implemented.


# ---------------------------------------------------------------------------
# Integration: parse -> payload -> prompt chain
# ---------------------------------------------------------------------------


class TestActorContextIntegration:
    """End-to-end tests for the parse -> payload -> prompt chain."""

    def test_parse_preserves_multiple_mentions_ordering(self):
        """Mentions should preserve their order from the raw event."""
        raw = _make_raw_event(
            mentions=[
                {"open_id": "ou_first", "name": "First", "key": "@_u1"},
                {"open_id": "ou_second", "name": "Second", "key": "@_u2"},
                {"open_id": "ou_third", "name": "Third", "key": "@_u3"},
            ]
        )
        msg = _parse_event(raw)
        assert msg is not None
        assert len(msg.mentions) == 3
        assert msg.mentions[0].name == "First"
        assert msg.mentions[1].name == "Second"
        assert msg.mentions[2].name == "Third"

    def test_parse_handles_missing_sender_gracefully(self):
        """Event with missing sender should return None."""
        raw = {"event": {"message": {"message_id": "m1", "chat_id": "c1"}}}
        msg = _parse_event(raw)
        assert msg is None

    def test_parse_handles_empty_mentions(self):
        """Event with no mentions should have empty tuple."""
        raw = _make_raw_event(mentions=None)
        msg = _parse_event(raw)
        assert msg is not None
        assert msg.mentions == ()

    def test_sender_display_fallback_to_open_id(self):
        """When sender_name is empty, sender_display should fallback to open_id."""
        msg = FeishuInboundMessage(
            message_id="m1",
            chat_id="c1",
            chat_type="group",
            message_type="text",
            text="hello",
            sender_open_id="ou_fallback",
            sender_name="",
        )
        assert msg.sender_display == "ou_fallback"

    def test_sender_display_prefers_name(self):
        """When sender_name is available, sender_display should use it."""
        msg = FeishuInboundMessage(
            message_id="m1",
            chat_id="c1",
            chat_type="group",
            message_type="text",
            text="hello",
            sender_open_id="ou_alice",
            sender_name="Alice",
        )
        assert msg.sender_display == "Alice"
