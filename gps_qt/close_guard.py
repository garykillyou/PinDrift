"""模擬進行中關閉視窗：先恢復 iPhone 的真實定位，再真正關閉。

直接關掉的話，qasync 的事件迴圈一停，GPSSession 的 task 就被整個銷毀，
sim.clear() 從來沒有被呼叫，只能靠連線中斷時 iPhone 自己恢復真實定位。
所以第一次關閉先擋下來，走一般的 restore_real_location()，等 session_ended
再關一次；sim.clear() 卡住（USB 已拔掉等）時以逾時為限，不讓視窗永遠關不掉。

只用到 QtCore，MainWindow 之外也能單獨測試。
"""

import logging

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)

# 等待恢復真實定位的上限。正常情況下 sim.clear() 一來一回不到一秒。
RESTORE_TIMEOUT_MS = 5000


class CloseGuard(QObject):
    def __init__(self, session, confirm, close_window, log, timeout_ms=RESTORE_TIMEOUT_MS,
                 parent=None):
        """
        session:      GPSSession（用到 session_active、restore_real_location()、session_ended）
        confirm:      () -> bool，詢問使用者是否要恢復真實定位並關閉
        close_window: () -> None，真正關閉視窗（會再進一次 closeEvent）
        log:          (str) -> None，寫進執行日誌
        """
        super().__init__(parent)
        self._session = session
        self._confirm = confirm
        self._close_window = close_window
        self._log = log
        self._restoring = False
        self._ready_to_close = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._on_timeout)

    def allow_close(self):
        """closeEvent 呼叫：回傳 True 代表這次可以直接關閉，False 代表先擋下。"""
        if self._ready_to_close or not self._session.session_active:
            return True
        if self._restoring:
            # 已經在恢復中，重複按關閉不再問一次，等它自己關。
            return False
        if not self._confirm():
            return False
        self._restoring = True
        self._log("恢復真實定位中，完成後會自動關閉視窗...")
        self._session.session_ended.connect(self._finish)
        self._timer.start()
        self._session.restore_real_location()
        return False

    def _on_timeout(self):
        message = "恢復真實定位逾時，直接關閉視窗（中斷連線後 iPhone 通常會自行恢復）"
        # 視窗馬上就要關了，執行日誌看不到，記錄檔一定要留一份。
        logger.warning(message)
        self._log(message)
        self._finish()

    def _finish(self):
        if self._ready_to_close:
            return
        self._ready_to_close = True
        self._timer.stop()
        self._session.session_ended.disconnect(self._finish)
        # 排到下一輪事件迴圈才關：session_ended 是在 _session_main() 的 finally 裡
        # 發出的，先讓那個 task 自己跑完，事件迴圈停下時才不會留下沒收尾的 task。
        QTimer.singleShot(0, self._close_window)
