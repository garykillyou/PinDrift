"""程式進入點：建立 QApplication + qasync 事件迴圈，啟動主視窗。

qasync 讓 asyncio 事件迴圈直接跑在 Qt 事件迴圈的同一條 thread 上，
GPSSession 的 async/await 狀態機因此不需要背景 thread。
"""

import asyncio
import sys

# QtWebEngineWidgets 必須在建立 QApplication 之前 import：Qt 6 在這個模組載入時
# 才會設定 AA_ShareOpenGLContexts，順序反了地圖面板會無法初始化（Qt 會直接中止）。
# 這行看起來沒被用到但不能刪，也不要被自動排序工具搬到 QApplication 之後。
import PySide6.QtWebEngineWidgets  # noqa: F401  isort:skip
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from . import applog, i18n, tile_scheme
from .widgets.main_window import MainWindow


def main():
    # 記錄檔與例外攔截要最先設好：MainWindow 建構途中出錯也要留下 traceback
    # （pythonw／打包版沒有 stderr）。此時還沒有執行日誌面板，先只寫記錄檔。
    log_message = applog.setup_file_logging()
    applog.install_exception_hooks()

    # 自訂 scheme 只能在建立 QApplication 之前登記，晚了 QtWebEngine 會直接忽略。
    tile_scheme.register_scheme()
    app = QApplication(sys.argv)
    # 要在建立任何 widget 之前安裝，標準按鈕的文字是建立當下就翻好的。
    translator = i18n.install_qt_translation(app)  # noqa: F841 保留參照，避免被 GC
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(loop=loop, startup_messages=[log_message])  # noqa: F841 保留參照，避免被 GC

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
