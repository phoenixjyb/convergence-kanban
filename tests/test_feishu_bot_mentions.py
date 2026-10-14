"""Bot event routing must not turn ordinary team messages into commands."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def event_bot(monkeypatch):
    import feishu_bot as bot

    monkeypatch.setattr(bot, "BOT_OPEN_ID", "ou_this_bot")
    monkeypatch.setattr(bot, "_resolve_sender", Mock(return_value="test-human"))
    monkeypatch.setattr(bot, "cmd_progress", Mock(return_value="Project progress"))
    monkeypatch.setattr(bot, "cmd_help", Mock(return_value="Kanban help"))
    monkeypatch.setattr(bot, "ReplyMessageRequestBody", SimpleNamespace, raising=False)
    monkeypatch.setattr(bot, "ReplyMessageRequest", Mock(), raising=False)
    client = SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(message=SimpleNamespace(reply=Mock()))))
    return bot, client


def event(text, chat_type="group", mentioned_id=None, key="@_user_1", sender_type="user"):
    mentions = [] if mentioned_id is None else [SimpleNamespace(key=key, id=SimpleNamespace(open_id=mentioned_id))]
    return SimpleNamespace(
        message=SimpleNamespace(message_id="om_test", message_type="text", chat_type=chat_type,
                                content=json.dumps({"text": text}), mentions=mentions),
        sender=SimpleNamespace(sender_type=sender_type, sender_id=SimpleNamespace(open_id="ou_sender")),
    )


@pytest.mark.parametrize("message", [
    event("大家注意，新版已发布"),
    event("@_all 大家下班前更新进度", mentioned_id="all", key="@_all"),
    event("@_all help", mentioned_id="all", key="@_all"),
    event("progress"),
    event("@_user_1 progress", mentioned_id="ou_someone_else"),
    event("@_user_1 普通聊天内容", mentioned_id="ou_this_bot"),
    event("@_user_1 help me plan tomorrow", mentioned_id="ou_this_bot"),
    event("@recomoKanban-bot help"),
    event("今天讨论进度 @_user_1 progress", mentioned_id="ou_this_bot"),
    event("@_user_1 @_all progress", mentioned_id="ou_this_bot"),
    event("@_user_1 progress", mentioned_id="ou_this_bot", sender_type="app"),
    event("普通聊天", chat_type="p2p"),
    event("progress", chat_type="unknown"),
    event(123, chat_type="p2p"),
])
def test_unaddressed_and_unrecognized_messages_are_silent(event_bot, message):
    bot, client = event_bot
    bot.handle_message(client, message)
    client.im.v1.message.reply.assert_not_called()
    bot._resolve_sender.assert_not_called()
    bot.cmd_progress.assert_not_called()
    bot.cmd_help.assert_not_called()


def test_explicit_own_mention_routes_group_command(event_bot):
    bot, client = event_bot
    bot.handle_message(client, event("@_user_1 progress", mentioned_id="ou_this_bot"))
    bot.cmd_progress.assert_called_once_with()
    client.im.v1.message.reply.assert_called_once()


def test_group_mention_uses_identity_not_position_in_mention_list(event_bot):
    bot, client = event_bot
    msg = event("@_user_1 progress", mentioned_id="ou_this_bot")
    msg.message.mentions.insert(0, SimpleNamespace(key="@_all", id=None))
    bot.handle_message(client, msg)
    client.im.v1.message.reply.assert_called_once()


def test_direct_message_recognized_command_still_works(event_bot):
    bot, client = event_bot
    bot.handle_message(client, event("帮助", chat_type="p2p"))
    bot.cmd_help.assert_called_once_with()
    client.im.v1.message.reply.assert_called_once()


def test_identity_unavailable_disables_group_commands(event_bot, monkeypatch):
    bot, client = event_bot
    monkeypatch.setattr(bot, "BOT_OPEN_ID", "")
    bot.handle_message(client, event("@_user_1 help", mentioned_id="ou_this_bot"))
    client.im.v1.message.reply.assert_not_called()


@pytest.mark.parametrize("command", ["done", "完成", "search", "assign", "new", "update", "bug", "time", "comment", "resolve"])
def test_explicit_bare_action_returns_usage(event_bot, command):
    bot, _ = event_bot
    assert "Usage" in bot.route_command(command, "test-human")


def test_malformed_content_is_silent(event_bot):
    bot, client = event_bot
    msg = event("progress", chat_type="p2p")
    for content in ("not-json", "[]", "null"):
        msg.message.content = content
        bot.handle_message(client, msg)
    client.im.v1.message.reply.assert_not_called()


def test_bot_identity_request_uses_tenant_authentication(event_bot, monkeypatch):
    bot, _ = event_bot
    sdk = SimpleNamespace(BaseRequest=SimpleNamespace, HttpMethod=SimpleNamespace(GET="GET"),
                          AccessTokenType=SimpleNamespace(TENANT="tenant"))
    monkeypatch.setattr(bot, "lark", sdk)
    response = SimpleNamespace(success=lambda: True, raw=SimpleNamespace(content=json.dumps({"bot": {"open_id": "ou_this_bot"}})))
    client = SimpleNamespace(request=Mock(return_value=response))
    assert bot._load_bot_open_id(client) == "ou_this_bot"
    request = client.request.call_args.args[0]
    assert request.token_types == {"tenant"}
    assert request.http_method == "GET"


def test_failed_identity_lookup_is_safe(event_bot, monkeypatch):
    bot, _ = event_bot
    sdk = SimpleNamespace(BaseRequest=SimpleNamespace, HttpMethod=SimpleNamespace(GET="GET"),
                          AccessTokenType=SimpleNamespace(TENANT="tenant"))
    monkeypatch.setattr(bot, "lark", sdk)
    client = SimpleNamespace(request=Mock(side_effect=RuntimeError("unavailable")))
    assert bot._load_bot_open_id(client) == ""
