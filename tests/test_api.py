"""Unit tests for feishu API helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from bub_im_bridge.feishu.api import fetch_user_info


def test_fetch_user_info_returns_dict():
    """fetch_user_info returns a dict with name, department, title, avatar_url."""
    mock_user = MagicMock()
    mock_user.name = "Alice"
    mock_user.department_id = "dept_001"
    mock_user.job_title = "Engineer"
    mock_user.avatar = MagicMock()
    mock_user.avatar.avatar_72 = "https://avatar.url"

    mock_data = MagicMock()
    mock_data.user = mock_user

    mock_resp = MagicMock()
    mock_resp.success.return_value = True
    mock_resp.data = mock_data

    mock_client = MagicMock()
    mock_client.contact.v3.user.get.return_value = mock_resp

    info = fetch_user_info(mock_client, "ou_aaa")
    assert info["name"] == "Alice"
    assert info["job_title"] == "Engineer"
    assert info["avatar_url"] == "https://avatar.url"


def test_fetch_user_info_fallback_on_failure():
    mock_resp = MagicMock()
    mock_resp.success.return_value = False
    mock_resp.code = 41050
    mock_resp.msg = "no permission"

    mock_client = MagicMock()
    mock_client.contact.v3.user.get.return_value = mock_resp

    info = fetch_user_info(mock_client, "ou_bbb")
    assert info["name"] == "ou_bbb"
