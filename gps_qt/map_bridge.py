"""地圖頁面（gps_qt/web/map.js）與 Python 之間的 QWebChannel 契約。

分工：
  - MapBridge 的 **signal** 是 Python -> JS，JS 端用 bridge.xxx.connect() 接收。
  - MapBridge 的 **slot**（一律命名為 on_*）是 JS -> Python，JS 直接呼叫；
    slot 收到後再轉成同名去掉 on_ 前綴的 Qt signal，讓 MapPanel 用一般的
    .connect() 接，不必知道自己是被 JavaScript 叫起來的。

payload 序列化刻意抽成模組層級的純函式，方便單獨測試，也讓「payload 裡不能
有每次都變動的欄位」這條規則（見 route_payload 的說明）有個明確的落點。
"""

import json

from PySide6.QtCore import QObject, Signal, Slot


def route_payload(points):
    """把路線座標點序列化成 map.js 的 renderRoute() 期待的 JSON。

    刻意不放流水號、時間戳這類每次都會變的欄位：JS 端靠「與上次收到的 JSON
    字串完全相同就跳過重繪」來擋掉雙向同步的回授迴圈（Python 推路線 -> JS
    重畫 -> 使用者拖曳 -> Python 更新模型 -> 又推路線），payload 只要帶了會
    變動的欄位，這道防護就等於失效。
    """
    return json.dumps(
        {"points": [[float(p[0]), float(p[1]), str(p[2])] for p in points]},
        ensure_ascii=False,
    )


def bounds_payload(points):
    """把座標點序列化成 map.js 的 fitBounds() 期待的 [[lat, lon], ...]。"""
    return json.dumps([[float(p[0]), float(p[1])] for p in points])


def favorites_payload(favorites):
    """挑出「地點最愛」（type 為 pin），序列化成地圖圖層需要的最小欄位集。

    刻意只處理地點最愛：路線最愛畫在地圖上會是一整條疊在編輯中路線上的線，
    兩者很難分辨，實際使用時只是干擾，所以不畫。

    每一筆都帶著 index——也就是它在 FavoritesPanel.favorites 這份完整清單裡的
    原始位置，這樣使用者點地圖上的最愛時，才能對回同一筆資料走既有的載入流程。
    格式不合（缺座標）的資料直接略過，不讓壞資料把整張地圖弄掛。
    """
    items = []
    for index, fav in enumerate(favorites):
        if fav.get("type") != "pin":
            continue
        try:
            items.append({
                "index": index,
                "name": str(fav.get("name", "")),
                "lat": float(fav["lat"]),
                "lon": float(fav["lon"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return json.dumps(items, ensure_ascii=False)


class MapBridge(QObject):
    """註冊到 QWebChannel 的物件（JS 端以 channel.objects.bridge 取得）。"""

    # ── Python -> JS ──
    route_changed = Signal(str)              # route_payload() 的 JSON
    pin_changed = Signal(float, float)
    mode_changed = Signal(str)               # "pin" | "route"
    position_changed = Signal(float, float)  # 模擬中每次注入座標
    trail_cleared = Signal()
    edit_locked = Signal(bool)
    tile_changed = Signal(str, str)          # 圖磚 URL 樣板, 版權標示
    fit_bounds = Signal(str)                 # bounds_payload() 的 JSON
    follow_changed = Signal(bool)
    favorites_changed = Signal(str)          # favorites_payload() 的 JSON
    view_requested = Signal(float, float, int)
    # 路徑規劃的點選狀態：(是否正在點選, 已點選座標的 bounds_payload JSON)
    pick_state_changed = Signal(bool, str)

    # ── JS -> Python（由下方對應的 on_* slot 轉發） ──
    map_clicked = Signal(float, float)
    point_dragged = Signal(int, float, float)
    point_delete_requested = Signal(int)
    point_insert_requested = Signal(int, bool)  # 節點序號, 是否插在後面
    pin_dragged = Signal(float, float)
    favorite_activated = Signal(int)
    view_changed = Signal(float, float, int)
    follow_disengaged = Signal()
    map_ready = Signal()
    js_error = Signal(str)

    @Slot(float, float)
    def on_map_clicked(self, lat, lon):
        self.map_clicked.emit(lat, lon)

    @Slot(int, float, float)
    def on_point_dragged(self, index, lat, lon):
        self.point_dragged.emit(index, lat, lon)

    @Slot(int)
    def on_point_delete_requested(self, index):
        self.point_delete_requested.emit(index)

    @Slot(int, bool)
    def on_point_insert_requested(self, index, after):
        self.point_insert_requested.emit(index, after)

    @Slot(float, float)
    def on_pin_dragged(self, lat, lon):
        self.pin_dragged.emit(lat, lon)

    @Slot(int)
    def on_favorite_activated(self, index):
        self.favorite_activated.emit(index)

    @Slot(float, float, int)
    def on_view_changed(self, lat, lon, zoom):
        self.view_changed.emit(lat, lon, zoom)

    @Slot()
    def on_follow_disengaged(self):
        self.follow_disengaged.emit()

    @Slot()
    def on_map_ready(self):
        self.map_ready.emit()

    @Slot(str)
    def on_js_error(self, message):
        self.js_error.emit(message)
