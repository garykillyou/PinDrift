# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

PinDrift 是一個 Python 桌面工具，透過 `pymobiledevice3` 模擬 iPhone（iOS 26）的 GPS 定位，
免越獄、免 iTunes，僅需 USB 連線。GUI 用 **PySide6 + qasync + qt-material**
（[gps_qt/](gps_qt) 套件，套件名沿用舊名未改），進入點為 `gps_qt/main.py`。

座標可以直接在內嵌的 Leaflet 地圖上點選、拖曳、刪除（[gps_qt/web/](gps_qt/web)），
移動中還會即時畫出目前位置與已走軌跡。

狀態存在兩個 JSON 檔（皆已列入 `.gitignore`），位置由 [paths.py](gps_qt/paths.py) 的
`data_file()` 決定：一律放在執行檔所在的資料夾（直接跑原始碼時是專案根目錄），
整包搬走設定就跟著走。`save_settings()`／`save_favorites()` 共用的 `_write_json()`
**只攔 `OSError` 並回傳錯誤訊息字串（成功回傳 `None`）**，不丟例外——放在唯讀位置時
存檔失敗不能讓 `closeEvent()` 整個炸掉；序列化失敗則照常拋 `TypeError`，那是程式的 bug。
三個呼叫端各自決定提示方式：切換主題走執行日誌、存最愛與關閉視窗走 `QMessageBox`
（視窗都要關了，寫進日誌等於沒說）。新增存檔入口時要記得接這個回傳值：
- `pindrift_favorites.json`：最愛地點／路線（`{"type": "pin"|"route", "name", ...}` 陣列）。
- `pindrift_settings.json`：`theme`（主題偏好）、`window`（視窗幾何 + `maximized`）、
  `last_route`（上次的路線座標點）、`speed_kmh`（上次的移動速度）、
  `map`（地圖的 `tile_source`／`custom_tile_url`／`custom_attribution`／`center`／`zoom`／`follow`／
  `routing_costing`／`simplify_m`，由 `persistence.load_map_settings()` 補齊預設值）。

## 常用指令

```bash
# 安裝相依套件
pip install -r requirements.txt

# 執行 App（tunneld 會自動偵測並提權啟動，見下方說明）
python -m gps_qt.main

# 手動啟動 tunneld（需「系統管理員」終端機，建立 iOS 26 的 RemoteXPC 加密通道）
python -m pymobiledevice3 remote tunneld

# 執行測試（只涵蓋純邏輯：geo、map_bridge payload、geocode 解析、routing polyline、設定正規化、存檔失敗處理）
pip install -r requirements-dev.txt
python -m pytest

# 打包成可直接交付的資料夾（產出 dist/PinDrift/，約 510 MB）
pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean PinDrift.spec
```

一般情況下不需要手動跑 tunneld：App 啟動後 [MainWindow._ensure_tunneld()](gps_qt/widgets/main_window.py)
會呼叫 [tunneld.py](gps_qt/tunneld.py) 偵測 `127.0.0.1:49151` 是否已經有人在聽，沒有的話用
`ShellExecuteW` 的 `runas` 動詞以系統管理員身分啟動（會跳 UAC），結果寫進執行日誌。
提權的對象由 `_elevated_command()` 依「是否已凍結」分成兩條路：未凍結時跑
`python.exe -m gps_qt.tunneld`（**刻意把 `pythonw.exe` 換回 `python.exe`**，開發時才看得到
tunneld 的主控台輸出），已凍結時跑同一個資料夾裡的 `PinDrift-tunneld.exe`——打包後使用者的
機器上沒有 Python，`python -m pymobiledevice3 ...` 那條路整條斷掉。
[run.bat](run.bat) 因此只剩「用 `pythonw` 開 App」一件事。

測試只涵蓋不需要 Qt 事件迴圈的純函式（[tests/](tests)），Widget 與地圖頁面沒有自動化測試；
專案沒有 lint 設定，也沒有 CI。

## 架構重點

### 檔案地圖
```
PinDrift/
├── run.bat                # 啟動捷徑：用 pythonw 開 App（tunneld 交給 tunneld.py）
├── build.bat              # 打包捷徑：裝相依 + 跑 PyInstaller
├── PinDrift.spec          # PyInstaller 設定（onedir，兩個執行檔共用 _internal）
├── app_entry.py           # 打包用的主程式進入點（PyInstaller 只吃腳本不吃模組）
├── tunneld_entry.py       # 打包用的 tunneld 進入點（console 模式的第二個執行檔）
├── requirements.txt       # 執行 App 需要的相依套件
├── requirements-dev.txt   # 測試相依（pytest）
├── requirements-build.txt # 打包相依（pyinstaller）
├── .gitattributes         # vendored 的 Leaflet 檔案排除行尾轉換（見下方地圖面板）
├── LICENSE                # MIT 授權條款全文
├── conftest.py            # 讓 pytest 把根目錄加進 sys.path
├── tests/                 # 純函式測試（不需要 Qt 事件迴圈）
└── gps_qt/
    ├── main.py              # 進入點：QApplication + qasync 事件迴圈
    ├── paths.py             # 資源／使用者資料的路徑解析（打包後兩者要分開）
    ├── tunneld.py           # tunneld 偵測 + 提權啟動；也是 tunneld 子行程的本體
    ├── theme.py             # qt-material 主題套用、字級覆寫、danger/success 語意色
    ├── geo.py               # haversine()、interpolate_points()、douglas_peucker()、
    │                        # cumulative_distances()／index_at_distance()（進度換算）
    ├── persistence.py       # JSON 存讀 + KML 解析 + 地圖設定正規化
    ├── window_geometry.py   # 視窗位置記憶（QScreen API）
    ├── session.py           # GPSSession：連線狀態機（pending_action 設計）
    ├── models.py            # RouteTableModel + DeleteButtonDelegate（路線表格虛擬化）
    ├── map_bridge.py        # QWebChannel 契約（MapBridge）+ payload 序列化純函式
    ├── geocode.py           # Nominatim 地名搜尋（Python 端發送，符合使用政策）
    ├── routing.py           # Valhalla 路徑規劃 + polyline6 解碼
    ├── web/                 # 地圖頁面（QWebEngineView 以 file:// 載入）
    │   ├── map.html / map.css / map.js
    │   └── vendor/          # Leaflet 1.9.4 本地副本（不依賴 CDN）
    └── widgets/
        ├── main_window.py      # 整體版面、控制按鈕狀態機、模式切換、地圖連動
        ├── map_panel.py        # QWebEngineView + Qt 原生工具列（搜尋/圖磚/跟隨/清軌跡）
        ├── route_planner.py    # 路徑規劃工具列：依序點選多個路徑點 → 算出沿道路的路線
        ├── pin_panel.py        # 固定定位模式面板（含座標貼上攔截）
        ├── route_panel.py      # 路線模式面板（速度設定 + 路線表格）
        └── favorites_panel.py  # 最愛清單
```

