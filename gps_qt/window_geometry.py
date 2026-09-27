"""視窗位置記憶：大小/座標/是否最大化存在 settings 的 "window" 欄位。

用 Qt 的 QScreen API 判斷座標是否落在任何一台螢幕內，不需要 ctypes
呼叫 Win32 MonitorFromPoint；Qt6 的 QWidget.geometry() 與
QScreen.availableGeometry() 都是邏輯像素，也不需要手動做實體/邏輯
像素換算。
"""

import math

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication

DEFAULT_WINDOW_W = 1500
DEFAULT_WINDOW_H = 820
MIN_WINDOW_W = 560
MIN_WINDOW_H = 360


def point_on_any_screen(x, y):
    """(x, y)（邏輯像素）是否落在目前接上的任何一台螢幕內。

    找不到設定或螢幕已拔掉/解析度變了時，呼叫端應該放棄還原座標、
    只套用大小，位置交給作業系統決定。
    """
    return QGuiApplication.screenAt(QPoint(int(x), int(y))) is not None


def _as_int(value, default):
    """有限的數值轉成 int（QWidget.resize()／move() 不收 float），其餘回傳 default。

    bool 是 int 的子類別，true/false 不能被當成像素值。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return int(value)


def normalize_window(raw):
    """把 settings["window"] 整理成 {width, height, x, y, maximized}，不改動輸入。

    型別不對的欄位換成預設值：width/height 用預設大小，x/y 為 None 代表位置交給
    作業系統決定，maximized 預設為 True（與第一次啟動相同）。手改壞的設定檔
    不能讓程式開不起來——字串寬度會讓 max() 丟 TypeError，而 bool("false") 是 True。
    """
    win = raw if isinstance(raw, dict) else {}
    maximized = win.get("maximized")
    return {
        "width": _as_int(win.get("width"), DEFAULT_WINDOW_W),
        "height": _as_int(win.get("height"), DEFAULT_WINDOW_H),
        "x": _as_int(win.get("x"), None),
        "y": _as_int(win.get("y"), None),
        "maximized": maximized if isinstance(maximized, bool) else True,
    }


def restore_geometry(window, settings):
    """依 settings["window"] 還原視窗大小/位置/是否最大化。

    回傳 True 代表視窗啟動後應該呼叫 showMaximized()，否則呼叫 showNormal()。
    找不到設定（第一次啟動）時 fallback 回預設大小 + 最大化，與原本行為一致。
    """
    win = normalize_window(settings.get("window"))
    window.resize(max(win["width"], MIN_WINDOW_W), max(win["height"], MIN_WINDOW_H))
    x, y = win["x"], win["y"]
    if x is not None and y is not None and point_on_any_screen(x, y):
        window.move(x, y)
    return win["maximized"]


def capture_geometry(window):
    """讀取視窗目前的大小/座標/是否最大化，回傳可直接存進 settings["window"] 的 dict。

    只有在「非最大化」狀態下的座標才有意義（最大化時的幾何是相對於當下螢幕算出來的，
    不能當作下次還原的基準），所以呼叫端應該只在 window.isMaximized() 為 False 時
    記錄 x/y；這裡一律回傳目前狀態，由呼叫端決定何時要更新記錄。
    """
    geo = window.geometry()
    return {
        "width": geo.width(),
        "height": geo.height(),
        "x": geo.x(),
        "y": geo.y(),
        "maximized": window.isMaximized(),
    }
