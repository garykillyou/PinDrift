"""Discord Webhook 通知：抵達端點時把訊息送到使用者自己的 Discord 頻道。

iPhone 本身沒有可以從 USB 端觸發的通知服務（pymobiledevice3 的 notification_proxy
送的是系統內部的 Darwin notification，不會出現在螢幕上），所以改走推播：訊息送進
Discord 頻道，手機上的 Discord App 再推播出來。

Webhook 網址本身就是憑證（拿到的人都能往頻道發訊息），所以：
- 只接受 Discord 官方網域的 webhook 網址（`persistence.is_valid_webhook_url()`），不會把訊息
  POST 到任意主機；重新導向也不跟（Qt 預設會跟著 https 轉到其他網域，307／308 還會把內容再送一次）；
- 失敗訊息一律由 HTTP 狀態碼／錯誤代碼組成，**不用 `reply.errorString()`**——Qt 的
  HTTP 錯誤字串會把完整網址（含 token）寫進去，進了執行日誌與記錄檔就外洩了。
"""

import json

from PySide6.QtCore import QByteArray, QObject, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .netclient import USER_AGENT
from .persistence import is_valid_webhook_url

REQUEST_TIMEOUT_MS = 10000
MESSAGE_PREFIX = "PinDrift："
SENDER_NAME = "PinDrift"
INVALID_URL_MESSAGE = "不是有效的 Discord Webhook 網址"

_HTTP_OK_MIN = 200
_HTTP_OK_MAX = 299
_HTTP_INVALID_WEBHOOK = (401, 403, 404)
_HTTP_RATE_LIMITED = 429


def webhook_payload(message):
    """要 POST 給 webhook 的 JSON 內容（bytes）。"""
    body = {"username": SENDER_NAME, "content": MESSAGE_PREFIX + message}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def describe_result(status, error):
    """依 HTTP 狀態碼與 QNetworkReply 的錯誤代碼回傳 (是否成功, 說明)。

    status 是 None 代表沒拿到 HTTP 回應（連不上、逾時）。說明文字不含網址。
    """
    if status is not None:
        if _HTTP_OK_MIN <= status <= _HTTP_OK_MAX:
            return True, "已傳送"
        if status in _HTTP_INVALID_WEBHOOK:
            return False, f"Webhook 無效或已被刪除（HTTP {status}），請到設定重新貼上網址"
        if status == _HTTP_RATE_LIMITED:
            return False, f"傳送太頻繁，被 Discord 暫時限制（HTTP {status}）"
        return False, f"Discord 回應錯誤（HTTP {status}）"
    if error == QNetworkReply.NetworkError.OperationCanceledError:
        return False, "連線逾時"
    return False, f"無法連線到 Discord（{error.name}）"


class DiscordNotifier(QObject):
    """非同步送出 webhook 訊息；結果經由呼叫端給的 on_done(ok, detail) 回報。

    不像 netclient.SingleFlightClient 那樣只保留最後一次請求：每則通知都要送到，
    不能被下一則取消。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)

    def send(self, url, message, on_done):
        """送出 message；網址不合法時直接以失敗回報並回傳 False。"""
        if not is_valid_webhook_url(url):
            on_done(False, INVALID_URL_MESSAGE)
            return False
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setTransferTimeout(REQUEST_TIMEOUT_MS)
        # webhook 不會重新導向；收到 3xx 就照 describe_result() 當成失敗回報。
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        reply = self._post(request, QByteArray(webhook_payload(message)))
        reply.finished.connect(lambda: self._on_finished(reply, on_done))
        return True

    def _post(self, request, body):
        return self._manager.post(request, body)

    @staticmethod
    def _on_finished(reply, on_done):
        reply.deleteLater()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        on_done(*describe_result(status, reply.error()))