### 執行流程（連接 iPhone 的關鍵鏈路，長連線架構）
1. `tunneld` 必須以系統管理員權限先啟動（App 開起來時 `_ensure_tunneld()` 會自動處理，
   或手動跑 `python -m pymobiledevice3 remote tunneld`），建立 iOS 26 的 RemoteXPC 通道。
2. 按「開始移動」時，[session.py](gps_qt/session.py) 的 `GPSSession._session_main()` 用 `asyncio.ensure_future()` 建立一個常駐 task，`async with DvtProvider(rsd) as dvt, LocationSimulation(dvt) as sim:` 開一次連線後就常駐在 while 迴圈裡；後續按「停止」都**不會**重建 task 或重新連線，只是改變 `self.pending_action` 這個共享狀態（`"forward" | "reverse" | "pause" | "disconnect"`），由 while 迴圈讀取並分派動作。「往起點／往終點」（切換方向）本身**不會**碰觸 `pending_action`，只改變下面提到的 `self.direction`。
3. 直到 `pending_action == "disconnect"`（使用者按「恢復真實定位」）才 `break` 出迴圈、呼叫 `sim.clear()` 並讓 `async with` 關閉連線——恢復真實 GPS 只會在明確斷線時發生，單純停止都仍保持模擬連線在目前座標。
4. 座標注入本身是 `sim.set(lat, lon)`，呼叫位置在 `_walk_route()` / `_walk_pin()` 這兩個由 `_session_main()` 依 `pending_action` 呼叫的協程裡。
5. `_session_main()` 的 `try/finally` **包住整個函式主體**，不是只包 `async with` 那一段（修過的 bug）：
   匯入失敗／tunneld 連線失敗／找不到裝置這些提早 `return` 的分支也必須重設 `session_active` 並 emit
   `session_ended`，否則 UI 會卡在按下「開始移動」當下的忙碌狀態，連「停止」都救不回來——那時
   `_session_main()` 早已結束，沒有任何 task 在讀 `pending_action`，而 `_stop()` 本身也不會主動同步按鈕狀態。

### 兩種模式（由 `MainWindow.mode` 控制，動作由 `pending_action` 驅動）
- **路線模式（route）**：`_walk_route(sim, direction)` 中 `direction=1` 往終點走、`direction=-1` 往起點走回去。
  方向與移動是兩個分開的動作：`GPSSession.toggle_direction()`（由「往起點／往終點」按鈕觸發）**單純
  切換** `self.direction`（`"forward"` / `"reverse"`），不會碰 `pending_action`、也不會啟動 task，
  純粹只是記錄「下次按開始移動要往哪走」；`GPSSession.start()`（由「開始移動」按鈕觸發）才會把
  `pending_action` 設成目前的 `self.direction` 並真正開始移動。UI 在移動中（`pending_action` 為
  `forward`/`reverse`）或斷線中（`disconnect`）會停用切換方向按鈕，要先「停止」才能再切方向。
  `interpolate_points()` 依 `haversine()` 算出的距離與設定速度（UI 以 km/h 輸入，經 `speed_ms()` 換算成
  m/s）把路線切成每秒一個內插點。**進度記在 `travelled_m`（已走到路線的第幾公尺），不是「第幾個內插
  點」**（修過的 bug）：內插點的數量由速度決定，停止期間改過速度後同一個索引對到的位置完全不同，而
  `min(idx, total - 1)` 這種夾取會把超出範圍的索引直接夾到最後一點——實測 2.2 公里的路線以 5 km/h 走到
  中途是第 794 個點（共 1589 個），改成 60 km/h 後只剩 134 個點，再按「開始移動」人就瞬移到終點。距離
  與速度無關，所以 `_walk_route()` 的每一輪都重算 `geo.cumulative_distances()`，再用
  `geo.index_at_distance()`（二分搜尋取最接近者）把 `travelled_m` 換算成這份內插結果裡的索引；中斷
  （停止／斷線）時會停在原地，之後從該處繼續。整條路線被換掉時則由 `GPSSession.reset_progress()` 歸零
  ——舊的已走距離對新路線沒有意義。觸發點是 `RouteTableModel` 的 `modelReset`，它只在 `set_route()`／
  `clear()` 發出，剛好對應「載入最愛」「路徑規劃算完」「清空座標點」三個整條替換的入口，不會被單點
  編輯誤觸。新增任何會整批換掉路線的入口時，要確認它有走到 `set_route()`／`clear()`。
  循環模式不是在進入 `_walk_route()` 時快取的：**每次抵達端點才即時讀取** `loop_provider()` 與
  `loop_style_provider()`，因此使用者中途勾選／切換走法會在下一次抵達端點時生效。循環有兩種走法
  （[route_panel.py](gps_qt/widgets/route_panel.py) 的 `loop_style_combo`，僅在勾選循環模式時才啟用）：
  - **來回（bounce）**：抵達端點折返，方向反轉，會一併更新 `direction`（區域變數）、`action_name`、
    `pending_action` 與 `self.direction`（記錄用），並 emit `direction_changed`，讓按鈕文字跟著改成
    新的方向。
  - **迴圈（circuit）**：方向不變，索引直接瞬移回路線另一端（往終點走完就跳回 `0`，往起點走完就跳
    回 `total - 1`，`travelled_m` 一併更新成該點的累積距離）再繼續走，模擬繞圈；不改 `direction`／
    `self.direction`，也不 emit `direction_changed`，因為方向本身沒有變。
