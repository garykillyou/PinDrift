"""地圖面板：QWebEngineView 載入 web/map.html，外加一排 Qt 原生工具列。

工具列刻意做在 Qt 這一側而不是 HTML 裡：這樣搜尋框、下拉選單、核取方塊都
直接吃 qt-material 的樣式，跟其他面板長得一樣，不必在 map.css 裡另外複製
一套跟著主題切換的控制項樣式。

與頁面之間所有溝通都經過 MapBridge（見 gps_qt/map_bridge.py）。頁面載入是
非同步的，所以每一項狀態都先存在這裡，等頁面回報 map_ready 之後再一次推過去
（_on_map_ready），之後的變動才即時送出。
"""

from PySide6.QtCore import QFile, QIODevice, QTimer, QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QInputDialog, QLineEdit, QMenu,
    QPushButton, QSizePolicy, QVBoxLayout,
)

from .. import paths, theme
from ..geocode import Geocoder
from ..map_bridge import MapBridge, bounds_payload, favorites_payload, route_payload
from .route_planner import RoutePlanner

MAP_HTML = paths.resource_path("web", "map.html")

MAP_MIN_HEIGHT = 320
# 工具列、路徑規劃列與地圖之間的間隔。Qt 預設的 6px 讓路徑規劃列的下緣框線
# 幾乎貼著地圖，兩者之間需要看得出來的呼吸空間。
ROW_SPACING = 8
SEARCH_BOX_MIN_WIDTH = 180
MENU_ITEM_MAX_CHARS = 70

AUTO_TILE = "auto"
CUSTOM_TILE = "custom"

# (設定值, 下拉選單文字, URL 樣板, 版權標示)
# Leaflet 原生支援 {s}（子網域）與 {r}（高解析度後綴），不需要自己展開。
TILE_SOURCES = [
    (AUTO_TILE, "圖磚：自動（跟隨主題）", "", ""),
    ("osm", "圖磚：OpenStreetMap",
     "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
     "&copy; OpenStreetMap contributors"),
    ("positron", "圖磚：CartoDB Positron（淺）",
     "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
     "&copy; OpenStreetMap contributors &copy; CARTO"),
    ("dark", "圖磚：CartoDB Dark Matter（深）",
     "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
     "&copy; OpenStreetMap contributors &copy; CARTO"),
    (CUSTOM_TILE, "圖磚：自訂 URL…", "", ""),
]
TILE_BY_KEY = {entry[0]: entry for entry in TILE_SOURCES}

# 「自動」時依主題挑一組對比合適的圖磚：深色主題配深色圖磚，標記才不會刺眼。
THEME_TILE = {"dark": "dark", "light": "positron"}


def _read_qt_resource(path):
    """讀出 Qt 內建資源檔的文字內容，讀不到回傳 None。"""
    handle = QFile(path)
    if not handle.open(QIODevice.OpenModeFlag.ReadOnly):
        return None
    try:
        return bytes(handle.readAll().data()).decode("utf-8")
    finally:
        handle.close()


