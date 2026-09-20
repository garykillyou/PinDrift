"""確保 pymobiledevice3 的 tunneld 正在執行（iOS 26 的 RemoteXPC 加密通道需要它）。

tunneld 需要系統管理員權限，不能直接在 App 的行程裡跑，必須另外用 ShellExecuteW
的 `runas` 動詞提權啟動一個子行程（會跳 UAC）。這裡同時是「偵測」與「啟動」的
單一來源，`run.bat` 不再自己判斷一次。

打包成 exe 之後使用者的機器上不會有 Python，`python -m pymobiledevice3 ...`
必然失敗，所以提權啟動的對象改成同一份程式的 tunneld 模式：

- 未凍結：提權跑 `python.exe -m gps_qt.tunneld`（工作目錄設為專案根目錄，
  `-m` 才找得到套件）。刻意不用 `pythonw.exe`，開發時保留主控台看得到 tunneld 輸出。
- 已凍結：提權跑同一個資料夾裡的 `PinDrift-tunneld.exe`（打包時一併產生的
  第二個執行檔，console 模式）。
"""

import os
import socket
import sys

from . import paths

TUNNELD_HOST = "127.0.0.1"
TUNNELD_PORT = 49151
# 只是連本機的 TCP 埠，通得到會立刻回來；這個秒數是「沒人在聽」時的等待上限。
PROBE_TIMEOUT_S = 0.5

TUNNELD_EXE_NAME = "PinDrift-tunneld.exe"
# ShellExecuteW 成功時回傳大於 32 的值；1223 是使用者在 UAC 按了「否」。
_SHELL_EXECUTE_SUCCESS_THRESHOLD = 32
_ERROR_CANCELLED = 1223
_SW_SHOWNORMAL = 1


def is_running(timeout=PROBE_TIMEOUT_S):
    """tunneld 是否已經在監聽。"""
    try:
        with socket.create_connection((TUNNELD_HOST, TUNNELD_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _elevated_command():
    """回傳 (要執行的程式, 參數字串, 工作目錄)。"""
    if paths.is_frozen():
        exe_dir = paths.executable_dir()
        return os.path.join(exe_dir, TUNNELD_EXE_NAME), "", exe_dir

    python_exe = sys.executable
    # 從 pythonw.exe 啟動時 sys.executable 也是 pythonw.exe，換回 python.exe 才有主控台。
    if os.path.basename(python_exe).lower() == "pythonw.exe":
        candidate = os.path.join(os.path.dirname(python_exe), "python.exe")
        if os.path.exists(candidate):
            python_exe = candidate
    return python_exe, "-m gps_qt.tunneld", paths.executable_dir()


def launch_elevated():
    """以系統管理員身分啟動 tunneld。回傳 (是否成功, 說明訊息)。"""
    if sys.platform != "win32":
        return False, f"目前平台（{sys.platform}）不支援自動啟動 tunneld，請自行啟動。"

    program, params, workdir = _elevated_command()
    if paths.is_frozen() and not os.path.exists(program):
        return False, f"找不到 {TUNNELD_EXE_NAME}，請確認它與主程式在同一個資料夾。"

    import ctypes

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", program, params or None, workdir, _SW_SHOWNORMAL
    )
    if result > _SHELL_EXECUTE_SUCCESS_THRESHOLD:
        return True, "tunneld 啟動中，請稍候幾秒再按「開始移動」。"
    if result == _ERROR_CANCELLED:
        return False, "已取消系統管理員授權，tunneld 沒有啟動，無法連線 iPhone。"
    return False, f"啟動 tunneld 失敗（ShellExecute 回傳 {result}）。"


def ensure_running():
    """確保 tunneld 在執行，回傳要寫進執行日誌的訊息清單。"""
    if is_running():
        return ["tunneld 已在執行。"]

    messages = ["tunneld 未執行，需要系統管理員權限才能啟動..."]
    _, message = launch_elevated()
    messages.append(message)
    return messages


def run_cli():
    """在這個行程裡直接跑 `pymobiledevice3 remote tunneld`（提權後的子行程用）。"""
    import multiprocessing

    multiprocessing.freeze_support()

    from pymobiledevice3.__main__ import main as pymobiledevice3_main

    sys.argv = ["pymobiledevice3", "remote", "tunneld"]
    return pymobiledevice3_main()


if __name__ == "__main__":
    sys.exit(run_cli() or 0)