- **固定定位模式（pin）**：`_walk_pin(sim)` 呼叫一次 `sim.set(lat, lon)` 後立刻把 `pending_action` 設回 `"pause"`，讓外層 while 迴圈進入 `await asyncio.sleep(0.2)` 的閒置分支，藉此在同一條長連線上「保持」定位，直到使用者按「停止」（其實已經是 pause 狀態，UI 只更新按鈕）或「恢復真實定位」。

### 地圖面板：QWebEngineView + Leaflet + QWebChannel
右欄以地圖為主體（[map_panel.py](gps_qt/widgets/map_panel.py)），座標面板在下方可整個收合。

**溝通契約**全部走 [map_bridge.py](gps_qt/map_bridge.py) 的 `MapBridge`：signal 是 Python → JS
（JS 端 `bridge.xxx.connect()`），slot 一律命名為 `on_*` 是 JS → Python（slot 收到後轉成去掉
`on_` 前綴的同名 Qt signal，讓 `MapPanel` 用一般的 `.connect()` 接）。新增任何互動時兩邊都要成對加。
payload 一律由模組層級的純函式序列化（`route_payload()`／`bounds_payload()`／`favorites_payload()`），
所以不開 Qt 也能單獨測試。`map.js` 的 `window.onerror` 會經由 `on_js_error` 回報到執行日誌——
地圖是另一個執行環境，沒有這條線的話 JS 出錯在 Python 這邊完全看不到，只會看到地圖「沒有反應」。

- **回授迴圈防護（最容易踩的坑）**：模型變動會回推整條路線給地圖，而地圖拖曳又會回寫模型。
  兩層擋住：(a) `MapPanel._schedule_route_push()` 用 `QTimer.singleShot(0)` 把同一輪事件迴圈的
  多次推送合併成一次；(b) `map.js` 的 `renderRoute()` 比對「JSON 與上次收到的完全相同就跳過重繪」。
  因此 **`route_payload()` 絕對不能加流水號、時間戳這類每次都會變的欄位**，加了 (b) 就失效。
  另外節點拖曳只在 `dragend` 通知 Python（`drag` 過程僅在本地更新折線），確保回推一定發生在
  拖曳結束後，不會把正在拖的 marker 重建掉。
- **marker 一律用 `draggable: true` 建立，再視情況 `dragging.disable()`**：Leaflet 只有在建構時
  `options.draggable` 為真才會建立 `marker.dragging` handler，用 `false` 建立的 marker 之後
  再也無法啟用拖曳。編輯鎖切換只呼叫 `enable()`/`disable()`，不重建 marker。
- **頁面是非同步載入的**：`MapPanel` 的每一項狀態都先存成成員變數，等頁面回報 `map_ready`
  才在 `_on_map_ready()` 一次推過去（順序有意義：先視野與圖磚，再畫內容，最後才套鎖定狀態——
  鎖定會把節點圖層整層拿掉，必須在節點已存在之後）。之後的變動才即時送出。
- **三個查證過的載入陷阱**：
  1. `main.py` 必須在建立 `QApplication` **之前** `import PySide6.QtWebEngineWidgets`，Qt 6 要在
     那時候設好 `AA_ShareOpenGLContexts`，順序反了會直接中止。那行 import 看起來沒用到但不能刪。
  2. `qwebchannel.js` 不從 CDN 抓，也不能用 `qrc:///qtwebchannel/qwebchannel.js`（`file://` 頁面
     讀不到 qrc）；改成 `QFile(":/qtwebchannel/qwebchannel.js")` 讀出原始碼，用 `QWebEngineScript`
     在 `DocumentCreation` 時機注入，`map.js` 執行時 `QWebChannel` 才一定已存在。
  3. `map.html` 是 `file://` 頁面而圖磚來自 https，必須打開
     `QWebEngineSettings.LocalContentCanAccessRemoteUrls`，否則圖磚全被擋掉而且**沒有任何錯誤訊息**。
- **工具列刻意做在 Qt 這一側**而不是 HTML 裡，這樣搜尋框/下拉選單/核取方塊直接吃 qt-material
  的樣式，不必在 `map.css` 裡再複製一套跟著主題切換的控制項樣式。
  面板內三列（工具列／路徑規劃列／地圖）的間距用 `ROW_SPACING`(8)，不是 Qt 預設的 6——
  預設值會讓路徑規劃列的下緣框線幾乎貼著地圖，看起來像被地圖蓋掉（修過的 bug）。
- **編輯鎖**：`_sync_btn_states()` 在 `pending_action` 為 `forward`/`reverse` 時送 `edit_locked(True)`。
  鎖定時 `map.js` 的 `setLocked()` 會把 `routeMarkerLayer`（節點專用的子圖層）從 `routeLayer` 移除，
  移動中地圖上只剩路徑線與軌跡；解鎖再把整層加回去，節點不需要重建。所以節點一律加到
  `routeMarkerLayer` 而不是 `routeLayer`，否則路徑線會跟著一起被藏掉。
  固定定位「保持中」（`_walk_pin()` 注入完已把 `pending_action` 設回 `pause`）**不算移動中**，
  此時在地圖上點新座標會由 `_reinject_pin_if_holding()` 立刻重新注入一次，人就直接搬過去。
- **軌跡**：`session.position_changed` 每次 `sim.set()` 後 emit，`map.js` 用 `polyline.addLatLng()`
  累加；超過 `TRAIL_MAX_POINTS`(3000) 就每兩點抽一點，循環模式跑整夜也不會累積出巨大的 polyline。
- **跟隨**：使用者手動拖動地圖（`dragstart`）會自動關閉跟隨並回報 Python 同步核取方塊；
  `panTo()` 不觸發 `dragstart`，所以程式自己的平移不會誤關。
