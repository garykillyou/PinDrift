"""路徑規劃工具列：在地圖上依序點選多個路徑點，算出沿道路的路徑取代目前路線。

刻意從 MapPanel 拆出來成獨立 widget：MapPanel 的職責是「顯示地圖並轉發互動」，
而這裡是一組自己的狀態機（點選中 → 查詢中），兩者混在一起會讓 MapPanel 膨脹到
不好讀。MapPanel 只負責把地圖點擊先問過這裡（handle_map_click），被吃掉就不當
成新增座標點。點選數量不固定，靠使用者按「完成規劃」明確結束，而不是像兩點
時那樣點第二下就自動觸發查詢。
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from .. import theme
from ..geo import douglas_peucker
from ..map_bridge import bounds_payload
from ..routing import COSTING_AUTO, COSTING_BICYCLE, COSTING_PEDESTRIAN, Router

# (下拉選單文字, Valhalla 的 costing 值)
COSTING_PRESETS = [
    ("步行", COSTING_PEDESTRIAN),
    ("單車", COSTING_BICYCLE),
    ("開車", COSTING_AUTO),
]
DEFAULT_COSTING = COSTING_PEDESTRIAN

# (下拉選單文字, Douglas-Peucker 容差公尺數)，0 代表不簡化
SIMPLIFY_PRESETS = [
    ("簡化：關閉", 0.0),
    ("簡化：低", 2.0),
    ("簡化：中", 5.0),
    ("簡化：高", 15.0),
]
DEFAULT_SIMPLIFY_M = 5.0

IDLE, PICKING, ROUTING = range(3)

MIN_WAYPOINTS = 2

BUTTON_TEXT = {
    IDLE: "規劃路徑",
    ROUTING: "規劃中…",
}


class RoutePlanner(QWidget):
    # (是否正在點選, 已點選座標的 JSON)：給地圖畫暫時標記與切換游標
    pick_state_changed = Signal(bool, str)
    route_computed = Signal(list)  # [[lat, lon, note], ...]
    simplify_requested = Signal(float)  # 手動簡化目前路線，參數是容差（公尺）
    log = Signal(str)

    def __init__(self, map_settings, parent=None):
        super().__init__(parent)
        self._settings = map_settings
        self._state = IDLE
        self._points = []

        self._router = Router(self)
        self._router.route_ready.connect(self._on_route_ready)
        self._router.failed.connect(self._on_failed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plan_btn = QPushButton()
        theme.mark_class(self.plan_btn, "no-uppercase")
        self.plan_btn.clicked.connect(self._on_plan_clicked)
        layout.addWidget(self.plan_btn)

        self.finish_btn = QPushButton("完成規劃")
        theme.mark_class(self.finish_btn, "no-uppercase")
        self.finish_btn.clicked.connect(self._on_finish_clicked)
        layout.addWidget(self.finish_btn)

        layout.addWidget(QLabel("移動方式："))
        self.costing_combo = _build_combo(
            COSTING_PRESETS, self._settings.get("routing_costing"), DEFAULT_COSTING
        )
        self.costing_combo.currentIndexChanged.connect(self._on_costing_changed)
        layout.addWidget(self.costing_combo)

        self.simplify_combo = _build_combo(
            SIMPLIFY_PRESETS, self._settings.get("simplify_m"), DEFAULT_SIMPLIFY_M
        )
        self.simplify_combo.currentIndexChanged.connect(self._on_simplify_changed)
        layout.addWidget(self.simplify_combo)

        # 下拉選單只影響「下一次規劃完」的結果；這顆按鈕用同一個容差，
        # 對目前表格裡的路線（手動點的、載入的最愛、KML 匯入的）再簡化一次。
        self.simplify_btn = QPushButton("簡化目前路線")
        theme.mark_class(self.simplify_btn, "no-uppercase")
        self.simplify_btn.clicked.connect(self._on_simplify_clicked)
        layout.addWidget(self.simplify_btn)

        layout.addStretch(1)
        self._sync_button()

    # ── 狀態機 ────────────────────
    def handle_map_click(self, lat, lon):
        """由 MapPanel 轉發地圖點擊。回傳 True 代表這次點擊已被路徑規劃吃掉，
        呼叫端就不該再把它當成「新增一個座標點」。點選會依序累積，湊滿至少
        MIN_WAYPOINTS 個點後由使用者按「完成規劃」才觸發查詢——多點的情況下
        無法像兩點時那樣靠「點第二下」自動判斷已經點完。"""
        if self._state != PICKING:
            return False
        self._points.append((lat, lon))
        self.log.emit(f"路徑規劃：已選第 {len(self._points)} 點 {lat:.6f}, {lon:.6f}")
        self._sync_button()
        return True

    def cancel(self):
        """取消進行中的點選（切換模式、開始移動等情況）。"""
        if self._state == IDLE:
            return
        self._state = IDLE
        self._points = []
        self._sync_button()

    def _on_plan_clicked(self):
        # 查詢中不接受操作；其餘狀態下這顆按鈕就是「開始點選 / 取消點選」的切換。
        if self._state == ROUTING:
            return
        if self._state == IDLE:
            self._state = PICKING
            self._points = []
            self.log.emit(f"路徑規劃：請依序點選路徑點（至少 {MIN_WAYPOINTS} 點），完成後按「完成規劃」")
        else:
            self._state = IDLE
            self._points = []
            self.log.emit("路徑規劃：已取消")
        self._sync_button()

    def _on_finish_clicked(self):
        if self._state != PICKING or len(self._points) < MIN_WAYPOINTS:
            return
        waypoints = self._points
        self._state = ROUTING
        self._sync_button()
        self.log.emit(f"路徑規劃：已選 {len(waypoints)} 點，計算沿道路的路徑中…")
        self._router.route(waypoints, self.costing_combo.currentData())

    def _sync_button(self):
        if self._state == PICKING:
            self.plan_btn.setText(f"點選中，已選 {len(self._points)} 點（再按一次取消）")
        else:
            self.plan_btn.setText(BUTTON_TEXT[self._state])
        self.plan_btn.setEnabled(self._state != ROUTING)
        self.finish_btn.setVisible(self._state == PICKING)
        self.finish_btn.setEnabled(len(self._points) >= MIN_WAYPOINTS)
        # 查詢中不能簡化：結果回來會整條取代路線，簡化了也白做；
        # 容差為 0（簡化：關閉）時按下去不會有任何效果，直接停用。
        self.simplify_btn.setEnabled(
            self._state != ROUTING and self.simplify_combo.currentData() > 0
        )
        picked = [[lat, lon] for lat, lon in self._points]
        self.pick_state_changed.emit(self._state == PICKING, bounds_payload(picked))

    # ── 查詢結果 ────────────────────
    def _on_route_ready(self, points, length_km, time_sec):
        self._state = IDLE
        self._points = []
        self._sync_button()

        tolerance = self.simplify_combo.currentData()
        simplified = douglas_peucker(points, tolerance)
        route = [[lat, lon, ""] for lat, lon in simplified]
        route[0][2] = "起點"
        route[-1][2] = "終點"

        minutes, seconds = int(time_sec // 60), int(time_sec % 60)
        detail = f"{len(points)} 點簡化為 {len(route)} 點" if tolerance > 0 else f"{len(route)} 點"
        self.log.emit(
            f"路徑規劃完成：{length_km:.2f} 公里，服務估計 {minutes} 分 {seconds} 秒（{detail}）"
        )
        self.route_computed.emit(route)

    def _on_failed(self, message):
        self._state = IDLE
        self._points = []
        self._sync_button()
        self.log.emit(message)

    # ── 下拉選單 ────────────────────
    def _on_costing_changed(self, _index):
        self._settings["routing_costing"] = self.costing_combo.currentData()

    def _on_simplify_changed(self, _index):
        self._settings["simplify_m"] = self.simplify_combo.currentData()
        self._sync_button()

    def _on_simplify_clicked(self):
        tolerance = self.simplify_combo.currentData()
        if self._state == ROUTING or tolerance <= 0:
            return
        self.simplify_requested.emit(tolerance)


def _build_combo(presets, saved_value, default_value):
    """建立下拉選單並選到存檔值；存檔值不合法（手改壞或舊版設定）就退回預設值。"""
    combo = QComboBox()
    for label, value in presets:
        combo.addItem(label, value)
    index = combo.findData(saved_value)
    if index < 0:
        index = combo.findData(default_value)
    combo.blockSignals(True)
    combo.setCurrentIndex(index)
    combo.blockSignals(False)
    return theme.fit_combo_width(combo)
