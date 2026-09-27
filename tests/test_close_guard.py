"""CloseGuard 的測試：模擬進行中關閉視窗時，先恢復真實定位再真正關閉。"""

import time

from PySide6.QtCore import QObject, Signal

from gps_qt.close_guard import CloseGuard

WAIT_LIMIT_S = 2.0


class FakeSession(QObject):
    session_ended = Signal()

    def __init__(self, active):
        super().__init__()
        self.session_active = active
        self.restore_calls = 0

    def restore_real_location(self):
        self.restore_calls += 1

    def end(self):
        self.session_active = False
        self.session_ended.emit()


class Recorder:
    def __init__(self, answer=True):
        self.answer = answer
        self.confirm_calls = 0
        self.closed = 0
        self.logs = []

    def confirm(self):
        self.confirm_calls += 1
        return self.answer

    def close_window(self):
        self.closed += 1


def _make_guard(session, recorder, timeout_ms=60000):
    return CloseGuard(
        session, recorder.confirm, recorder.close_window, recorder.logs.append,
        timeout_ms=timeout_ms,
    )


def _process_until(qapp, condition):
    deadline = time.monotonic() + WAIT_LIMIT_S
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()


def test_closes_right_away_when_not_simulating(qapp):
    # Arrange
    session, recorder = FakeSession(active=False), Recorder()
    guard = _make_guard(session, recorder)

    # Act / Assert
    assert guard.allow_close() is True
    assert recorder.confirm_calls == 0
    assert session.restore_calls == 0


def test_cancelling_the_confirmation_keeps_the_window_open(qapp):
    # Arrange
    session, recorder = FakeSession(active=True), Recorder(answer=False)
    guard = _make_guard(session, recorder)

    # Act
    allowed = guard.allow_close()

    # Assert
    assert allowed is False
    assert recorder.confirm_calls == 1
    assert session.restore_calls == 0


def test_restores_real_location_and_closes_after_the_session_ends(qapp):
    # Arrange
    session, recorder = FakeSession(active=True), Recorder()
    guard = _make_guard(session, recorder)

    # Act：第一次按關閉先被擋下，定位恢復完成後才真的關閉
    allowed = guard.allow_close()
    session.end()
    _process_until(qapp, lambda: recorder.closed)

    # Assert
    assert allowed is False
    assert session.restore_calls == 1
    assert recorder.closed == 1
    assert recorder.logs
    assert guard.allow_close() is True


def test_closing_again_while_restoring_does_not_ask_twice(qapp):
    # Arrange
    session, recorder = FakeSession(active=True), Recorder()
    guard = _make_guard(session, recorder)
    guard.allow_close()

    # Act
    allowed = guard.allow_close()

    # Assert
    assert allowed is False
    assert recorder.confirm_calls == 1
    assert session.restore_calls == 1
    assert recorder.closed == 0


def test_closes_anyway_when_restoring_takes_too_long(qapp):
    """sim.clear() 卡住（例如 USB 已拔掉）時不能讓視窗永遠關不掉。"""
    # Arrange
    session, recorder = FakeSession(active=True), Recorder()
    guard = _make_guard(session, recorder, timeout_ms=10)

    # Act
    guard.allow_close()
    _process_until(qapp, lambda: recorder.closed)
    session.end()  # 逾時之後才結束，不能再關第二次
    qapp.processEvents()

    # Assert
    assert recorder.closed == 1
    assert any("逾時" in line for line in recorder.logs)