- **圖磚**：`TILE_SOURCES` 內建 OSM／CartoDB Positron／Dark Matter／自訂 URL，預設 `"auto"`
  跟著主題換（深色配 Dark Matter、淺色配 Positron）；使用者手動選過就固定下來不再跟著主題跑。
  Leaflet 原生支援 `{s}`／`{r}`，不需要自己展開。**這些公用圖磚僅供輕量使用且必須保留 attribution。**
- **地名搜尋刻意由 Python 端發送**（[geocode.py](gps_qt/geocode.py) 用 `QNetworkAccessManager`）：
  Nominatim 政策要求可識別的 User-Agent 且每秒最多 1 次，在 QWebEngine 裡 `fetch()` 帶的是瀏覽器
  UA，改不掉也不合規。route 模式搜尋只帶視野過去，**不自動加點**；結果超過一筆會跳 `QMenu` 讓使用者挑。
  `Geocoder` 與 `Router`（路徑規劃）用的是同一個形狀：`MIN_REQUEST_INTERVAL_MS`(1000) 擋住過快的
  請求，`_abort_pending()` 讓同時間只保留最後一次查詢，避免舊結果比新結果晚到而覆蓋掉畫面。
- **Leaflet 本地化**在 `web/vendor/`：純靠 CDN 時斷網會整頁白，本地化後控制項仍在，
  只有圖磚空白並由 `tileerror` 顯示提示橫幅。
  `.gitattributes` 把 `gps_qt/web/vendor/**` 標為 `-text`，**vendored 檔案一律不做行尾轉換**：
  上游發布的 `leaflet.css` 本身就是 CRLF，被 `core.autocrlf` 正規化成 LF 後版控內容會與上游
  差 661 bytes，日後升級版本時整個檔案都會是差異，也無法用 checksum 驗證抓下來的檔案有沒有
  被動過。之後再 vendor 任何第三方檔案都要記得加進這條規則。

### 路徑規劃：Valhalla + Douglas-Peucker
`interpolate_points()` 在兩點之間走的是**直線**；要沿實際道路走就必須有路網資料，
這由 [routing.py](gps_qt/routing.py)（查詢）與 [route_planner.py](gps_qt/widgets/route_planner.py)（互動）負責。

- **服務是 Valhalla 的 FOSSGIS 公用實例**，不需要 API 金鑰，支援 `pedestrian`／`bicycle`／`auto`
  三種 costing。**這是社群維運的免費服務，政策是「合理使用」**，不要拿來做批次查詢。
- **`Router.route()` 收的是 `waypoints` 串列（至少兩點，沒有上限）**，原封不動對應請求裡的
  `locations`，服務會依序經過每一點；一次多點查詢比起分段查再自己接起來，轉彎與路口的處理
  由服務決定，也只算一次請求（有每秒一次的限制）。
- **`shape` 是精度 1e6 的 polyline**（一般的 Google polyline 是 1e5）。用錯精度不會報錯，
  只會讓座標差十倍，所以 `POLYLINE_PRECISION` 寫成具名常數，並有一個測試專門釘住這件事。
- **多個 leg 的接縫點會重複**（前一段的終點等於下一段的起點），`parse_route()` 會去掉重複的
  那一個，否則路線裡會出現距離為零的相鄰點。
- **回傳的轉彎點動輒上百上千個**（實測台中火車站→台灣大道三段 3.3 公里有 132 點），直接塞進
  座標表格會難以手動微調，所以用 `geo.douglas_peucker()` 抽稀，預設容差 5 公尺（實測降到 22 點，
  路形肉眼看不出差別）。`douglas_peucker()` **刻意用顯式堆疊而非遞迴**：遞迴版深度最壞等於點數，
  上千點會撞到 Python 的遞迴上限。
- **點選狀態機在 `RoutePlanner`**（IDLE → PICKING → ROUTING），刻意不放在
  `MapPanel` 裡：後者的職責是「顯示地圖並轉發互動」，混進來會讓它膨脹到不好讀。`MapPanel._on_map_clicked()`
  一律先問過 `route_planner.handle_map_click()`，**被吃掉就不能再當成新增座標點**——新增任何
  「會攔截地圖點擊」的功能都要沿用這個「攔截成功才吃掉事件」的形狀。
- **點選幾個點不固定，所以結束點選要由使用者明確表示**：`handle_map_click()` 每次只是把座標累積
  進 `self._points`，湊滿 `MIN_WAYPOINTS`(2) 之後由「完成規劃」（`finish_btn`，只在 PICKING 狀態
  顯示）觸發查詢。只支援起訖兩點時可以「點第二下就自動送出」，多點則沒有任何訊號能判斷使用者
  點完了，狀態機不能再靠點擊次數推進——之後若要加「插入中途點」這類功能也要沿用同一個形狀。
- 切到固定定位模式或模擬開始移動（編輯鎖）時都要呼叫 `route_planner.cancel()`，否則按鈕會卡在
  「點選中，已選 N 點」卻永遠等不到下一次點擊，也按不到「完成規劃」。
- **點選過程要在地圖上看得見**：`pick_state_changed(picking, points_json)` 這條 bridge signal 讓
  `map.js` 切換 `map-picking` 十字游標，並把已選的點依序畫成「起」「2」「3」…的標記（點數不固定，
  所以標記文字用序號而不是固定的「起」「終」兩種）；`RoutePlanner` 的按鈕文字同步顯示「已選 N 點」。
  沒有這些回饋，使用者無從判斷剛才那一下有沒有被收到、也不知道還差幾點才能按「完成規劃」。
- 算完的路線由 `MainWindow._on_route_computed()` **整條取代**目前路線，同時 `fit_to()` 拉視野、
  `clear_trail()` 清軌跡——路線都換了，舊軌跡沒有參考價值。`_load_favorite()` 載入最愛時同理。

### 非同步整合：qasync
[main.py](gps_qt/main.py) 用 `qasync.QEventLoop` 包住 `QApplication` 並 `asyncio.set_event_loop(loop)`，讓 asyncio
事件迴圈直接跑在 Qt 事件迴圈的同一條 thread 上，因此 `GPSSession._session_main()`／`_walk_route()`／
`_walk_pin()` 可以直接是 async 方法，不需要背景 thread、也不需要跨執行緒 marshalling。`GPSSession` 用
Qt signal（`log`/`progress_value`/`progress_label`/`paused`/`session_ended`/`direction_changed`／
`position_changed`（地圖即時位置與軌跡）／`route_finished`（抵達端點的系統匣通知））把狀態
送出，`MainWindow.__init__` 用 `.connect()` 接對應的 slot。

