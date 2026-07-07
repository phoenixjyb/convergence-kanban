"""Notification layer tests:
- slack_notify is a clean no-op when SLACK_WEBHOOK_URL is unset.
- slack_notify posts the expected Block Kit shape when set (mocked HTTP).
- notify.py dispatcher fans out to every configured backend and survives
  a failure in one backend without affecting the others.
"""

import importlib
import json
import sys
from unittest.mock import patch, MagicMock


# ── slack_notify ─────────────────────────────────────────────────────────

def test_slack_notify_noop_without_url(monkeypatch):
    """No webhook URL → no HTTP call ever attempted."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    import slack_notify
    importlib.reload(slack_notify)
    # Bypass debounce: call _post_webhook directly via _flush after enqueueing
    with patch("urllib.request.build_opener") as opener:
        slack_notify.notify_bug_created("test", "high", "alice-claude")
        slack_notify._flush()
        opener.assert_not_called()


def test_slack_notify_posts_block_kit_when_configured(monkeypatch):
    """With URL set, _post_webhook sends a JSON payload with 'blocks'."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL",
                       "https://hooks.slack.com/services/T0/B0/XXXX")
    import slack_notify
    importlib.reload(slack_notify)

    opened_payloads = []

    class FakeOpener:
        def open(self, req, timeout=None):
            opened_payloads.append(json.loads(req.data))
            class FakeResp:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b'{"ok":true}'
            return FakeResp()

    with patch("urllib.request.build_opener", return_value=FakeOpener()):
        slack_notify.notify_bug_created("Crash on boot", "critical", "alice-claude")
        slack_notify._flush()

    assert len(opened_payloads) == 1
    payload = opened_payloads[0]
    assert "blocks" in payload
    # Header block + section block + context block
    block_types = [b.get("type") for b in payload["blocks"]]
    assert "header" in block_types
    assert "section" in block_types
    # Severity emoji rendered
    header_text = payload["blocks"][0]["text"]["text"]
    assert "Bug Reported" in header_text
    assert "rotating_light" in header_text  # critical → :rotating_light:


def test_slack_notify_all_event_types_have_expected_signatures():
    """The public API mirrors feishu_notify exactly."""
    import slack_notify
    for name in (
        "notify_task_created", "notify_task_status_changed",
        "notify_blocker_created", "notify_blocker_resolved",
        "notify_bug_created",
    ):
        assert hasattr(slack_notify, name), f"missing {name}"


# ── dispatcher fan-out ──────────────────────────────────────────────────

def test_dispatcher_fans_out_to_all_loaded_backends():
    """Every backend's notify_bug_created is called once."""
    import notify
    importlib.reload(notify)

    calls = {"feishu": 0, "slack": 0}

    class FakeFeishu:
        __name__ = "feishu_notify"
        @staticmethod
        def notify_bug_created(*a, **kw): calls["feishu"] += 1

    class FakeSlack:
        __name__ = "slack_notify"
        @staticmethod
        def notify_bug_created(*a, **kw): calls["slack"] += 1

    with patch.object(notify, "_BACKENDS", [FakeFeishu, FakeSlack]):
        notify.notify_bug_created("test", "low", "alice")
    assert calls == {"feishu": 1, "slack": 1}


def test_dispatcher_swallows_per_backend_failures():
    """One backend raising must not block other backends."""
    import notify
    importlib.reload(notify)

    sane_calls = 0

    class BrokenBackend:
        __name__ = "broken_notify"
        @staticmethod
        def notify_bug_created(*a, **kw): raise RuntimeError("boom")

    class SaneBackend:
        __name__ = "sane_notify"
        @staticmethod
        def notify_bug_created(*a, **kw):
            nonlocal sane_calls
            sane_calls += 1

    with patch.object(notify, "_BACKENDS", [BrokenBackend, SaneBackend]):
        notify.notify_bug_created("t", "low", "x")  # must not raise
    assert sane_calls == 1, "sane backend should still be called"


def test_dispatcher_active_backends_reflects_loaded_modules():
    import notify
    importlib.reload(notify)
    backends = notify.active_backends()
    # feishu_notify and slack_notify both ship in this repo, so both should load
    assert isinstance(backends, list)
    assert "feishu_notify" in backends
    assert "slack_notify" in backends


# ── dingtalk_notify ──────────────────────────────────────────────────────

def test_dingtalk_notify_noop_without_url(monkeypatch):
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK_SECRET", raising=False)
    import dingtalk_notify
    importlib.reload(dingtalk_notify)
    with patch("urllib.request.build_opener") as opener:
        dingtalk_notify.notify_bug_created("test", "high", "alice-claude")
        dingtalk_notify._flush()
        opener.assert_not_called()


def test_dingtalk_notify_posts_markdown_when_configured(monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL",
                       "https://oapi.dingtalk.com/robot/send?access_token=FAKE")
    monkeypatch.delenv("DINGTALK_WEBHOOK_SECRET", raising=False)
    import dingtalk_notify
    importlib.reload(dingtalk_notify)

    captured = []

    class FakeOpener:
        def open(self, req, timeout=None):
            captured.append((req.full_url, json.loads(req.data.decode("utf-8"))))
            class FakeResp:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b'{"errcode":0}'
            return FakeResp()

    with patch("urllib.request.build_opener", return_value=FakeOpener()):
        dingtalk_notify.notify_bug_created("Boot failure", "high", "alice-claude")
        dingtalk_notify._flush()

    assert len(captured) == 1
    url, payload = captured[0]
    # No HMAC → URL unchanged
    assert "sign=" not in url
    assert payload["msgtype"] == "markdown"
    assert "Bug Reported" in payload["markdown"]["title"]
    assert "Boot failure" in payload["markdown"]["text"]


def test_dingtalk_notify_signs_url_when_secret_set(monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL",
                       "https://oapi.dingtalk.com/robot/send?access_token=FAKE")
    monkeypatch.setenv("DINGTALK_WEBHOOK_SECRET", "SECfakesecret123456")
    import dingtalk_notify
    importlib.reload(dingtalk_notify)
    signed = dingtalk_notify._sign_url()
    assert "timestamp=" in signed
    assert "sign=" in signed
    # Sign is base64-then-url-encoded; should be present and non-empty
    assert "sign=&" not in signed and not signed.endswith("sign=")
