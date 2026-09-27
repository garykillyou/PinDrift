"""netclient.SingleFlightClient 的節流與過期結果過濾測試（用假的 reply，不連網路）。"""

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply

from gps_qt.netclient import MIN_REQUEST_INTERVAL_MS, SingleFlightClient


@pytest.fixture(autouse=True)
def _qt_app(qapp):
    # QNetworkAccessManager 需要 Q*Application 存在（共用 conftest 的 qapp）
    return qapp


class FakeReply(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self._finished = False
        self._error = QNetworkReply.NetworkError.NoError

    def isFinished(self):
        return self._finished

    def error(self):
        return self._error

    def abort(self):
        # 與 QNetworkReply 一致：abort() 會以 OperationCanceledError 結束並發出 finished
        self._error = QNetworkReply.NetworkError.OperationCanceledError
        self.finish()

    def finish(self):
        self._finished = True
        self.finished.emit()


class RecordingClient(SingleFlightClient):
    THROTTLED_MESSAGE = "太頻繁"

    def __init__(self):
        super().__init__()
        self.now_ms = 10_000
        self.handled = []
        self.failures = []
        self.failed.connect(self.failures.append)

    def _now_ms(self):
        return self.now_ms

    def _handle_reply(self, reply):
        self.handled.append(reply)

    def send(self):
        reply = FakeReply()
        return reply if self._send(lambda _manager: reply) else None


def test_second_request_within_interval_is_throttled():
    # Arrange
    client = RecordingClient()
    client.send()

    # Act
    client.now_ms += MIN_REQUEST_INTERVAL_MS - 1
    second = client.send()

    # Assert
    assert second is None
    assert client.failures == ["太頻繁"]


def test_newer_request_aborts_the_pending_one_and_only_its_result_is_handled():
    # Arrange
    client = RecordingClient()
    first = client.send()
    client.now_ms += MIN_REQUEST_INTERVAL_MS

    # Act
    second = client.send()
    second.finish()

    # Assert：舊請求被中止且結果被丟掉，只處理新的那一個
    assert first.error() == QNetworkReply.NetworkError.OperationCanceledError
    assert client.handled == [second]
    assert client.failures == []


def test_late_result_of_a_replaced_request_is_ignored():
    # Arrange：舊請求已經回來、但還沒處理前就被新請求取代
    client = RecordingClient()
    first = client.send()
    first._finished = True  # 已完成但 finished 還在事件佇列裡，abort() 不會再動它
    client.now_ms += MIN_REQUEST_INTERVAL_MS
    second = client.send()

    # Act
    first.finished.emit()

    # Assert
    assert client.handled == []
    second.finish()
    assert client.handled == [second]


def test_cancel_aborts_the_pending_request_and_drops_its_result():
    # Arrange：開始移動時路徑規劃還在查詢中
    client = RecordingClient()
    reply = client.send()

    # Act
    client.cancel()

    # Assert：結果不會再被處理，之後也能正常送出新請求
    assert reply.error() == QNetworkReply.NetworkError.OperationCanceledError
    assert client.handled == []