新增/修改任何動作（`pending_action` 的新值）時，需同步確認：(a) `_session_main()` 的 if/elif 分派邏輯、
(b) 對應的 `_walk_*()` 如何在動作被外部改變時中斷並保留 `travelled_m`、(c) 觸發該動作的按鈕要如何在
`MainWindow._sync_btn_states()` 重置其他按鈕狀態。

### 控制按鈕狀態機（`MainWindow._sync_btn_states()`）
- `busy`（`pending_action` 為 `forward`/`reverse`/`disconnect`）時停用「開始移動」與「恢復真實定位」。
- `holding`（已連線且 `pending_action == "pause"`）時「停止」仍要可按——固定定位模式啟動後會立刻回到
  `"pause"`，此時連線還在，若停用「停止」會跟 `_walk_pin()` 印出的提示訊息互相矛盾。
- 「恢復真實定位」在 `session_active` 為 False 時（從未連線或已斷線）停用；移動中按下會先跳警告要求
  使用者先按「停止」。
- `_update_return_btn_state()`（切換方向鈕）：因為切換方向本身不會啟動移動，不需要等
  `session_active`／連線完成，路線模式下隨時可切；只有 `pending_action` 為 `forward`/`reverse`/
  `disconnect`（移動中或斷線中）才停用，避免中途切換造成方向跟目前實際走的方向不一致，要先
  按「停止」才能再切。按鈕文字顯示「按下去會變成哪個方向」：`session.direction` 目前是
  `"reverse"` 就顯示「往終點」，否則顯示「往起點」。
- 連線結束（正常斷線或出錯）時 `_on_session_ended()` 會先把 `pending_action` 歸零成 `"pause"` 再同步
  按鈕，否則殘留的 `"disconnect"` 會讓按鈕全部卡在停用。
- **抵達端點的提示走系統匣、不用 `QMessageBox`**：沒開循環模式時 `_walk_route()` emit
  `route_finished(message)`，`MainWindow._on_route_finished()` 用 `QSystemTrayIcon.showMessage()` 顯示。
  對話框會搶焦點、打斷使用者正在做的事（例如全螢幕遊戲），系統匣提示不會 activate 視窗。
  `_start()` 會先 `tray_icon.hide()` 清掉上一趟殘留的通知（`hide()` 會讓還在顯示中的 balloon 一併消失），
  否則使用者會把舊的 toast 誤認成這趟剛跳出來的。

### 主題系統：qt-material，一個重要陷阱
- [theme.py](gps_qt/theme.py) 的 `apply()` 呼叫 `qt_material.apply_stylesheet(app, theme=..., invert_secondary=...)`
  套用內建的 `dark_red.xml` / `light_red.xml`（qt-material 目前只用內建色票，沒有覆寫成自訂品牌色，
  這是使用者明確要求）。淺色主題要傳 `invert_secondary=True`，否則 qt-material 的 `secondaryColor`
  系列預設是深色系（給深色主題用），淺色主題文字對比會不足。
- **陷阱**：qt-material 的樣式表最上層有 `* { font-size: ...px; ... }`，套用在 `QApplication` 層級後會
  蓋掉個別 widget 用 `setFont()` 設定的字級（Qt 樣式表屬性一旦命中該 widget，優先權高於程式設定的
  `QFont`——已用 `QFontInfo` 實測驗證過）。所以任何字級例外（區塊標題、App 標題）都不能只呼叫
  `setFont()`，要用 `mark_class(widget, "app-title"/"section-title")` 設定 Qt 動態屬性 `class`，並在
  `EXTRA_QSS_TEMPLATE` 補一段對應的 `.app-title`/`.section-title` 選擇器（`apply()` 產生完 qt-material
  的樣式表後會再 append 這段），才蓋得過去。新增任何「這個 widget 字級要特別大/特別色」的需求都要走
  這個模式，不要直接 `setFont()`。區塊標題另有包好的 `theme.style_section_title(label)`（內部就是
  `mark_class(label, "section-title")` 再回傳同一個 label），各面板一律呼叫它，不要自己再寫一次
  `mark_class()`，字串打錯不會報錯、只會靜靜地不套用。
- 按鈕的語意色（危險/成功動作）也是同一套機制：`mark_class(btn, "danger")`／`mark_class(btn, "success")`
  對應 qt-material 內建的 `QPushButton.danger`／`.success` 規則（靠 Qt 動態屬性 `class` 選取，這點已用
  offscreen 平台實際渲染截圖驗證過，不是靠猜的）。`mark_class()` 呼叫完一定要 `unpolish()`/`polish()`
  才會重新計算樣式。
