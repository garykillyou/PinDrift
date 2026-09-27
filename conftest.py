"""放在專案根目錄，讓 pytest 把根目錄加進 sys.path，測試才 import 得到 gps_qt 套件。"""

import os

import pytest


@pytest.fixture(scope="session")
def qapp():
    """整個測試過程共用一個 QApplication（offscreen，不開視窗）。

    一個行程只能有一個 Q*Application，而且 QApplication 必須是第一個建立的：
    若先有人建了 QCoreApplication，之後就建不出需要 widget 的 QApplication。
    所以需要 Qt 應用程式物件的測試一律透過這個 fixture 取得。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
