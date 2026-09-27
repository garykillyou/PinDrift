"""執行日誌的檔案記錄與未處理例外的攔截。

App 平常用 pythonw 或打包成視窗模式的 exe 執行，兩者都沒有主控台，stderr 也不存在：
Qt slot 裡丟出的例外（PySide6 會交給 sys.excepthook 印到 stderr）與沒人 await 的
asyncio task 錯誤，原本都會完全消失。這裡把它們接到兩個地方：

- 記錄檔 `pindrift.log`（與設定檔放在同一個資料夾，見 paths.data_file()）：完整
  traceback，使用者回報問題時可以直接附上。
- 執行日誌面板：一行錯誤摘要，讓使用者知道發生了什麼事。

`gps_qt` 底下每個模組用 `logging.getLogger(__name__)` 取得的 logger 都是這裡
`gps_qt` logger 的子孫，寫進去的訊息都會進到同一份記錄檔。
"""

import logging
import logging.handlers
import sys
import time

from . import paths

LOGGER_NAME = "gps_qt"
LOG_FILE = paths.data_file("pindrift.log")
# 單一檔案 1 MB、保留 3 份舊檔：循環模式跑一整夜也不會把磁碟吃滿。
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger(LOGGER_NAME)
_file_handler = None


def setup_file_logging(path=LOG_FILE):
    """把 gps_qt 的日誌寫進 path。成功回傳 None，開不了檔回傳要顯示給使用者的訊息。

    寫不了記錄檔（放在唯讀位置）不該讓程式開不起來，執行日誌面板照常運作。
    重複呼叫會先移除前一次加上的 handler，不會每行寫兩次。
    """
    global _file_handler
    remove_file_logging()
    logger.setLevel(logging.INFO)
    try:
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
    except OSError as exc:
        return f"無法寫入記錄檔 {path}：{exc}（執行日誌仍會顯示在視窗中）"
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    _file_handler = handler
    return None


def remove_file_logging():
    global _file_handler
    if _file_handler is None:
        return
    logger.removeHandler(_file_handler)
    _file_handler.close()
    _file_handler = None


def timestamped(message, now=None):
    """執行日誌面板的一行：前面加上當地時間 HH:MM:SS。"""
    return f"{time.strftime('%H:%M:%S', time.localtime(now))}  {message}"


def install_exception_hooks(report=None, loop=None):
    """攔截未處理的例外：完整 traceback 寫進記錄檔，摘要交給 report(text) 顯示。

    report 為 None 時只寫記錄檔（MainWindow 建好之前用）。給了 loop 就一併攔截
    asyncio 的錯誤（例如沒人 await 的 task 丟出的例外）。
    """
    def excepthook(exc_type, exc, tb):
        logger.error("未處理的例外", exc_info=(exc_type, exc, tb))
        _report(report, f"程式錯誤：{exc_type.__name__}: {exc}")
        # 有主控台時（開發時用 python.exe 跑）照舊印到 stderr，不然 traceback 只剩記錄檔。
        if sys.stderr is not None:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook
    if loop is None:
        return

    def asyncio_handler(_loop, context):
        exc = context.get("exception")
        message = context.get("message", "")
        logger.error("asyncio：%s", message, exc_info=exc)
        summary = f"{type(exc).__name__}: {exc}" if exc is not None else message
        _report(report, "背景工作錯誤：" + summary)

    loop.set_exception_handler(asyncio_handler)


def _report(report, text):
    if report is None:
        return
    if _file_handler is not None:
        text += f"（詳細內容見 {_file_handler.baseFilename}）"
    try:
        report(text)
    except Exception:
        # 回報本身出錯（例如視窗已經關了）時不能再往外丟：這裡就在 excepthook
        # 裡面，再丟一次只會遞迴。原本的例外已經寫進記錄檔了。
        logger.exception("無法把錯誤顯示在執行日誌")