- **控制項的外框與高度是覆寫過的**：qt-material 的樣式表雖然各類都寫 `height: 28px`，
  但那是**內容區**高度，各 widget 的 padding 與邊框不同，實測 `sizeHint()` 分別是
  `QPushButton` 40／`QComboBox` 32／`QLineEdit` 30／`QDoubleSpinBox` 33 px，並排在同一排
  工具列時高低不一；而且輸入類 widget 被當成 Material 的「填色輸入框」（只有底線
  `border-width: 0 0 2px 0`、只有上緣圓角），與按鈕的「四邊 2px 框線 + 4px 圓角」也不同調。
  `theme.py` 的 `CONTROL_QSS_TEMPLATE` + `_control_qss()` 把按鈕／下拉選單／單行輸入／數值
  輸入統一成同一組外框與同一個高度（`CONTROL_HEIGHT`，內容區高度；實際外觀高 = 該值 + 邊框 4px），
  展開後的清單（`QComboBox QAbstractItemView`）與 `QMenu` 也跟著對齊。要調整高度只改
  `CONTROL_HEIGHT` 一處，不要回頭去改個別 widget 的 `setFixedHeight()`。
  - **`CONTROL_HEIGHT` 不能小於 widget 實際需要的高度**（這是修過的 bug）：QSS 的 `max-height`
    會變成 widget 的 `maximumHeight`（= 該值 + 邊框 4px），設得太小時版面配置會把控制項往下
    推幾個 px、**下緣框線被父 widget 裁掉**（看起來像被下面的元件蓋住），文字也跟著偏上，
    看起來沒有垂直置中——兩個症狀同一個原因。設成 24 時實測 `RoutePlanner` 的按鈕被排到
    `y=2`、幾何高度 32 卻超出父層 32；28 才會讓 `sizeHint`／`maximumHeight`／實際幾何三者
    都是 32。改這個常數後要確認 `sizeHint().height() == maximumHeight()`。
  - **形狀統一但顏色分層**：強調色只留給可按的 `QPushButton`，輸入類平時是中性框線
    （`secondaryLightColor`），`:hover`/`:focus` 才轉成 `primaryColor`，焦點位置才看得出來。
    `:hover`/`:focus` 與 `:disabled` 選擇器權重相同，靠後面的規則勝出，所以 **`:disabled`
    一定要寫在 `:hover`/`:focus` 之後**。
  - 色票跟 `qt_material.get_theme()` 要（`invert_secondary` 必須和 `apply()` 傳的值一致），
    **不要在 QSS 裡寫死色碼**，否則切換主題會脫鉤；停用狀態用 `_rgba()` 把同一個顏色加上
    透明度變淡，而不是另外挑一個色。
  - **「別人內部的編輯器」要例外**：`QTableView` 儲存格的編輯器、`QDoubleSpinBox` 內部的
    輸入框（`pin_panel` 還會用 `setLineEdit()` 換成自訂子類別）都是 `QLineEdit`，會被上面的
    規則命中。表格編輯器鎖死高度會撐破所在的列；spin box 內部的那個會多畫一層框線、多縮排
    一次 `padding-left`，數值也會被往下擠。所以 `QTableView QLineEdit` 與
    `QAbstractSpinBox QLineEdit` 都要把這些屬性放回預設。新增任何 `QLineEdit` 通用規則時，
    都要想一下有沒有第三個「內部編輯器」也會被掃到。
- **下拉選單會截字的陷阱**：qt-material 的 `QComboBox::drop-down { width: 20px }` 與
  `QComboBox::down-arrow { margin-right: 8px }` 畫在文字區右側，但 `QComboBox` 只有
  `padding-left`、沒有對應的右側 padding，`sizeHint()` 也沒把這塊完整計入；再加上
  `QComboBox` 預設的 `AdjustToContentsOnFirstShow` 只在第一次顯示時算一次寬度就鎖死
  （而 `MainWindow` 在 `_build_ui()` 之後還會再套用一次主題，路徑規劃列又是切到路線模式
  才顯示），選項文字一長就會被箭頭壓掉一截。**所有 `QComboBox` 一律要過一次
  `theme.fit_combo_width()`**（設 `AdjustToContents` + 補 `COMBO_ARROW_ALLOWANCE`），
  不要自己 `setMinimumWidth()` 寫死像素。與 `_fix_to_hint()` 同樣必須在 `theme.apply()` 之後呼叫。
- 同一套機制還有一個 `.no-uppercase { text-transform: none; }`：qt-material 預設會把按鈕文字轉成大寫，
  速度預設按鈕（「步行 5 km/h」）這種含單位的文字被轉大寫後會變成「5 KM/H」，所以用
  `mark_class(btn, "no-uppercase")` 擋掉。
- 全域字體是 `Noto Sans TC`（比例字體，非等寬；使用者測試過多個等寬字體選項後決定用這個純粹當一般
  UI 字體）。要換字體只改 `apply()` 裡 `extra["font_family"]` 一處。
- 路線/固定定位模式切換按鈕是 `setCheckable(True)` + `QButtonGroup(exclusive=True)`，靠 qt-material
  內建的 `QPushButton:checked` 樣式顯示目前選取狀態，不需要手動切換顏色屬性。

### 視窗幾何：QScreen API
[window_geometry.py](gps_qt/window_geometry.py) 用 `QGuiApplication.screenAt(QPoint(x, y))` 判斷座標是否落在任何一台螢幕
內，回傳 `None` 就代表無效、位置交給 Windows 決定。Qt6 預設開啟 High-DPI scaling，`QWidget.geometry()`
拿到的座標本身就是邏輯像素，不需要手動做實體/邏輯像素換算。`MainWindow` 只在 `not self.isMaximized()`
時才更新 `_normal_geometry`（`resizeEvent`/`moveEvent` 都會呼叫），因為最大化時的幾何不能當還原基準；
`closeEvent()` 用這份記錄的座標存檔，同時把 `last_route` 與 `speed_kmh` 一起寫回 `pindrift_settings.json`。

### 路線表格：QTableView 虛擬化
[models.py](gps_qt/models.py) 的 `RouteTableModel(QAbstractTableModel)` + `RoutePanel`（[route_panel.py](gps_qt/widgets/route_panel.py)）
裡的 `QTableView` 原生只 render 可見列，不論路線有幾個點都不需要手動管理列 widget 的重複利用。
- 座標欄（緯度/經度/備註）靠 `Qt.ItemIsEditable` flag + `setData()` 支援直接編輯。
- 刪除欄用自訂的 `DeleteButtonDelegate(QStyledItemDelegate)`：`paint()` 畫文字、`editorEvent()` 攔截點擊
  發出 `delete_requested(row)` signal。**刻意不用 `setIndexWidget()`**——那會替每一列建立一個真正的
  `QWidget` 並常駐，等於又要自己管理 widget 生命週期，違背用 `QTableView` 換掉手刻虛擬化的目的。
- 刪除欄畫的是「刪除」二字（不用 icon/emoji），`setColumnWidth(COL_DELETE, ...)` 給的欄寬要能容納
  這兩個字，改文字時兩處要一起改。