class MapPanel(QFrame):
    """地圖面板。對外只暴露「設定地圖狀態」的方法與「使用者在地圖上做了什麼」的
    signal，由 MainWindow 決定要怎麼套用到路線模型或固定座標欄位。"""

    map_clicked = Signal(float, float)
    point_moved = Signal(int, float, float)
    point_delete_requested = Signal(int)
    pin_dragged = Signal(float, float)
    favorite_activated = Signal(int)
    location_searched = Signal(float, float, str)
    route_computed = Signal(list)  # 路徑規劃算出的完整路線 [[lat, lon, note], ...]
    simplify_requested = Signal(float)  # 手動簡化目前路線，參數是容差（公尺）
    log = Signal(str)

    def __init__(self, map_settings, theme_name, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self._settings = map_settings
        self._theme_name = theme_name

        self._ready = False
        self._route = []
        self._pin = None
        self._mode = "route"
        self._locked = False
        self._favorites_json = "[]"
        self._route_push_pending = False

        layout = QVBoxLayout(self)
        layout.setSpacing(ROW_SPACING)
        layout.addLayout(self._build_toolbar())

        # 路徑規劃只在路線模式有意義，所以獨立成第二列、切到固定定位時整列隱藏；
        # 全部擠成一列的話控制項太多，視窗一窄就被壓扁。
        self.route_planner = RoutePlanner(self._settings)
        self.route_planner.log.connect(self.log)
        self.route_planner.route_computed.connect(self.route_computed)
        self.route_planner.simplify_requested.connect(self.simplify_requested)
        self.route_planner.pick_state_changed.connect(self._on_pick_state_changed)
        layout.addWidget(self.route_planner)

        self._build_view()
        layout.addWidget(self.view, 1)

        self._geocoder = Geocoder(self)
        self._geocoder.results_ready.connect(self._on_search_results)
        self._geocoder.failed.connect(self.log)

    # ── UI 組裝 ────────────────────
    def _build_toolbar(self):
        row = QHBoxLayout()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜尋地名後跳至該位置")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(SEARCH_BOX_MIN_WIDTH)
        self.search_edit.returnPressed.connect(self._do_search)
        row.addWidget(self.search_edit, 1)

        search_btn = QPushButton("搜尋")
        search_btn.clicked.connect(self._do_search)
        row.addWidget(search_btn)

        self.tile_combo = QComboBox()
        for entry in TILE_SOURCES:
            self.tile_combo.addItem(entry[1], entry[0])
        self._select_tile_in_combo(self._settings.get("tile_source", AUTO_TILE))
        theme.fit_combo_width(self.tile_combo)
        self.tile_combo.currentIndexChanged.connect(self._on_tile_selected)
        row.addWidget(self.tile_combo)

        self.follow_check = QCheckBox("跟隨目前位置")
        self.follow_check.setChecked(bool(self._settings.get("follow", True)))
        self.follow_check.toggled.connect(self._on_follow_toggled)
        row.addWidget(self.follow_check)

        clear_btn = QPushButton("清除軌跡")
        theme.mark_class(clear_btn, "no-uppercase")
        clear_btn.clicked.connect(self.clear_trail)
        row.addWidget(clear_btn)
        return row

    def _build_view(self):
        self.view = QWebEngineView(self)
        self.view.setMinimumHeight(MAP_MIN_HEIGHT)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        page = self.view.page()
        # map.html 是 file:// 頁面，而圖磚來自 https；不打開這個屬性的話
        # Chromium 會擋掉所有圖磚請求，地圖會是一片空白且沒有任何錯誤訊息。
        page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

        self.bridge = MapBridge(self)
        self.channel = QWebChannel(page)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)
        self._inject_webchannel_script(page)

        self.bridge.map_ready.connect(self._on_map_ready)
        self.bridge.map_clicked.connect(self._on_map_clicked)
        self.bridge.point_dragged.connect(self.point_moved)
        self.bridge.point_delete_requested.connect(self.point_delete_requested)
        self.bridge.pin_dragged.connect(self.pin_dragged)
        self.bridge.favorite_activated.connect(self.favorite_activated)
        self.bridge.view_changed.connect(self._on_view_changed)
        self.bridge.follow_disengaged.connect(self._on_follow_disengaged)
        self.bridge.js_error.connect(lambda msg: self.log.emit("地圖 JS 錯誤：" + msg))

        self.view.setUrl(QUrl.fromLocalFile(MAP_HTML))

    def _inject_webchannel_script(self, page):
        """把 qwebchannel.js 注入頁面。

        不從 CDN 抓（要連外），也不用 qrc:///qtwebchannel/qwebchannel.js
        （file:// 頁面讀不到 qrc）；改成從 Qt 資源讀出原始碼，用
        QWebEngineScript 在 DocumentCreation 時機注入，這樣 map.js 執行時
        QWebChannel 這個全域物件一定已經存在。
        """
        source = _read_qt_resource(":/qtwebchannel/qwebchannel.js")
        if source is None:
            self._log_later("地圖：找不到 qwebchannel.js，地圖互動功能將無法運作")
            return
        script = QWebEngineScript()
        script.setName("qwebchannel")
        script.setSourceCode(source)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        page.scripts().insert(script)

    def _log_later(self, message):
        """延到下一輪事件迴圈再發 log：建構期間 MainWindow 還沒 connect 上來。"""
        QTimer.singleShot(0, lambda: self.log.emit(message))

    # ── 對外：設定地圖狀態 ────────────────────
    def set_route(self, points):
        self._route = [list(p) for p in points]
        self._schedule_route_push()

    def set_pin(self, lat, lon):
        self._pin = (lat, lon)
        self._push_pin()

    def set_mode(self, mode):
        self._mode = mode
        self.route_planner.setVisible(mode == "route")
        if mode != "route":
            self.route_planner.cancel()
        self._push_mode()

    def set_locked(self, locked):
        self._locked = locked
        # 模擬移動中地圖不接受點擊，正在進行的路徑點點選流程要跟著中止，
        # 否則按鈕會一直停在「點選中，已選 N 點」卻永遠等不到下一次點擊。
        self.route_planner.setEnabled(not locked)
        if locked:
            self.route_planner.cancel()
        self._push_locked()

    def set_favorites(self, favorites):
        """設定要畫在地圖上的最愛（只有地點最愛會被畫出來，見 favorites_payload）。"""
        self._favorites_json = favorites_payload(favorites)
        self._push_favorites()

    def set_position(self, lat, lon):
        if self._ready:
            self.bridge.position_changed.emit(lat, lon)

    def clear_trail(self):
        if self._ready:
            self.bridge.trail_cleared.emit()

    def fit_to(self, points):
        if self._ready and points:
            self.bridge.fit_bounds.emit(bounds_payload(points))

    def apply_theme(self, theme_name):
        self._theme_name = theme_name
        if self._settings.get("tile_source", AUTO_TILE) == AUTO_TILE:
            self._push_tile()

    # ── 推送到頁面 ────────────────────
    def _schedule_route_push(self):
        # 表格逐格編輯時 dataChanged 會一格發一次，合併成每輪事件迴圈推一次即可。
        if self._route_push_pending:
            return
        self._route_push_pending = True
        QTimer.singleShot(0, self._flush_route_push)

    def _flush_route_push(self):
        self._route_push_pending = False
        self._push_route()

    def _push_route(self):
        if self._ready:
            self.bridge.route_changed.emit(route_payload(self._route))

    def _push_pin(self):
        if self._ready and self._pin is not None:
            self.bridge.pin_changed.emit(self._pin[0], self._pin[1])

    def _push_mode(self):
        if self._ready:
            self.bridge.mode_changed.emit(self._mode)

    def _push_locked(self):
        if self._ready:
            self.bridge.edit_locked.emit(self._locked)

    def _push_favorites(self):
        if self._ready:
            self.bridge.favorites_changed.emit(self._favorites_json)

    def _push_follow(self):
        if self._ready:
            self.bridge.follow_changed.emit(self.follow_check.isChecked())

    def _push_tile(self):
        if self._ready:
            url, attribution = self._current_tile()
            self.bridge.tile_changed.emit(url, attribution)

    def _push_view(self):
        center = self._settings.get("center")
        if not self._ready or not isinstance(center, (list, tuple)) or len(center) != 2:
            return
        self.bridge.view_requested.emit(
            float(center[0]), float(center[1]), int(self._settings.get("zoom", 15))
        )

    def _on_map_ready(self):
        self._ready = True
        # 順序有意義：先定好視野與圖磚，再畫內容，最後才套用鎖定狀態
        # （鎖定會重畫所有節點圖示，必須在節點已經存在之後）。
        self._push_view()
        self._push_tile()
        self._push_mode()
        self._push_route()
        self._push_pin()
        self._push_favorites()
        self._push_follow()
        self._push_locked()

    # ── 工具列事件 ────────────────────
    def _current_tile(self):
        key = self._settings.get("tile_source", AUTO_TILE)
        if key == AUTO_TILE:
            key = THEME_TILE.get(self._theme_name, "osm")
        if key == CUSTOM_TILE:
            url = self._settings.get("custom_tile_url", "")
            if url:
                return url, self._settings.get("custom_attribution", "")
            key = "osm"
        entry = TILE_BY_KEY.get(key) or TILE_BY_KEY["osm"]
        return entry[2], entry[3]

    def _select_tile_in_combo(self, key):
        index = self.tile_combo.findData(key)
        self.tile_combo.blockSignals(True)
        self.tile_combo.setCurrentIndex(index if index >= 0 else 0)
        self.tile_combo.blockSignals(False)

    def _on_tile_selected(self, _index):
        key = self.tile_combo.currentData()
        if key == CUSTOM_TILE and not self._ask_custom_tile_url():
            self._select_tile_in_combo(self._settings.get("tile_source", AUTO_TILE))
            return
        self._settings["tile_source"] = key
        self._push_tile()

    def _ask_custom_tile_url(self):
        url, ok = QInputDialog.getText(
            self, "自訂圖磚",
            "請輸入圖磚 URL 樣板（可用 {s} {z} {x} {y} {r}）：",
            text=self._settings.get("custom_tile_url", ""),
        )
        if not ok or not url.strip():
            return False
        attribution, ok = QInputDialog.getText(
            self, "自訂圖磚", "請輸入版權標示（可留空）：",
            text=self._settings.get("custom_attribution", ""),
        )
        if not ok:
            return False
        self._settings["custom_tile_url"] = url.strip()
        self._settings["custom_attribution"] = attribution.strip()
        return True

    def _on_follow_toggled(self, checked):
        self._settings["follow"] = checked
        self._push_follow()

    def _on_follow_disengaged(self):
        # 使用者在地圖上手動拖動而自動關閉跟隨，把核取方塊同步過來；
        # 不能再推回 JS，否則會跟頁面自己的狀態打架。
        self.follow_check.blockSignals(True)
        self.follow_check.setChecked(False)
        self.follow_check.blockSignals(False)
        self._settings["follow"] = False

    def _on_view_changed(self, lat, lon, zoom):
        self._settings["center"] = [lat, lon]
        self._settings["zoom"] = zoom

    # ── 地圖點擊的分派 ────────────────────
    def _on_map_clicked(self, lat, lon):
        # 路徑規劃正在等起點/終點時，這一下要被它吃掉，不能同時又新增一個座標點。
        if self.route_planner.handle_map_click(lat, lon):
            return
        self.map_clicked.emit(lat, lon)

    def _on_pick_state_changed(self, picking, points_json):
        if self._ready:
            self.bridge.pick_state_changed.emit(picking, points_json)

    # ── 地名搜尋 ────────────────────
    def _do_search(self):
        self._geocoder.search(self.search_edit.text())

    def _on_search_results(self, results):
        if not results:
            self.log.emit("搜尋：找不到符合的地點")
            return
        if len(results) == 1:
            self._goto(results[0])
            return
        menu = QMenu(self)
        for result in results:
            action = menu.addAction(_shorten(result["name"]))
            action.triggered.connect(
                lambda checked=False, item=result: self._goto(item)
            )
        menu.exec(self.search_edit.mapToGlobal(self.search_edit.rect().bottomLeft()))

    def _goto(self, result):
        self.log.emit("搜尋：跳至 " + result["name"])
        self.fit_to([[result["lat"], result["lon"]]])
        self.location_searched.emit(result["lat"], result["lon"], result["name"])


def _shorten(text):
    if len(text) <= MENU_ITEM_MAX_CHARS:
        return text
    return text[:MENU_ITEM_MAX_CHARS] + "…"
