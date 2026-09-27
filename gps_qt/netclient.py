"""Geocoder 與 Router 共用的 HTTP 請求骨架：節流 + 同時間只保留最後一次請求。

兩者都是社群維運的免費服務（Nominatim／Valhalla 的 FOSSGIS 實例），使用政策都要求
可識別的 User-Agent 且不能打得太快；也都有同一個問題：使用者連續查兩次時，前一個
還沒回來的請求要中止，否則舊結果比新結果晚到就會蓋掉畫面。這些規則寫在這裡一次，
子類別只負責組請求與解析回應。

用 QNetworkAccessManager 而非 urllib：它是非同步的，直接跑在 Qt 事件迴圈上，
等待回應期間 UI 不會卡住，也不需要為了一個查詢另外開 thread。
"""

from PySide6.QtCore import QDateTime, QObject, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

# 兩個服務的政策都要求能識別發出請求的應用程式；換成自己的專案位址也可以。
USER_AGENT = "PinDrift-GPS-Simulator/1.0 (https://github.com/garykillyou/PinDrift)"
MIN_REQUEST_INTERVAL_MS = 1000  # Nominatim 政策上限：每秒最多 1 次；Valhalla 沿用同一個間隔


class SingleFlightClient(QObject):
    """子類別實作 _handle_reply()，並透過 _send() 送出請求。

    _handle_reply() 只會收到「最新一次、沒有被取消」的回應；過期或被中止的
    回應在這裡就被濾掉了。
    """

    failed = Signal(str)
    THROTTLED_MESSAGE = "請求太頻繁，請稍候再試"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._last_request_ms = 0

    @staticmethod
    def new_request(url):
        """建立帶好 User-Agent 的請求。"""
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        return request

    def _send(self, make_reply):
        """make_reply(manager) 送出請求並回傳 reply。太頻繁時 emit failed 並回傳 False。"""
        now = self._now_ms()
        if now - self._last_request_ms < MIN_REQUEST_INTERVAL_MS:
            self.failed.emit(self.THROTTLED_MESSAGE)
            return False
        self._last_request_ms = now

        self._abort_pending()
        self._reply = make_reply(self._manager)
        self._reply.finished.connect(self._on_finished)
        return True

    def _now_ms(self):
        return QDateTime.currentMSecsSinceEpoch()

    def _abort_pending(self):
        if self._reply is not None and not self._reply.isFinished():
            self._reply.abort()
        self._reply = None

    def _on_finished(self):
        reply = self.sender()
        reply.deleteLater()
        if reply is not self._reply:
            return  # 已被新的查詢取代，忽略這份過期結果
        self._reply = None
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return
        self._handle_reply(reply)

    def _handle_reply(self, reply):
        raise NotImplementedError