- `RoutePanel.delete_point()` 在只剩 2 個點時直接 return：路線至少要兩點才能內插，UI 層先擋掉。
  表格的刪除欄與地圖節點彈出視窗的「刪除此點」都走這個方法，兩邊共用同一道下限檢查——新增其他
  刪除入口時也要接到這裡，不要各自呼叫 `model.remove_point()`。
- 標題列除了「新增點」還有「清空座標點」（`model.clear()`）：清空後路線只剩 0 個點，要重新在地圖上
  點或載入最愛才能再開始移動。
- `_update_info()` 由 `RouteTableModel` 的 `on_changed` callback 觸發，每次表格變動就重算總距離、依目前
  速度估算的預計時間與節點數，顯示在「路線座標點」標題右邊。

### 最愛清單：QListWidget + 自訂 eliding label
[favorites_panel.py](gps_qt/widgets/favorites_panel.py) 的 `FavoritesPanel` 項目數通常不多，不像路線表格要處理數千筆，
不需要虛擬化，直接用 `QListWidget` + `setItemWidget()` 掛自訂的列 widget。
- 名稱欄用 `_ElidingLabel(QLabel)`：`resizeEvent()` 裡用 `fontMetrics().elidedText()` 依目前寬度重新截斷
  加「…」，並設定 `QSizePolicy.Ignored` 讓它可以縮到比文字本身更窄。**這是修過的 bug**：一開始沒設
  `Ignored`，QLabel 的預設 `minimumSizeHint` 等於文字寬度，名稱一長就會把整列往右撐出可視範圍，必須
  橫向捲動才看得到後面的載入/編輯/刪除欄位；改用 `Ignored` + 動態截斷後，這幾個欄位永遠留在可視範圍
  內。
- **列的高度要用 `theme.fit_list_item()` 設，不要直接把 `row_widget.sizeHint()` 塞給
  `QListWidgetItem.setSizeHint()`**（修過的 bug）：qt-material 有一條
  `QListView::item { padding: 4px }`，`setItemWidget()` 掛上去的列 widget 會被上下各內縮 4px，
  實際拿到的高度比 item 的 sizeHint 少 8px（實測需要 36px 只拿到 28px），列裡按鈕的下緣框線
  就被裁掉。`fit_list_item()` 會補上 `LIST_ITEM_PADDING * 2`；那個常數直接對應上面那條 QSS 規則。
- 這幾個固定欄位（座標預覽、載入、編輯、刪除）的寬度用 `_fix_to_hint()` 依 widget 自己的 `sizeHint()`
  動態算出來，**不要**寫死像素常數：按鈕實際所需寬度取決於當下套用的 QSS padding，寫死的數字換主題或
  調字級後很容易太窄而裁切文字（也是修過的 bug）。呼叫時機必須在 `theme.apply()` 套用樣式表「之後」，
  `sizeHint()` 才會反映正確的 padding——`MainWindow.__init__` 因此把 `theme.apply()` 排在 `_build_ui()`
  之前呼叫。
- `refresh()` 同時做兩件事：依目前模式（pin/route）過濾清單內容，以及切換標題列按鈕的可見性——pin 模式
  只顯示「儲存目前座標」，route 模式只顯示「儲存目前路線」與「匯入 KML 路線」。切換模式時
  `MainWindow._switch_mode()` 會呼叫 `favorites_panel.refresh()`，兩者一起更新。
- **地圖上的最愛圖層只畫地點最愛**：`favorites_payload()` 濾掉 route 型（一整條疊在編輯中路線上的
  線分不出哪條是哪條，只是干擾），而且 `MainWindow._push_favorites_to_map()` 在 route 模式直接送空
  清單把圖層清掉。payload 每一筆都帶 `index`——它在 `FavoritesPanel.favorites` 完整清單裡的原始位置，
  使用者點地圖上的圓點時才能對回同一筆資料走既有的 `_load_favorite()` 流程（清單本身是過濾過的，
  用過濾後的序號會對錯）。
- 路線最愛除了手動輸入座標外，也可從 KML 檔案匯入（`_import_kml` → `persistence.parse_kml_route()`）：
  解析第一條 `LineString` 作為路線座標，並用起訖點附近（約 50 公尺內）的 `Point` 名稱自動當作起訖點
  備註，其餘中間點備註留空。

### 固定座標欄位：貼上「緯度, 經度」的攔截機制
[pin_panel.py](gps_qt/widgets/pin_panel.py) 的 `_CoordinatePasteLineEdit(QLineEdit)` 讓使用者把地圖複製來的
`24.981326, 121.451743` 直接貼進緯度或經度任一欄，就自動拆成兩個值分別帶入。
- **不能用 `insertFromMimeData()` 覆寫**：那是 `QTextEdit` 才有的掛勾，`QLineEdit` 沒有。
- **也不能覆寫 `paste()`**：右鍵選單的 Paste 動作在 C++ 端直接接到非 virtual 的 `paste()` slot，Python
  這邊的覆寫攔不到。
- 所以改為攔截兩個實際入口：`keyPressEvent()` 比對 `QKeySequence.StandardKey.Paste`（Ctrl+V），
  以及 `contextMenuEvent()` 裡把標準選單中 Paste 動作的 `triggered` 重接到自己的 handler。
- `_try_apply_pasted_coordinates()` 回傳 bool：字串不是「兩個以逗號分隔且都在合法經緯度範圍內的數字」
  就回 False，由呼叫端 fallback 回原本的貼上行為。新增類似的輸入攔截時要沿用這個「攔截成功才吃掉事件」
  的形狀，不要無條件吞掉貼上。
- `PinPanel` 的版面最後一定要留一個 `layout.addStretch(1)`（修過的 bug）：少了它，`QVBoxLayout` 會把
  面板多出來的垂直空間平均分給每一列（包含兩個標題 `QLabel`），文字被撐在過高的空白區塊正中央，
  看起來像「標題列高度太大」。加上之後多餘空間全被吸收，其餘內容維持貼齊頂端的自然高度。

