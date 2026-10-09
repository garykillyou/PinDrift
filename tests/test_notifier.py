"""notifier 的網址檢查、payload、結果說明與送出流程測試（用假的 reply，不連網路）。"""

import json

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

from gps_qt import notifier
from gps_qt.notifier import DiscordNotifier

VALID_URL = "https://discord.com/api/webhooks/123456789/abc_DEF-ghi"


@pytest.mark.parametrize("url", [
    VALID_URL,
    VALID_URL + "/",
    "https://discordapp.com/api/webhooks/1/token",
    "https://ptb.discord.com/api/webhooks/1/token",
    "https://canary.discord.com/api/webhooks/1/token",
    VALID_URL + "?thread_id=987654321",                    # 論壇頻道
])
def test_is_valid_webhook_url_accepts_discord_webhooks(url):
    assert notifier.is_valid_webhook_url(url)


@pytest.mark.parametrize("url", [
    "",
    None,
    123,
    "http://discord.com/api/webhooks/1/token",            # 不是 https
    "https://evil.com/api/webhooks/1/token",               # 別的主機
    "https://discord.com.evil.com/api/webhooks/1/token",   # 假冒的網域
    "https://discord.com/api/webhooks/abc/token",          # id 不是數字
    "https://discord.com/api/webhooks/1",                  # 少了 token
    " " + VALID_URL,                                       # 前後空白要由呼叫端先去掉
    VALID_URL + "?wait=true",
    VALID_URL + "?thread_id=abc",
])
def test_is_valid_webhook_url_rejects_everything_else(url):
    assert not notifier.is_valid_webhook_url(url)


def test_webhook_payload_has_prefixed_content_and_keeps_chinese():
    # Act
    body = notifier.webhook_payload("已抵達終點")

    # Assert
    assert json.loads(body.decode("utf-8")) == {
        "username": notifier.SENDER_NAME,
        "content": notifier.MESSAGE_PREFIX + "已抵達終點",
    }
    assert "已抵達終點".encode("utf-8") in body


@pytest.mark.parametrize("status", [200, 204])
def test_describe_result_success_for_2xx(status):
    assert notifier.describe_result(status, QNetworkReply.NetworkError.NoError)[0] is True


@pytest.mark.parametrize("status,keyword", [
    (307, "HTTP 307"),                                     # 不跟重新導向，當成失敗
    (404, "Webhook 無效"),
    (401, "Webhook 無效"),
    (429, "太頻繁"),
    (500, "HTTP 500"),
])
def test_describe_result_explains_http_errors(status, keyword):
    ok, detail = notifier.describe_result(status, QNetworkReply.NetworkError.ContentNotFoundError)
    assert ok is False
    assert keyword in detail


def test_describe_result_without_status_reports_timeout_or_network_error():
    timeout = notifier.describe_result(None, QNetworkReply.NetworkError.OperationCanceledError)
    unreachable = notifier.describe_result(None, QNetworkReply.NetworkError.HostNotFoundError)
    assert timeout == (False, "連線逾時")
    assert unreachable[0] is False and "HostNotFoundError" in unreachable[1]


class FakeReply(QObject):
    finished = Signal()

    def __init__(self, status, error):
        super().__init__()
        self._status = status
        self._error = error

    def attribute(self, attr):
        assert attr == QNetworkRequest.Attribute.HttpStatusCodeAttribute
        return self._status

    def error(self):
        return self._error


class RecordingNotifier(DiscordNotifier):
    def __init__(self, reply):
        super().__init__()
        self.reply = reply
        self.posted = []

    def _post(self, request, body):
        self.posted.append((request, bytes(body.data())))
        return self.reply


@pytest.fixture
def results():
    return []


def _record(results):
    return lambda ok, detail: results.append((ok, detail))


def test_send_posts_json_to_webhook_and_reports_success(qapp, results):
    # Arrange
    sender = RecordingNotifier(FakeReply(204, QNetworkReply.NetworkError.NoError))

    # Act
    sent = sender.send(VALID_URL, "已抵達終點", _record(results))
    sender.reply.finished.emit()

    # Assert
    assert sent is True
    request, body = sender.posted[0]
    assert request.url().toString() == VALID_URL
    assert request.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) == "application/json"
    assert (
        request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute)
        == QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
    )
    assert json.loads(body)["content"].endswith("已抵達終點")
    assert results == [(True, "已傳送")]


def test_send_failure_detail_never_contains_the_url(qapp, results):
    # Arrange
    sender = RecordingNotifier(FakeReply(404, QNetworkReply.NetworkError.ContentNotFoundError))

    # Act
    sender.send(VALID_URL, "x", _record(results))
    sender.reply.finished.emit()

    # Assert
    ok, detail = results[0]
    assert ok is False
    assert "abc_DEF-ghi" not in detail and "webhooks" not in detail


def test_send_with_invalid_url_reports_failure_without_posting(qapp, results):
    # Arrange
    sender = RecordingNotifier(FakeReply(204, QNetworkReply.NetworkError.NoError))

    # Act
    sent = sender.send("https://evil.com/api/webhooks/1/token", "x", _record(results))

    # Assert
    assert sent is False
    assert sender.posted == []
    assert results == [(False, notifier.INVALID_URL_MESSAGE)]
