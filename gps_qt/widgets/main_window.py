"""主視窗：整體版面、按鈕狀態機、視窗幾何/主題存讀。

這裡只放 UI 骨架，連線狀態機在 gps_qt/session.py 的 GPSSession。
"""

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSplitter, QStyle, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import applog, geo, persistence, theme, tunneld, window_geometry
from ..close_guard import CloseGuard
from ..session import GPSSession
from .favorites_panel import FavoritesPanel
from .map_panel import MapPanel
from .pin_panel import PinPanel
from .route_panel import DEFAULT_SPEED_KMH, RoutePanel

logger = logging.getLogger(__name__)

DEFAULT_ROUTE = [
    [24.1368, 120.6862, "台中火車站"],
    [24.1390, 120.6800, "台灣大道一段"],
    [24.1420, 120.6720, "台灣大道二段"],
    [24.1470, 120.6640, "台灣大道三段"],
    [24.1520, 120.6560, "台灣大道四段"],
    [24.1560, 120.6480, "近市政府"],
    [24.1590, 120.6430, "勤美誠品"],
]

WIDE_LAYOUT_BREAKPOINT = 1000

# 右欄的垂直配額：地圖是主體，座標面板佔比較小的一塊（可整個收合把空間讓給地圖）。
MAP_STRETCH = 3
COORDS_STRETCH = 2

# 設定變動後最多等這麼久就自動存檔一次。計時器第一次變動時啟動、期間的變動
# 不會重新計時，連續拖曳節點也只會每隔這段時間寫一次檔，而不是永遠等不到空檔。
AUTOSAVE_DELAY_MS = 2000