### 響應式版面
`MainWindow.resizeEvent()`（[main_window.py](gps_qt/widgets/main_window.py)）依視窗寬度是否超過 `WIDE_LAYOUT_BREAKPOINT`
（1000px）切換 `QSplitter` 的方向（`Qt.Horizontal`/`Qt.Vertical`）。切換方向後一定要重新
`setSizes([10**6, 10**6])`：`QSplitter` 換方向時沿用舊方向的像素值會變成不等寬/不等高，用兩個相同的
大數字讓 Qt 依可用空間等比例換算成 50/50。執行日誌面板高度不手動計算，交給 `QVBoxLayout` 原生分配
剩餘空間。整個中央 widget 再用 `QScrollArea(setWidgetResizable(True))` 包一層，視窗縮到很小時仍可捲動
看到全部內容。

右欄內部的垂直配額由 `MAP_STRETCH`(3) 與 `COORDS_STRETCH`(2) 決定，地圖另有 `MAP_MIN_HEIGHT`(320)
的下限。座標面板要不要顯示由 `_sync_coord_panels()` 一處判斷——「目前模式」與「是否收合」是兩個
獨立條件，分散到 `_switch_mode()` 與收合按鈕各自 `show()`/`hide()` 的話，收合狀態下切換模式會把
面板又叫回來。

### 打包成執行檔：PyInstaller onedir
[PinDrift.spec](PinDrift.spec) 產出 `dist/PinDrift/` 這一個可以整包搬走的資料夾（約 510 MB），
裡面有兩個共用同一份 `_internal` 的執行檔：`PinDrift.exe`（視窗模式、一般權限）與
`PinDrift-tunneld.exe`（主控台模式、由前者提權啟動）。

- **刻意用 onedir 而不是 onefile**：QtWebEngine 的 `QtWebEngineProcess.exe` 是獨立子行程，
  還要找得到 ICU 資料與 locales，onefile 每次啟動都解壓到暫存目錄，既慢又常出現子行程
  找不到資源的問題。
- **tunneld 要拆成第二個執行檔**：使用者的機器上沒有 Python，原本
  `Start-Process python -m pymobiledevice3 ... -Verb RunAs` 這條路整條斷掉。拆成兩個 exe 才能
  讓主程式維持視窗模式，而 tunneld 保有主控台（看得到它在跑、也看得到錯誤）。兩者的
  `Analysis` 分開但共用一個 `COLLECT`，相依套件不會打包兩份。
- **`paths.py` 是打包能不能動的關鍵**：隨附資源（`web/`）在 `sys._MEIPASS`（即 `_internal/`）
  底下，使用者資料（最愛、設定）則在 exe 自己的資料夾——兩者在 onedir 下是不同路徑，
  用同一套 `__file__` 相對算法會錯。未凍結時兩者都回到專案根目錄，所以開發時的行為與
  打包前完全相同。**設定放在 exe 旁邊是使用者明確要求**（整包搬走設定跟著走），代價是
  裝進 `Program Files` 這類唯讀位置時存不了設定。
- **三個實測踩到的坑**（改 `EXCLUDED_MODULES` 前務必先讀）：
  1. `PySide6.QtUiTools` **不能排除**——`qt_material/__init__.py` 直接 import 它，排掉會在
     `import qt_material` 當場 `ModuleNotFoundError`。同理 `QtQml`／`QtQuick`／`QtPositioning`／
     `QtWebChannel`／`QtNetwork`／`QtOpenGL` 是 QtWebEngine 的相依，排掉地圖會壞。
  2. `prompt_toolkit` **不能排除**——`pymobiledevice3/cli/cli_common.py` 匯入的 `questionary`
     依賴它，排掉 tunneld 一啟動就 `ModuleNotFoundError`。`pygments` 同理（`remotexpc.py` 與
     `service_connection.py` 會用到）。可以排的是螢幕錄影／截圖／互動式 shell 那條路上的
     `av`／`numpy`／`PIL`／`IPython`／`jedi`（合計約 125 MB），因為 pymobiledevice3 的 CLI 子命令
     是用 `importlib` 依名稱延遲載入的，我們只會走到 `remote tunneld` 與 DVT。
  3. `wintun.dll` 在 **另一個發行套件** `pytun_pmd3` 裡，`collect_all("pymobiledevice3")` 不會
     一起帶走，少了它 tunneld 一啟動就 `FileNotFoundError`。所以 spec 裡另外
     `collect_all("pytun_pmd3")`。
- **`qt_material` 也要 `collect_all()`**：主題色票是套件目錄裡的 `.xml` 與 `.css.template`，
  是資料檔而不是 `.py`，靜態分析不會帶走，少了它 `theme.apply()` 會找不到 `dark_red.xml`。
  凡是「相依套件把資源放在自己的套件目錄裡」都是同一類問題，新增相依時要先想一下這件事。
- **`upx=False` 不要打開**：UPX 壓縮過的 Qt DLL 常常載入失敗，省下的體積換來隨機的啟動錯誤，
  不划算。`EXE()` 與 `COLLECT()` 兩處都要維持關閉。
- **`multiprocessing.freeze_support()` 必須是進入點的第一件事**（[app_entry.py](app_entry.py) 與
  `tunneld.run_cli()` 都有）：凍結後的程式若有子行程以 spawn 方式啟動，會重新執行整個進入點腳本，
  沒先呼叫就會無限遞迴開新視窗。新增任何進入點腳本都要照抄這個開頭。
- **視窗模式的 exe 當掉時看不到 traceback**，只會跳一個 PyInstaller 的錯誤對話框，而且那個
  對話框會讓行程一直活著——用「行程還在」判斷啟動成功會得到假的綠燈。驗證時要改用
  `subprocess.PIPE` 收 stdout，並確認 `QtWebEngineProcess.exe` 這個子行程真的起來了
  （它起來才代表地圖頁面載入成功）。
- **翻譯與除錯資源佔掉 130 MB**，spec 用 `_is_unused_qt_data()` 濾掉 `*.debug.pak`、
  53 種 WebEngine 語系與 157 個 Qt `.qm` 裡用不到的那些。要多支援一種語系就改
  `KEEP_WEBENGINE_LOCALES` 與 `KEEP_QT_TRANSLATION_SUFFIXES`。
