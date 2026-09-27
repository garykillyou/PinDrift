"""applog：記錄檔、日誌時間戳記與未處理例外的攔截。"""

import asyncio
import logging
import sys
import time

import pytest

from gps_qt import applog


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "pindrift.log"
    assert applog.setup_file_logging(str(path)) is None
    yield path
    applog.remove_file_logging()


@pytest.fixture
def restore_excepthook(monkeypatch):
    # 測試會換掉 sys.excepthook，結束後由 monkeypatch 換回來
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)


def _flush():
    for handler in logging.getLogger(applog.LOGGER_NAME).handlers:
        handler.flush()


def test_messages_from_any_gps_qt_module_go_to_the_log_file(log_file):
    # Act
    logging.getLogger("gps_qt.widgets.main_window").info("開始移動...")
    _flush()

    # Assert
    content = log_file.read_text(encoding="utf-8")
    assert "開始移動..." in content
    assert "gps_qt.widgets.main_window" in content


def test_setup_returns_a_message_when_the_log_file_cannot_be_opened(tmp_path):
    # Act：放在唯讀位置時寫不了記錄檔，但不能讓程式開不起來
    message = applog.setup_file_logging(str(tmp_path / "沒有這個資料夾" / "pindrift.log"))

    # Assert
    assert isinstance(message, str)
    assert "沒有這個資料夾" in message
    applog.remove_file_logging()


def test_setup_twice_does_not_duplicate_lines(tmp_path):
    # Arrange
    path = tmp_path / "pindrift.log"
    applog.setup_file_logging(str(path))
    applog.setup_file_logging(str(path))

    # Act
    logging.getLogger("gps_qt").info("只出現一次")
    _flush()
    applog.remove_file_logging()

    # Assert
    assert path.read_text(encoding="utf-8").count("只出現一次") == 1


def test_timestamped_prefixes_local_time():
    # Arrange
    now = time.mktime((2026, 9, 27, 21, 5, 9, 0, 0, -1))

    # Act / Assert
    assert applog.timestamped("tunneld 已在執行。", now) == "21:05:09  tunneld 已在執行。"


def test_excepthook_logs_traceback_and_reports_a_summary(log_file, restore_excepthook):
    # Arrange
    reports = []
    applog.install_exception_hooks(reports.append)

    # Act：模擬 Qt slot 裡丟出、沒人接住的例外
    try:
        raise ValueError("表格資料錯誤")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    _flush()

    # Assert：UI 看到摘要，記錄檔有完整 traceback
    assert len(reports) == 1
    assert "ValueError: 表格資料錯誤" in reports[0]
    assert str(log_file) in reports[0]
    content = log_file.read_text(encoding="utf-8")
    assert "Traceback" in content and "表格資料錯誤" in content


def test_asyncio_errors_are_reported(log_file, restore_excepthook):
    # Arrange
    reports = []
    loop = asyncio.new_event_loop()
    try:
        applog.install_exception_hooks(reports.append, loop)

        # Act：沒人 await 的 task 丟出例外時，asyncio 走的就是這條路
        loop.call_exception_handler({
            "message": "Task exception was never retrieved",
            "exception": RuntimeError("boom"),
        })
    finally:
        loop.close()

    # Assert
    assert len(reports) == 1
    assert "RuntimeError: boom" in reports[0]


def test_a_failing_reporter_does_not_raise(log_file, restore_excepthook):
    # Arrange：回報本身出錯（例如視窗已經關了）時不能再丟例外，否則會無限遞迴
    def broken(_text):
        raise RuntimeError("視窗已關閉")
    applog.install_exception_hooks(broken)

    # Act / Assert
    sys.excepthook(ValueError, ValueError("x"), None)