class MainWindow(QMainWindow):
    def __init__(self, loop=None, startup_messages=()):
        """loop：qasync 的事件迴圈，用來攔截 asyncio 的未處理錯誤。
        startup_messages：main() 在視窗建好之前收集到、要寫進執行日誌的訊息。"""
        super().__init__()
        self.settings, settings_message = persistence.load_settings()
        self.theme_name = self.settings.get("theme", "dark")
        if self.theme_name not in ("dark", "light"):
            self.theme_name = "dark"
        self.mode = "route"

        route = persistence.load_saved_route(self.settings) or [list(r) for r in DEFAULT_ROUTE]
        # 回傳的就是 settings["map"] 本身，MapPanel 會就地更新它，closeEvent 一起寫回。
        self.map_settings = persistence.load_map_settings(self.settings)
        self._coords_collapsed = False

        self.setWindowTitle("PinDrift — iPhone GPS 路線模擬器")
        self.setMinimumSize(window_geometry.MIN_WINDOW_W, window_geometry.MIN_WINDOW_H)
        maximize = window_geometry.restore_geometry(self, self.settings)
        self._normal_geometry = window_geometry.capture_geometry(self)

        # 樣式表要在建立任何子 widget 之前先套用：子 widget 建構時若呼叫
        # sizeHint()/fontMetrics() 依目前樣式決定固定寬度，套用順序反了會用到
        # 「尚未套用 QSS 前」的尺寸，等真正套用樣式表後（padding 變大）就會被裁切。
        theme.apply(QApplication.instance(), self.theme_name)
        self._build_ui(route)
        self._apply_theme()
        # 讀檔時的狀況（壞檔已備份等）要等執行日誌建好才寫得進去。
        for message in (settings_message, self.favorites_panel.load_message, *startup_messages):
            if message:
                self._log(message)
        # 執行日誌建好之後，未處理的例外才能在這裡顯示摘要（main() 先前只寫記錄檔）。
        applog.install_exception_hooks(self._log, loop)

        self.session = GPSSession(
            route_provider=lambda: self.route_panel.route,
            speed_provider=lambda: self.route_panel.speed_ms(),
            pin_provider=lambda: self.pin_panel.coordinates(),
            mode_provider=lambda: self.mode,
            loop_provider=lambda: self.route_panel.loop_enabled(),
            loop_style_provider=lambda: self.route_panel.loop_style(),
        )
        self.session.log.connect(self._log)
        self.session.progress_value.connect(lambda v: self.progress_bar.setValue(int(v * 1000)))
        self.session.progress_label.connect(self.progress_label.setText)
        self.session.paused.connect(self._sync_btn_states)
        # session_ended 發出前 GPSSession 已自行把 pending_action 歸零，這裡只要同步按鈕。
        self.session.session_ended.connect(self._sync_btn_states)
        self.session.direction_changed.connect(self._sync_btn_states)
        self.session.position_changed.connect(self.map_panel.set_position)
        self.session.route_finished.connect(self._on_route_finished)
        self.tray_icon = QSystemTrayIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation), self
        )
        self._close_guard = CloseGuard(
            self.session, self._confirm_close_while_simulating, self.close, self._log, parent=self
        )
        self._connect_map()
        self._setup_autosave()
        self._switch_mode("route")
        self._sync_btn_states()

        if maximize:
            self.showMaximized()
        else:
            self.showNormal()

        # 延到下一輪事件迴圈才檢查 tunneld：提權用的 UAC 對話框會卡住這條執行緒，
        # 先讓視窗畫出來，使用者才看得到自己是在對哪個程式授權。
        QTimer.singleShot(0, self._ensure_tunneld)

    # ── UI 組裝 ────────────────────
    def _build_ui(self, route):
        central = QWidget()
        outer_layout = QVBoxLayout(central)

        title_row = QHBoxLayout()
        title_label = theme.mark_class(QLabel("PinDrift"), "app-title")
        title_row.addWidget(title_label)
        subtitle = QLabel("iPhone iOS 26  ·  需先執行 tunneld")
        title_row.addWidget(subtitle)
        title_row.addStretch(1)
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self._toggle_theme)
        title_row.addWidget(self.theme_btn)
        outer_layout.addLayout(title_row)

        self.splitter = QSplitter(Qt.Horizontal)
        outer_layout.addWidget(self.splitter, 1)

        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("開始移動")
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)
        self.return_btn = QPushButton("往起點")
        self.return_btn.clicked.connect(self._toggle_direction)
        btn_row.addWidget(self.return_btn)
        self.stop_btn = QPushButton("停止")
        theme.mark_class(self.stop_btn, "danger")
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.stop_btn)
        left_layout.addLayout(btn_row)

        self.restore_btn = QPushButton("恢復真實定位")
        self.restore_btn.clicked.connect(self._restore_real_location)
        left_layout.addWidget(self.restore_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        left_layout.addWidget(self.progress_bar)
        self.progress_label = QLabel("")
        left_layout.addWidget(self.progress_label)

        left_layout.addWidget(theme.style_section_title(QLabel("執行日誌")))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        left_layout.addWidget(self.log_view)

        self.favorites_panel = FavoritesPanel(
            pin_provider=lambda: self.pin_panel.coordinates(),
            route_provider=lambda: self.route_panel.route,
            mode_provider=lambda: self.mode,
        )
        self.favorites_panel.load_requested.connect(self._load_favorite)
        left_layout.addWidget(self.favorites_panel)

        self.splitter.addWidget(left_col)

        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)

        mode_row = QHBoxLayout()
        mode_row.addWidget(theme.style_section_title(QLabel("模式選擇")))
        # 用 checkable 按鈕 + 互斥群組取代原本手動切換 QSS 屬性：qt-material 的
        # QPushButton:checked 樣式本身就會用 primaryColor 標示目前選取的模式。
        self.route_mode_btn = QPushButton("路線移動")
        self.route_mode_btn.setCheckable(True)
        self.route_mode_btn.clicked.connect(lambda: self._switch_mode("route"))
        mode_row.addWidget(self.route_mode_btn)
        self.pin_mode_btn = QPushButton("固定定位")
        self.pin_mode_btn.setCheckable(True)
        self.pin_mode_btn.clicked.connect(lambda: self._switch_mode("pin"))
        mode_row.addWidget(self.pin_mode_btn)
        self.mode_btn_group = QButtonGroup(self)
        self.mode_btn_group.setExclusive(True)
        self.mode_btn_group.addButton(self.route_mode_btn)
        self.mode_btn_group.addButton(self.pin_mode_btn)
        mode_row.addStretch(1)
        right_layout.addLayout(mode_row)

        self.map_panel = MapPanel(self.map_settings, self.theme_name)
        right_layout.addWidget(self.map_panel, MAP_STRETCH)

        self.coords_toggle_btn = QPushButton()
        theme.mark_class(self.coords_toggle_btn, "no-uppercase")
        self.coords_toggle_btn.clicked.connect(self._toggle_coords)
        right_layout.addWidget(self.coords_toggle_btn)

        self.pin_panel = PinPanel()
        right_layout.addWidget(self.pin_panel, COORDS_STRETCH)
        speed_kmh = persistence.load_speed_kmh(self.settings, DEFAULT_SPEED_KMH)
        self.route_panel = RoutePanel(route, initial_speed=speed_kmh)
        right_layout.addWidget(self.route_panel, COORDS_STRETCH)

        self.splitter.addWidget(right_col)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        # setStretchFactor 只影響「resize 時多出來的空間」怎麼分配，初始寬度仍要
        # 靠 setSizes() 指定；給兩個相同的大數字，Qt 會依可用空間等比例換算。
        self.splitter.setSizes([10**6, 10**6])

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)

    # ── 主題 ────────────────────
    def _apply_theme(self):
        theme.apply(QApplication.instance(), self.theme_name)
        self.theme_btn.setText("切換淺色" if self.theme_name == "dark" else "切換深色")
        # 圖磚設定為「自動」時要跟著主題換成淺色/深色底圖。
        self.map_panel.apply_theme(self.theme_name)

    def _toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self._apply_theme()
        self.settings["theme"] = self.theme_name
        error = persistence.save_settings(self.settings)
        if error:
            self._log(error)

    # ── 模式切換 ────────────────────
    def _switch_mode(self, mode):
        self.mode = mode
        self.start_btn.setText("開始移動" if mode == "route" else "固定定位")
        self._sync_coord_panels()
        self.map_panel.set_mode(mode)
        self.route_mode_btn.setChecked(mode == "route")
        self.pin_mode_btn.setChecked(mode == "pin")
        self._update_return_btn_state()
        # refresh() 會 emit favorites_changed，順帶更新地圖的最愛圖層（只有 pin 模式有）。
        self.favorites_panel.refresh()

    def _toggle_coords(self):
        self._coords_collapsed = not self._coords_collapsed
        self._sync_coord_panels()

    def _sync_coord_panels(self):
        """依「目前模式」與「是否收合」決定顯示哪一個座標面板。

        這兩個是各自獨立的條件，集中在這裡一起判斷；分散到 _switch_mode() 與
        收合按鈕各自 show()/hide() 的話，收合狀態下切換模式會把面板又叫回來。
        """
        expanded = not self._coords_collapsed
        self.pin_panel.setVisible(expanded and self.mode == "pin")
        self.route_panel.setVisible(expanded and self.mode == "route")
        name = "固定座標" if self.mode == "pin" else "路線座標點"
        self.coords_toggle_btn.setText(("▾ 收合 " if expanded else "▸ 展開 ") + name)

    def _load_favorite(self, fav):
        # 移動中換路線或切到固定定位，地圖與實際走的路線會對不上（清單的「載入」
        # 與地圖上的最愛圓點都走這裡）。
        if self._is_moving():
            self._log("模擬移動中無法載入最愛，請先按「停止」")
            return
        if fav["type"] == "pin":
            self.pin_panel.lat_spin.setValue(fav["lat"])
            self.pin_panel.lon_spin.setValue(fav["lon"])
            self._switch_mode("pin")
            self.map_panel.fit_to([[fav["lat"], fav["lon"]]])
            self._reinject_pin_if_holding()
        else:
            self.route_panel.set_route([list(r) for r in fav["route"]])
            self._switch_mode("route")
            self.map_panel.fit_to([[r[0], r[1]] for r in fav["route"]])
        # 換了地點/路線，先前的軌跡已經沒有參考價值。
        self.map_panel.clear_trail()
        self._log(f"已載入：{fav['name']}")

    # ── 地圖連動 ────────────────────
    def _connect_map(self):
        """把地圖上的操作接到既有的路線模型／固定座標欄位，並讓兩邊互相同步。

        資料 -> 地圖：模型任何變動都回推一次完整路線。回授迴圈由兩層擋住——
        MapPanel 會把同一輪事件迴圈裡的多次推送合併成一次，map.js 再比對
        「JSON 與上次相同就跳過重繪」，所以「推過去又被推回來」不會無限繞。
        """
        self.map_panel.log.connect(self._log)
        self.map_panel.map_clicked.connect(self._on_map_clicked)
        self.map_panel.point_moved.connect(self.route_panel.move_point)
        self.map_panel.point_delete_requested.connect(self.route_panel.delete_point)
        self.map_panel.point_insert_requested.connect(self.route_panel.insert_adjacent)
        self.map_panel.pin_dragged.connect(self._apply_map_coordinates)
        self.map_panel.favorite_activated.connect(self._on_map_favorite_activated)
        self.map_panel.location_searched.connect(self._on_location_searched)
        self.map_panel.route_computed.connect(self._on_route_computed)
        self.map_panel.simplify_requested.connect(self._on_simplify_requested)

        model = self.route_panel.model
        model.dataChanged.connect(self._push_route_to_map)
        model.rowsInserted.connect(self._push_route_to_map)
        model.rowsRemoved.connect(self._push_route_to_map)
        model.modelReset.connect(self._push_route_to_map)
        # modelReset 只有在 set_route()／clear() 時才發出，也就是「整條路線被換掉」
        # 的兩個入口（載入最愛、路徑規劃算完、清空座標點）。舊的已走距離對新路線
        # 沒有意義，不歸零的話按「開始移動」會從新路線的某個中途點開始走。
        model.modelReset.connect(self.session.reset_progress)
        # 快速選擇、貼上座標、打完字都算「座標確定」，保持中就立刻重新注入，
        # 與在地圖上點選的行為一致。
        self.pin_panel.coordinates_committed.connect(self._reinject_pin_if_holding)
        self.pin_panel.lat_spin.valueChanged.connect(self._push_pin_to_map)
        self.pin_panel.lon_spin.valueChanged.connect(self._push_pin_to_map)
        self.favorites_panel.favorites_changed.connect(self._push_favorites_to_map)

        self._push_route_to_map()
        self._push_pin_to_map()

    def _push_route_to_map(self, *_args):
        self.map_panel.set_route(self.route_panel.route)

    def _push_pin_to_map(self, *_args):
        self.map_panel.set_pin(*self.pin_panel.coordinates())

    def _push_favorites_to_map(self):
        # 只有固定定位模式才在地圖上畫最愛，而且只畫地點最愛：路線最愛會是一整條
        # 疊在編輯中路線上的線，分不出哪條是哪條，反而干擾。route 模式送空清單
        # 把圖層清掉。
        favorites = self.favorites_panel.favorites if self.mode == "pin" else []
        self.map_panel.set_favorites(favorites)

    def _on_map_clicked(self, lat, lon):
        if self.mode == "pin":
            self._apply_map_coordinates(lat, lon)
            return
        self.route_panel.add_point_at(lat, lon)

    def _apply_map_coordinates(self, lat, lon):
        self.pin_panel.lat_spin.setValue(lat)
        self.pin_panel.lon_spin.setValue(lon)
        self._reinject_pin_if_holding()

    def _reinject_pin_if_holding(self, *_args):
        """固定定位保持中時改座標就立刻重新注入，讓地圖上點一下人就搬過去。

        _walk_pin() 注入完座標會把 pending_action 設回 "pause"（連線仍然在），
        所以「session_active 且 pending_action 為 pause」就代表正在保持中。
        移動模式（forward/reverse）本來就會被地圖的編輯鎖擋住，走不到這裡。
        座標與上次注入的相同就不再送一次：離開輸入框時即使沒改值也會觸發
        editingFinished，不擋的話每點一下別的地方就多一輪注入與日誌。
        """
        if self.mode != "pin" or not self.session.session_active:
            return
        if self.session.pending_action != "pause":
            return
        if self.pin_panel.coordinates() == self.session.last_position:
            return
        self.session.start_forward()
        self._sync_btn_states()

    def _on_map_favorite_activated(self, index):
        favorites = self.favorites_panel.favorites
        if 0 <= index < len(favorites):
            self._load_favorite(favorites[index])

    def _on_route_computed(self, route):
        """路徑規劃算完，整條取代目前路線。

        set_route() 會觸發 modelReset，路線自然會回推到地圖；這裡另外把視野拉到
        新路線的範圍，並清掉先前的軌跡——路線都換了，舊軌跡已經沒有參考價值。
        開始移動時 RoutePlanner.cancel() 會中止查詢，這裡再擋一次，萬一結果
        仍在移動中送達也不會換掉正在走的路線。
        """
        if self._is_moving():
            self._log("模擬移動中，已忽略路徑規劃結果")
            return
        self.route_panel.set_route([list(point) for point in route])
        self.map_panel.fit_to([[point[0], point[1]] for point in route])
        self.map_panel.clear_trail()

    def _on_simplify_requested(self, tolerance_m):
        """手動簡化目前路線（有備註的點一律保留，見 geo.simplify_route()）。

        走 set_route() 整條替換，所以跟載入最愛一樣會觸發 modelReset 把已走距離
        歸零——點被抽掉後路線長度也會略為改變，舊進度不再精確。路形幾乎不變，
        視野與軌跡都不需要動。點數沒有減少就不替換，免得無謂地歸零進度。
        """
        if self._is_moving():
            return
        route = self.route_panel.route
        simplified = geo.simplify_route(route, tolerance_m)
        if len(simplified) == len(route):
            self._log(f"路線簡化：{len(route)} 點已無可抽稀的點（容差 {tolerance_m:g} 公尺）")
            return
        self.route_panel.set_route(simplified)
        self._log(
            f"路線簡化：{len(route)} 點簡化為 {len(simplified)} 點（容差 {tolerance_m:g} 公尺）"
        )

    def _on_location_searched(self, lat, lon, _name):
        # route 模式只是把視野帶過去，不自動加點——搜尋是為了找路，不是為了加節點。
        if self.mode == "pin":
            self._apply_map_coordinates(lat, lon)

    # ── 控制按鈕 ────────────────────
    def _start(self):
        if self.mode == "route" and len(self.route_panel.route) < 2:
            QMessageBox.critical(self, "錯誤", "請至少設定 2 個路線點")
            return
        # 開始新的一趟之前，先清掉上一趟「已抵達端點」殘留的系統匣通知，
        # 避免使用者誤以為是這趟才剛顯示的。hide() 會讓還在顯示中的
        # balloon/toast 一併消失；_on_route_finished() 需要通知時會再 show()。
        self.tray_icon.hide()
        self._log("固定定位模式啟動..." if self.mode == "pin" else "開始移動...")
        if self.mode == "route":
            # 依目前「切換方向」按鈕設定的方向開始移動；固定定位模式沒有
            # 方向概念，一律往前（start_forward() 內部即固定為 "forward"）。
            self.session.start()
        else:
            self.session.start_forward()
        self._sync_btn_states()

    def _stop(self):
        self.session.stop()
        self._log("停止中...")

    def _toggle_direction(self):
        # 單純切換「下次開始移動」要走的方向，不會啟動移動——真正開始移動
        # 要另外按「開始移動」。移動中會被 _update_return_btn_state() 停用，
        # 理論上按不到，這裡仍防禦性擋一次。
        if self.mode != "route":
            return
        if len(self.route_panel.route) < 2:
            QMessageBox.critical(self, "錯誤", "請至少設定 2 個路線點")
            return
        self.session.toggle_direction()
        self._sync_btn_states()
        if self.session.direction == "reverse":
            self._log("已切換方向：下次開始移動將往起點走")
        else:
            self._log("已切換方向：下次開始移動將往終點走")

    def _restore_real_location(self):
        if not self.session.session_active:
            QMessageBox.information(self, "提示", "目前尚未連線模擬，已經是真實定位")
            return
        if self.session.pending_action in ("forward", "reverse"):
            QMessageBox.warning(self, "警告", "請先按「停止」，再恢復真實定位")
            return
        self.session.restore_real_location()
        self.map_panel.clear_trail()
        self._sync_btn_states()
        self._log("恢復真實定位中...")

    def _on_route_finished(self, message):
        # 用系統匣提示而非 QMessageBox：跳出對話框會搶走焦點、中斷使用者正在
        # 做的其他事（例如全螢幕遊戲），系統匣提示不會 activate 視窗。
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
            self.tray_icon.showMessage(
                "PinDrift", message, QSystemTrayIcon.MessageIcon.Information, 5000
            )

    def _sync_btn_states(self):
        busy = self.session.pending_action in ("forward", "reverse", "disconnect")
        # 固定定位模式啟動後會立刻回到 "pause"（保持在目前座標），此時連線
        # 仍在，「停止」要維持可按，否則會跟 _walk_pin() 的提示訊息互相矛盾。
        holding = self.session.session_active and self.session.pending_action == "pause"
        self.start_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(self.session.pending_action in ("forward", "reverse") or holding)
        # 從未成功連線（尚未按過「開始移動」，或已恢復真實定位斷線）時，
        # 「恢復真實定位」沒有意義，初始化時只留「開始移動」可以點擊。
        self.restore_btn.setEnabled(self.session.session_active and not busy)
        self._update_return_btn_state()
        # 模擬移動中鎖住所有會改路線的入口（地圖、路線表格、模式切換），避免走到
        # 一半路線被改掉；固定定位「保持中」（pending_action 已回到 pause）不算
        # 移動中，仍可在地圖上點選新座標。
        moving = self._is_moving()
        self.map_panel.set_locked(moving)
        self.route_panel.set_locked(moving)
        self.route_mode_btn.setEnabled(not moving)
        self.pin_mode_btn.setEnabled(not moving)

    def _is_moving(self):
        return self.session.pending_action in ("forward", "reverse")

    def _update_return_btn_state(self):
        # 切換方向鈕現在單純切換「下次開始移動」要走的方向，不會觸發移動，
        # 所以不需要等連線／session_active，路線模式下隨時都能切換；但移動中
        # （forward/reverse）或斷線中（disconnect）要停用，避免中途切換造成
        # 「方向」與目前實際走的方向不一致，需要先按「停止」才能再切換。
        # 文字顯示「按下去會變成哪個方向」：目前設定是往起點走（reverse）
        # 就顯示「往終點」，否則顯示「往起點」。
        busy = self.session.pending_action in ("forward", "reverse", "disconnect")
        self.return_btn.setEnabled(self.mode == "route" and not busy)
        self.return_btn.setText("往終點" if self.session.direction == "reverse" else "往起點")

    def _ensure_tunneld(self):
        """tunneld 沒在跑就提權啟動它；結果寫進執行日誌。"""
        for message in tunneld.ensure_running():
            self._log(message)

    def _log(self, msg):
        # 同步寫進記錄檔：使用者回報問題時可以附上，視窗關掉之後也還查得到。
        logger.info(msg)
        self.log_view.appendPlainText(applog.timestamped(msg))

    # ── 視窗幾何記憶 + 響應式版面 ────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.isMaximized():
            self._normal_geometry = window_geometry.capture_geometry(self)
        wide = self.width() >= WIDE_LAYOUT_BREAKPOINT
        new_orientation = Qt.Horizontal if wide else Qt.Vertical
        if self.splitter.orientation() != new_orientation:
            self.splitter.setOrientation(new_orientation)
            # 換方向後舊的 sizes（另一軸的像素）沿用會變成不等寬/不等高，重設成等分。
            self.splitter.setSizes([10**6, 10**6])

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self.isMaximized():
            self._normal_geometry = window_geometry.capture_geometry(self)

    # ── 設定存檔 ────────────────────
    def _setup_autosave(self):
        """路線、速度與地圖設定變動後自動存檔。

        只在關閉視窗時存檔的話，程式當掉或被強制結束就會把上次的路線與設定
        全部弄丟。地圖設定是 MapPanel 就地改 self.map_settings（即
        self.settings["map"]），所以只需要一個 settings_changed 通知。
        """
        self._last_autosave_error = None
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_DELAY_MS)
        self._autosave_timer.timeout.connect(self._autosave)

        model = self.route_panel.model
        for signal in (model.dataChanged, model.rowsInserted, model.rowsRemoved, model.modelReset):
            signal.connect(self._schedule_autosave)
        self.route_panel.speed_spin.valueChanged.connect(self._schedule_autosave)
        self.map_panel.settings_changed.connect(self._schedule_autosave)

    def _schedule_autosave(self, *_args):
        if not self._autosave_timer.isActive():
            self._autosave_timer.start()

    def _autosave(self):
        self._collect_settings()
        error = persistence.save_settings(self.settings)
        # 放在唯讀位置時每次自動存檔都會失敗，同樣的錯誤只講一次，不洗版執行日誌。
        if error and error != self._last_autosave_error:
            self._log("自動儲存設定失敗：" + error)
        self._last_autosave_error = error

    def _collect_settings(self):
        """把只存在 widget 上的狀態（視窗幾何、路線、速度）寫回 self.settings。"""
        win = dict(self._normal_geometry)
        win["maximized"] = self.isMaximized()
        self.settings["window"] = win
        self.settings["last_route"] = [[r[0], r[1], r[2]] for r in self.route_panel.route]
        self.settings["speed_kmh"] = self.route_panel.speed_spin.value()

    def _confirm_close_while_simulating(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("關閉 PinDrift")
        box.setText("模擬定位仍在進行中。\n關閉前要先恢復 iPhone 的真實定位。")
        restore_btn = box.addButton("恢復真實定位並關閉", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restore_btn)
        box.exec()
        return box.clickedButton() is restore_btn

    def closeEvent(self, event):
        # 模擬進行中先擋下關閉：CloseGuard 詢問後走 restore_real_location()，
        # 等 session_ended（或逾時）再呼叫一次 close()，那時才真的存檔關閉。
        if not self._close_guard.allow_close():
            event.ignore()
            self._sync_btn_states()
            return
        self._autosave_timer.stop()
        self._collect_settings()
        error = persistence.save_settings(self.settings)
        if error:
            # 視窗都要關了，寫進執行日誌等於沒說；但也不攔下關閉動作。
            QMessageBox.warning(self, "設定儲存失敗", error)
        super().closeEvent(event)
