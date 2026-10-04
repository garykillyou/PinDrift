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
整包搬走設定就跟著走。同一個資料夾還會有記錄檔 `pindrift.log*`、圖磚快取 `tile_cache/`、
讀檔失敗的備份 `pindrift_*.corrupt-*.json` 與寫入中途的 `pindrift_*.json.tmp`，全部列入 `.gitignore`
（都是個人資料）；新增任何寫進這個資料夾的檔案，都要一併加進 `.gitignore` 與 README 的檔案結構。`save_settings()`／`save_favorites()` 共用的 `_write_json()`
**只攔 `OSError` 並回傳錯誤訊息字串（成功回傳 `None`）**，不丟例外——放在唯讀位置時
存檔失敗不能讓 `closeEvent()` 整個炸掉；序列化失敗則照常拋 `TypeError`，那是程式的 bug。
寫入是**先序列化、寫到 `.tmp` 再 `os.replace()`**，序列化失敗或寫到一半當機都不會留下被清空的原檔。
各呼叫端自己決定提示方式：切換主題與自動存檔走執行日誌（自動存檔同樣的錯誤只記一次，放在唯讀
位置時才不會每兩秒洗版一次）、存最愛與關閉視窗走 `QMessageBox`（視窗都要關了，寫進日誌等於沒說）。
新增存檔入口時要記得接這個回傳值。
設定除了關閉視窗時存，**路線、速度、地圖設定變動後也會自動存檔**（`MainWindow._setup_autosave()`），
程式當掉或被強制結束才不會把上次的路線弄丟。計時器是 `AUTOSAVE_DELAY_MS`(2000) 的 single-shot，
**第一次變動時啟動、期間的變動不重新計時**——若改成每次都重新計時，連續拖曳時會一直等不到空檔。
地圖設定是 `MapPanel`／`RoutePlanner` 就地改 `settings["map"]`，改完 emit `settings_changed`；
平移／縮放視野刻意不觸發（跟隨模式下每秒都在變），只在關閉視窗時存。視窗幾何、路線、速度這些只存在
widget 上的狀態由 `_collect_settings()` 統一寫回，自動存檔與 `closeEvent()` 共用。
執行日誌除了顯示在視窗（每行前面加 `HH:MM:SS`），也會經由 [applog.py](gps_qt/applog.py) 寫進同一個
資料夾的 `pindrift.log`（1 MB 輪替、保留 3 份，已列入 `.gitignore`）。`main()` 最先呼叫
`setup_file_logging()` 與 `install_exception_hooks()`：Qt slot 裡丟出的例外（PySide6 交給
`sys.excepthook`）與 asyncio 沒人接的錯誤（`loop.set_exception_handler()`），在 pythonw／打包版原本
都會完全消失，現在完整 traceback 進記錄檔、摘要進執行日誌；有主控台時仍照舊印到 stderr。
各模組一律用 `logging.getLogger(__name__)`，都是 `gps_qt` logger 的子孫，會進到同一份記錄檔。
讀取端 `load_settings()`／`load_favorites()` 回傳 **`(資料, 訊息)`**：檔案無法解析、最外層型別不對，
或最愛裡有被 `normalize_favorite()` 略過的項目時，會先把原檔複製成
`<檔名>.corrupt-<時間戳>.json` 再回報（`MainWindow` 建好版面後寫進執行日誌）。**絕對不能改回
默默吞掉例外**（修過的 bug）：回傳預設值之後的下一次存檔會把壞檔連同還救得回來的資料整個蓋掉。
- `pindrift_favorites.json`：最愛地點／路線（`{"type": "pin"|"route", "name", ...}` 陣列）。
- `pindrift_settings.json`：`theme`（主題偏好）、`window`（視窗幾何 + `maximized`）、
  `last_route`（上次的路線座標點）、`speed_kmh`（上次的移動速度）、
  `map`（地圖的 `tile_source`／`custom_tile_url`／`custom_attribution`／`center`／`zoom`／`follow`／
  `routing_costing`／`simplify_m`，由 `persistence.load_map_settings()` 補齊預設值）。
  **每個欄位讀進來都要先檢查型別與範圍**，設定檔可能被手改壞：`window` 走
  `window_geometry.normalize_window()`、`speed_kmh` 走 `persistence.load_speed_kmh()`、`last_route` 走
  `load_saved_route()`、`map` 走 `load_map_settings()`（`center` 要在經緯度範圍內、`zoom` 在
  `MAP_ZOOM_MIN`～`MAP_ZOOM_MAX`（對應 map.js 的 `maxZoom` 19）內，需要範圍檢查的欄位登記在
  `_MAP_FIELD_PARSERS`）。不合法的欄位一律改用預設值（這些值下次存檔就會重新產生，不需要備份）。
  共同的規則：布林／字串**只接受同型別**，不用 `bool()`／`str()` 硬轉（`bool("false")` 是 True）；
  數值要排除 `bool`（是 `int` 的子類別）與 NaN／無限大（JSON 存得進去，送進 Qt 或 Leaflet 就壞）。
  新增設定欄位時要照這個形狀補一個檢查，直接 `settings.get()` 拿來用的話，手改成字串就會讓程式
  一啟動就丟 `TypeError`（修過的 bug：`speed_kmh`、`window.width` 都踩過）。

## 常用指令

```bash
# 安裝相依套件
pip install -r requirements.txt

# 執行 App（tunneld 會自動偵測並提權啟動，見下方說明）
python -m gps_qt.main

# 手動啟動 tunneld（需「系統管理員」終端機，建立 iOS 26 的 RemoteXPC 加密通道）
python -m pymobiledevice3 remote tunneld

# 執行測試（只涵蓋純邏輯：geo、map_bridge payload、geocode 解析、routing polyline、設定欄位的型別／範圍檢查、
# 讀檔壞檔備份與最愛驗證、存檔失敗處理、路線表格的經緯度範圍檢查、
# GPSSession 的續走／改速度／循環走法／時間間隔／停止立即生效／例外回報／tunneld 提示、KML 匯入、
# 網路請求的節流與過期過濾、移動中鎖定路線表格與清空確認、固定座標的確定通知、記錄檔與例外攔截、
# 圖磚選擇與自訂版權標示的 escape、圖磚快取的路徑／新鮮度／容量上限、模擬中關閉視窗的恢復流程）
pip install -r requirements-dev.txt
python -m pytest

# 打包成可直接交付的資料夾（產出 dist/PinDrift/，約 510 MB）
# 需要 libssl-3-x64.dll／libcrypto-3-x64.dll：有 Git for Windows 會自動找到，
# 否則設 PINDRIFT_OPENSSL_DIR 指向 DLL 所在資料夾（見下方打包章節）
pip install -r requirements-lock.txt
python -m PyInstaller --noconfirm --clean PinDrift.spec

# 升級套件並實測過之後，依目前環境重新產生打包用的固定版本檔
python scripts/lock_requirements.py
```

**相依套件分兩層**：`requirements*.txt` 寫版本範圍（下限 + 實測版本所在的主／次版號上限——
pymobiledevice3 改版常搬動模組路徑，而 `session.py` 直接 import 它的內部模組；PySide6／
qt-material 的次版號會改樣式表與 WebEngine 行為；qasync 還在 0.x），`requirements-lock.txt` 則是
[scripts/lock_requirements.py](scripts/lock_requirements.py) 依目前環境產生的固定版本（含遞移相依，
只收 `requirements.txt` + `requirements-build.txt` 會帶進來的套件，不是 `pip freeze` 整個環境），
**打包（`build.bat`）一律裝鎖定檔**，確保打出來的 exe 用的就是實測過的版本。鎖定檔的環境標記依
產生時的平台評估，只適用 Windows。放寬上限或升級套件後要實測、重新產生鎖定檔，並更新
`requirements.txt` 開頭註解裡的實測版本。

一般情況下不需要手動跑 tunneld：App 啟動後 [MainWindow._ensure_tunneld()](gps_qt/widgets/main_window.py)
會呼叫 [tunneld.py](gps_qt/tunneld.py) 偵測 `127.0.0.1:49151` 是否已經有人在聽，沒有的話用
`ShellExecuteW` 的 `runas` 動詞以系統管理員身分啟動（會跳 UAC），結果寫進執行日誌。
提權的對象由 `_elevated_command()` 依「是否已凍結」分成兩條路：未凍結時跑
`python.exe -m gps_qt.tunneld`（**刻意把 `pythonw.exe` 換回 `python.exe`**，開發時才看得到
tunneld 的主控台輸出），已凍結時跑同一個資料夾裡的 `PinDrift-tunneld.exe`——打包後使用者的
機器上沒有 Python，`python -m pymobiledevice3 ...` 那條路整條斷掉。
[run.bat](run.bat) 因此只剩「用 `pythonw` 開 App」一件事。
按「開始移動」時連不上 tunneld 的提示同樣分兩條路（`tunneld.manual_start_hint()`）：未凍結時叫使用者
跑 `python -m pymobiledevice3 remote tunneld`，打包版改成「重新開啟 PinDrift 讓它自動啟動，或以系統
管理員身分執行同資料夾的 `PinDrift-tunneld.exe`」。任何給使用者看的指令都要想一下打包版有沒有 Python。

測試以不需要 Qt 事件迴圈的邏輯為主（[tests/](tests)）；少數 widget（`RoutePanel`、`PinPanel`）以
offscreen 平台建立來測，地圖頁面與 `MainWindow` 沒有自動化測試（`MainWindow` 需要 QtWebEngine；
要測它的行為就像 `CloseGuard` 那樣抽成只用 QtCore 的小類別）。**需要 Q*Application 的測試一律用
[conftest.py](conftest.py) 的 `qapp` fixture**：一個行程只能有一個，而且若先建了 `QCoreApplication`，
之後就建不出 widget 需要的 `QApplication`。
`GPSSession` 只用到 QtCore 的 signal，可以直接 `asyncio.run(session._walk_route(...))` 測；
[test_session.py](tests/test_session.py) 把 `_now()`／`_sleep_until()` 換成假的時鐘、`sim` 換成
記錄呼叫的假物件，一秒一步的路線不用真的等。
專案沒有 lint 設定，也沒有 CI。

## 架構重點

### 檔案地圖
```
PinDrift/
├── run.bat                # 啟動捷徑：用 pythonw 開 App（tunneld 交給 tunneld.py）
├── build.bat              # 打包捷徑：裝 requirements-lock.txt + 跑 PyInstaller
├── PinDrift.spec          # PyInstaller 設定（onedir，兩個執行檔共用 _internal；另帶 Qt 用的 OpenSSL DLL）
├── app_entry.py           # 打包用的主程式進入點（PyInstaller 只吃腳本不吃模組）
├── tunneld_entry.py       # 打包用的 tunneld 進入點（console 模式的第二個執行檔）
├── requirements.txt       # 執行 App 需要的相依套件（版本範圍：下限 + 上限）
├── requirements-dev.txt   # 測試相依（pytest）
├── requirements-build.txt # 打包相依（pyinstaller）
├── requirements-lock.txt  # 打包用的固定版本（實測版本 + 遞移相依，由下面的腳本產生）
├── scripts/
│   └── lock_requirements.py  # 依目前環境產生 requirements-lock.txt
├── .gitattributes         # vendored 的 Leaflet 檔案排除行尾轉換（見下方地圖面板）
├── LICENSE                # MIT 授權條款全文
├── conftest.py            # 讓 pytest 把根目錄加進 sys.path；共用的 qapp fixture（offscreen）
├── tests/                 # 邏輯測試（不需要 Qt 事件迴圈；session 用假時鐘）
└── gps_qt/
    ├── main.py              # 進入點：QApplication + qasync 事件迴圈
    ├── paths.py             # 資源／使用者資料的路徑解析（打包後兩者要分開）
    ├── applog.py            # 記錄檔 pindrift.log、日誌時間戳記、未處理例外的攔截
    ├── tunneld.py           # tunneld 偵測 + 提權啟動；也是 tunneld 子行程的本體
    ├── theme.py             # qt-material 主題套用、字級覆寫、danger/success 語意色
    ├── geo.py               # haversine()、RouteSampler（依弧長等距切步、按需算單點）、
    │                        # douglas_peucker()、simplify_route()（保留備註點的抽稀）、
    │                        # cumulative_distances()、route_length()、
    │                        # is_valid_latitude()／is_valid_longitude()、adjacent_point()（前後插點的座標）
    ├── persistence.py       # JSON 存讀 + KML 解析 + 地圖設定正規化
    ├── window_geometry.py   # 視窗位置記憶（QScreen API）
    ├── session.py           # GPSSession：連線狀態機（pending_action 設計）
    ├── close_guard.py       # CloseGuard：模擬中關閉視窗時先恢復真實定位再關
    ├── tiles.py             # 圖磚來源清單 + resolve_tile()（自訂版權標示在這裡 escape）
    ├── tile_cache.py        # 圖磚本機快取的純函式（URL 改寫、檔案路徑、新鮮度、容量上限）
    ├── tile_scheme.py       # pdtile: scheme 處理器：快取優先，沒有才下載並存起來
    ├── models.py            # RouteTableModel + DeleteButtonDelegate（路線表格虛擬化）
    ├── map_bridge.py        # QWebChannel 契約（MapBridge）+ payload 序列化純函式
    ├── netclient.py         # SingleFlightClient：節流 + 只保留最後一次請求（geocode/routing 共用）
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
2. 按「開始移動」時，[session.py](gps_qt/session.py) 的 `GPSSession._session_main()` 用 `asyncio.ensure_future()` 建立一個常駐 task，`async with DvtProvider(rsd) as dvt, LocationSimulation(dvt) as sim:` 開一次連線後就常駐在 while 迴圈裡；後續按「停止」都**不會**重建 task 或重新連線，只是改變 `self.pending_action` 這個共享狀態（`"forward" | "reverse" | "pause" | "disconnect"`），由 while 迴圈讀取並分派動作。`pending_action` 是 property，**一被改掉就喚醒等待中的迴圈**
（見下方「動作改變立即喚醒」），「停止」「恢復真實定位」不必等下一步的刻度或下一輪輪詢。「往起點／往終點」（切換方向）本身**不會**碰觸 `pending_action`，只改變下面提到的 `self.direction`。
3. 直到 `pending_action == "disconnect"`（使用者按「恢復真實定位」）才 `break` 出迴圈、呼叫 `sim.clear()` 並讓 `async with` 關閉連線——恢復真實 GPS 只會在明確斷線時發生，單純停止都仍保持模擬連線在目前座標。
4. 座標注入本身是 `sim.set(lat, lon)`，呼叫位置在 `_walk_route()` / `_walk_pin()` 這兩個由 `_session_main()` 依 `pending_action` 呼叫的協程裡。
5. `_session_main()` 的 `try/finally` **包住整個函式主體**，不是只包 `async with` 那一段（修過的 bug）：
   匯入失敗／tunneld 連線失敗／找不到裝置這些提早 `return` 的分支也必須重設 `session_active` 並 emit
   `session_ended`，否則 UI 會卡在按下「開始移動」當下的忙碌狀態，連「停止」都救不回來——那時
   `_session_main()` 早已結束，沒有任何 task 在讀 `pending_action`，而 `_stop()` 本身也不會主動同步按鈕狀態。
   同一個 `try` 還有 **`except Exception`**（修過的 bug）：移動中拔 USB、iPhone 鎖定、關掉開發者模式，
   或程式本身出錯，例外都會從 `sim.set()` 等處丟出；沒接住的話只會變成 asyncio 印在 stderr 的
   「Task exception was never retrieved」，而 pythonw／打包版沒有 stderr，使用者只看到按鈕突然恢復。
   現在會寫進執行日誌（摘要）與記錄檔（traceback），`travelled_m` 保留，重新連線後可以接著走。
   `_walk_route()` 每一圈開始時也會檢查路線是否少於 `MIN_ROUTE_POINTS`(2) 點，是的話停下並說明。

### 兩種模式（由 `MainWindow.mode` 控制，動作由 `pending_action` 驅動）
- **路線模式（route）**：`_walk_route(sim, direction)` 中 `direction=1` 往終點走、`direction=-1` 往起點走回去。
  方向與移動是兩個分開的動作：`GPSSession.toggle_direction()`（由「往起點／往終點」按鈕觸發）**單純
  切換** `self.direction`（`"forward"` / `"reverse"`），不會碰 `pending_action`、也不會啟動 task，
  純粹只是記錄「下次按開始移動要往哪走」；`GPSSession.start()`（由「開始移動」按鈕觸發）才會把
  `pending_action` 設成目前的 `self.direction` 並真正開始移動。UI 在移動中（`pending_action` 為
  `forward`/`reverse`）或斷線中（`disconnect`）會停用切換方向按鈕，要先「停止」才能再切方向。
  `geo.RouteSampler(route, step_m)` 依 `haversine()` 算出的距離與設定速度（UI 以 km/h 輸入，經
  `speed_ms()` 換算成 m/s，乘上 `STEP_INTERVAL_S` 就是 `step_m`）把路線切成每秒一步。**切法是把整條路線
  當成一條線依弧長等距取樣，不是逐段切**（修過的 bug）：逐段切時比一步短的段也會佔滿一秒、1.9 步長的段被 `int()` 捨成一步，路線點越密實際速度與
  預計時間偏得越多。步數取「總長 / 步長」四捨五入後平均分配，代價是轉角會被截掉最多約半步。
  **`RouteSampler` 不會一次展開整條路線**（修過的效能問題）：舊的 `interpolate_points()` 一次產生所有
  內插點，每一圈與每次改速度都在 UI 執行緒上重算，10 公里以 0.1 km/h（速度下限）走是約 36 萬點。現在建立
  時只算原本路線點的累積距離，`point(k)` 用二分搜尋找出第 k 步所在的線段即時內插；索引 0 是起點、
  `last_index` 是終點，點數是 `last_index + 1`。**不要為了方便又把所有點展開成串列**。**進度記在 `travelled_m`（已走到路線的第幾公尺），不是「第幾個內插
  點」**（修過的 bug）：內插點的數量由速度決定，停止期間改過速度後同一個索引對到的位置完全不同，而
  `min(idx, total - 1)` 這種夾取會把超出範圍的索引直接夾到最後一點——實測 2.2 公里的路線以 5 km/h 走到
  中途是第 794 個點（共 1589 個），改成 60 km/h 後只剩 134 個點，再按「開始移動」人就瞬移到終點。
  `travelled_m` 是**沿原路線的弧長**（`RouteSampler.distance_at(k)`），與步長無關，所以 `_walk_route()`
  的每一輪都依目前速度重建 `RouteSampler`，再用 `index_at()`（取最接近的一步）把 `travelled_m` 換算成
  這一輪的索引；中斷
  （停止／斷線）時會停在原地，之後從該處繼續。整條路線被換掉時則由 `GPSSession.reset_progress()` 歸零
  ——舊的已走距離對新路線沒有意義。觸發點是 `RouteTableModel` 的 `modelReset`，它只在 `set_route()`／
  `clear()` 發出，剛好對應「載入最愛」「路徑規劃算完」「簡化目前路線」「清空座標點」四個整條替換的入口，不會被單點
  編輯誤觸。新增任何會整批換掉路線的入口時，要確認它有走到 `set_route()`／`clear()`。
  `_walk_route()` 拆成三段：`_resume_index()`（`travelled_m` → 起始索引）、`_walk_points()`（一步步注入）、
  `_on_route_end()`（抵達端點後依循環設定決定下一輪方向，回傳 `None` 代表停下）。
  - **移動中改速度會在下一步生效**：`_walk_points()` 每一步都比對 `speed_provider()`，變了就回傳
    `_SPEED_CHANGED`，由外層依 `travelled_m` 用新速度重新內插。此時 `_resume_index()` 的
    `skip_current` 會跳到行進方向上的下一個點，否則剛注入過的位置會被重送一次、原地多停一秒。
  - **每一步排在固定刻度上**（`next_tick += STEP_INTERVAL_S`，用 `_sleep_until()` 等到那個時間點），
    會扣掉 `sim.set()` 本身的往返耗時（修過的 bug）：舊寫法是 `set()` 之後固定 `sleep(1.0)`，實際間隔
    是「一秒 + 往返時間」，長路線會越走越慢。某一步卡得比一個間隔還久時用 `max(..., _now())` 從當下
    重新起算，不連續補送落後的步數（那等於在地圖上瞬間跳一段）。
  - **動作改變立即喚醒**（修過的 bug：按「停止」最多要等一秒、待機時每 0.2 秒輪詢一次）：
    `pending_action` 的 setter 會 `set()` 一個 `asyncio.Event`。`_walk_points()` 等下一個刻度時用
    `_sleep_until_or_action_change()` 讓 `_sleep_until()` 跟「動作被改掉」賽跑，`_session_main()`
    的待機分支則用 `_wait_for_action_change()` 直接等到動作改變。時間仍只經過 `_now()`／`_sleep_until()`
    這兩個掛勾，測試換成假時鐘的方式不變。Event 會綁定建立時的事件迴圈，所以由
    `_current_action_event()` 在第一次等待時才於當下的迴圈建立（測試每次 `asyncio.run()` 都是新迴圈）；
    `clear()` 之後立刻檢查條件、中間沒有 `await`，不會漏掉 `sim.set()` 往返期間發生的變動。
  循環模式不是在進入 `_walk_route()` 時快取的：**每次抵達端點才即時讀取** `loop_provider()` 與
  `loop_style_provider()`，因此使用者中途勾選／切換走法會在下一次抵達端點時生效。循環有兩種走法
  （[route_panel.py](gps_qt/widgets/route_panel.py) 的 `loop_style_combo`，僅在勾選循環模式時才啟用）：
  - **來回（bounce）**：抵達端點折返，方向反轉，會一併更新 `direction`（區域變數）、`action_name`、
    `pending_action` 與 `self.direction`（記錄用），並 emit `direction_changed`，讓按鈕文字跟著改成
    新的方向。
  - **迴圈（circuit）**：方向不變，索引直接瞬移回路線另一端（往終點走完就跳回 `0`，往起點走完就跳
    回 `last_index`，`travelled_m` 一併更新成該點的弧長位置）再繼續走，模擬繞圈；不改 `direction`／
    `self.direction`，也不 emit `direction_changed`，因為方向本身沒有變。
- **固定定位模式（pin）**：`_walk_pin(sim)` 呼叫一次 `sim.set(lat, lon)` 後立刻把 `pending_action` 設回 `"pause"`，讓外層 while 迴圈進入 `_wait_for_action_change()` 的閒置分支（不輪詢，動作一改就醒），藉此在同一條長連線上「保持」定位，直到使用者按「停止」（其實已經是 pause 狀態，UI 只更新按鈕）或「恢復真實定位」。

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
- **`syncRouteMarkers()` 只更新真的有變的部分**：座標沒變就不 `setLatLng()`，`routeIconKey()`（序號 +
  是否為起訖點）沒變就不 `setIcon()`；彈出視窗在建立 marker 時用函式綁一次，開啟時才依
  `marker.routeIndex`／`marker.routePoint` 產生內容。舊寫法每次都對全部 marker 重新 `setIcon()` +
  `bindPopup()`，2000 個點時移動一點要約 55 ms，改完約 0.5 ms。新增 marker 屬性時要記得在這裡同步，
  否則彈出視窗會顯示舊資料。拖曳中的折線則是直接改 `getLatLngs()` 回傳的內部陣列再 `redraw()`
  （會重新投影），不用 `setLatLngs()` 把整條線的座標重新轉換一次。
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
  **只鎖地圖不夠**（修過的 bug）：移動中還能改路線表格的話，地圖畫的是新路線、實際走的仍是舊路線，
  循環模式下清空路線更會讓下一圈丟 `IndexError`。所以 `_sync_btn_states()` 用同一個 `_is_moving()`
  一併鎖住：`RoutePanel.set_locked()`（新增／清空按鈕停用、`RouteTableModel.set_locked()` 讓儲存格
  不可編輯且 `setData()` 一律拒收——鎖在 model 才擋得住鎖定前就開著的編輯器）、模式切換按鈕；
  `_load_favorite()`、`_on_route_computed()`、`_on_simplify_requested()` 這些整條替換的入口則在
  開頭檢查 `_is_moving()`。開始移動時 `RoutePlanner.cancel()` 會中止還在查詢的路徑規劃請求
  （`SingleFlightClient.cancel()`），否則結果晚到仍會換掉路線。新增任何會改路線或模式的入口，
  都要想一下移動中是否該擋。
  固定定位「保持中」（`_walk_pin()` 注入完已把 `pending_action` 設回 `pause`）**不算移動中**，
  此時改座標會由 `_reinject_pin_if_holding()` 立刻重新注入一次，人就直接搬過去。入口包括地圖點選／
  拖曳、載入地點最愛，以及 `PinPanel.coordinates_committed`（快速選擇、貼上座標、欄位打完字的
  `editingFinished`；打字途中的 `valueChanged` 不算，否則每按一鍵都會瞬移到打到一半的座標）。
  座標與 `GPSSession.last_position`（最後一次實際注入的座標）相同時不再送一次：離開輸入框時即使
  沒改值也會觸發 `editingFinished`。
- **軌跡**：`session.position_changed` 每次 `sim.set()` 後 emit，`map.js` 用 `polyline.addLatLng()`
  累加；超過 `TRAIL_MAX_POINTS`(3000) 就每兩點抽一點，循環模式跑整夜也不會累積出巨大的 polyline。
- **跟隨**：使用者手動拖動地圖（`dragstart`）會自動關閉跟隨並回報 Python 同步核取方塊；
  `panTo()` 不觸發 `dragstart`，所以程式自己的平移不會誤關。
- **圖磚**：[tiles.py](gps_qt/tiles.py) 的 `TILE_SOURCES` 內建 OSM／CartoDB Positron／Dark Matter／
  自訂 URL，預設 `"auto"` 跟著主題換（深色配 Dark Matter、淺色配 Positron）；使用者手動選過就固定下來
  不再跟著主題跑。目前該用哪一組由純函式 `resolve_tile(map_settings, theme_name)` 決定（不相依
  QtWebEngine，可單獨測試），`MapPanel._push_tile()` 再經 `bridge.tile_changed` 送到 `map.js` 的
  `setTile()`。Leaflet 原生支援 `{s}`／`{r}`，不需要自己展開。**這些公用圖磚僅供輕量使用且必須保留
  attribution。**
  - **Leaflet 會把 attribution 當 HTML 插進頁面**，而這個頁面能呼叫 QWebChannel bridge，所以
    **自訂圖磚的版權標示（使用者輸入的純文字）在 `resolve_tile()` 裡 `html.escape()` 後才送出**
    （修過的安全問題）；設定檔裡存的仍是原文，輸入框才顯示得回來。內建清單的版權標示是寫死的 HTML
    （`&copy;` 實體），原樣送出，不能一起 escape。新增任何會把使用者輸入送進頁面當 HTML 用的欄位，
    都要在 Python 端 escape。
  - **瀏覽過的圖磚存進本機快取**（[tile_cache.py](gps_qt/tile_cache.py)＋[tile_scheme.py](gps_qt/tile_scheme.py)）：
    `_push_tile()` 送出前用 `cached_url_template()` 在 http(s) 樣板前面加上 `pdtile:`，Leaflet 照常展開
    `{z}/{x}/{y}/{s}/{r}`，實際請求由 `TileSchemeHandler` 接手：`TILE_FRESH_SECONDS`（90 天）內的快取
    直接回、不連線；過期或沒有才用 `QNetworkAccessManager` 下載（帶 `netclient.USER_AGENT`，符合 OSM
    要求可識別 UA）並寫進 exe 旁的 `tile_cache/`（已列入 `.gitignore`）；下載失敗時退回過期的快取，
    都沒有才 `job.fail()` 讓 `tileerror` 橫幅照常出現。**刻意只快取看過的、不做範圍批次下載**：OSM 官方
    圖磚政策明文禁止 bulk download，CARTO 免費圖磚也不允許——之後若要加「預先下載一塊範圍」，只能對
    使用者自行確認允許下載的自訂來源開放。
    - `register_scheme()` 必須在建立 `QApplication` **之前**呼叫（`main.py`），晚了 Qt 會默默忽略，
      地圖就整片空白。
    - 算雜湊前會把 `{s}` 展開出來的單字母子網域（`a.`～`d.`）統一成 `s.`，同一張圖磚不會因為隨機子網域存三份；下載仍用原網址。下載回應要 HTTP 200 **且內容是圖片**（`is_image()` 看特徵碼）才存：captive portal／限流頁常是 200，存進去地圖會壞到快取過期。同一網址的並行請求合併成一次下載（`_PendingFetch`，全部 job 都被取消才中止），下載有 `DOWNLOAD_TIMEOUT_MS` 逾時，逾時後退回過期的快取。
    - 檔名是上游網址的 SHA-1（前兩碼分一層資料夾），不照網址路徑建資料夾：網址是頁面給的字串，
      直接組路徑就得自己擋路徑穿越。`upstream_url()` 也只放行 http(s)，不讓頁面借道讀本機檔案。
    - 寫入沿用 `.tmp` + `os.replace()`；寫不進去（唯讀位置）只記一次記錄檔，地圖照常從網路顯示。
    - 容量上限 `TILE_CACHE_MAX_BYTES`(500 MB)：`install()` 啟動時在背景執行緒跑 `prune_cache()`，
      從最舊的刪到上限的 `TILE_CACHE_PRUNE_RATIO`(0.8)，略過寫到一半的 `.tmp`。背景執行緒不能碰
      Qt 物件，結果只寫記錄檔。
    - Leaflet 取消圖磚（快速平移）時 job 會被銷毀：`abort()` 會同步觸發 `finished`，所以先在
      `job.destroyed` 裡記下「job 已經不在」再中止，`_on_fetched()` 看到就不再碰 job。
- **地名搜尋刻意由 Python 端發送**（[geocode.py](gps_qt/geocode.py) 用 `QNetworkAccessManager`）：
  Nominatim 政策要求可識別的 User-Agent 且每秒最多 1 次，在 QWebEngine 裡 `fetch()` 帶的是瀏覽器
  UA，改不掉也不合規。route 模式搜尋只帶視野過去，**不自動加點**；結果超過一筆會跳 `QMenu` 讓使用者挑。
  `Geocoder` 與 `Router`（路徑規劃）都繼承 [netclient.py](gps_qt/netclient.py) 的 `SingleFlightClient`：
  `MIN_REQUEST_INTERVAL_MS`(1000) 擋住過快的請求，`_abort_pending()` 讓同時間只保留最後一次查詢，
  `_on_finished()` 濾掉過期與被取消的回應，避免舊結果比新結果晚到而覆蓋掉畫面；`USER_AGENT` 也只定義
  在這裡。子類別只負責組請求（`new_request()` 已帶好 User-Agent，再交給 `_send()`）、實作
  `_handle_reply()`，並用 `THROTTLED_MESSAGE` 覆寫節流時的提示文字。
- **Leaflet 本地化**在 `web/vendor/`：純靠 CDN 時斷網會整頁白，本地化後控制項仍在，
  只有沒快取過的圖磚空白並由 `tileerror` 顯示提示橫幅（看過的圖磚有本機快取，見上方）。
  `.gitattributes` 把 `gps_qt/web/vendor/**` 標為 `-text`，**vendored 檔案一律不做行尾轉換**：
  上游發布的 `leaflet.css` 本身就是 CRLF，被 `core.autocrlf` 正規化成 LF 後版控內容會與上游
  差 661 bytes，日後升級版本時整個檔案都會是差異，也無法用 checksum 驗證抓下來的檔案有沒有
  被動過。之後再 vendor 任何第三方檔案都要記得加進這條規則。

### 路徑規劃：Valhalla + Douglas-Peucker
`RouteSampler` 在兩點之間走的是**直線**；要沿實際道路走就必須有路網資料，
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
- **「簡化目前路線」按鈕**（`RoutePlanner.simplify_btn`）用同一個下拉選單的容差，對表格裡**現有**
  的路線再抽稀一次——下拉選單本身只影響「下一次規劃完」的結果，手動點的、載入的最愛、KML 匯入的
  路線原本沒有機會簡化。訊號鏈是 `RoutePlanner.simplify_requested(tolerance)` → `MapPanel` 同名
  signal 轉發 → `MainWindow._on_simplify_requested()`，形狀與 `route_computed` 相同（`RoutePlanner`
  不持有路線，只送出意圖）。
  - 抽稀走 `geo.simplify_route()` 而不是直接呼叫 `douglas_peucker()`：**有備註的點一律保留**
    （起訖點、KML 匯入的地名是使用者標的，落在直線上也有意義），做法是在備註點把路線切段、各段分別
    抽稀再接起來。回傳的是新的列，不改動輸入。
  - 結果走 `route_panel.set_route()` 整條替換，因此會觸發 `modelReset` 把 `travelled_m` 歸零（點被
    抽掉後路線長度會略變，舊進度不再精確）；**點數沒有減少就不替換**，免得無謂地歸零進度。路形幾乎
    不變，所以不像 `_on_route_computed()` 那樣 `fit_to()` 或清軌跡。
  - 容差為 0（簡化：關閉）或 ROUTING 狀態時按鈕停用，由 `_sync_button()` 統一判斷（切換下拉選單時
    也會重跑一次）；移動中整個 `RoutePlanner` 已被編輯鎖 `setEnabled(False)`，走到一半不會被換路線。
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
- 連線結束（正常斷線、提早 return 或出錯）時，`_session_main()` 的 `finally` 會先把 `pending_action`
  歸零成 `"pause"` 再 emit `session_ended`，`MainWindow` 收到後只負責 `_sync_btn_states()`；否則殘留的
  `"disconnect"` 會讓按鈕全部卡在停用。狀態由 `GPSSession` 自己收尾，不讓 UI 從外面改。
- **抵達端點的提示走系統匣、不用 `QMessageBox`**：沒開循環模式時 `_walk_route()` emit
  `route_finished(message)`，`MainWindow._on_route_finished()` 用 `QSystemTrayIcon.showMessage()` 顯示。
  對話框會搶焦點、打斷使用者正在做的事（例如全螢幕遊戲），系統匣提示不會 activate 視窗。
  `_start()` 會先 `tray_icon.hide()` 清掉上一趟殘留的通知（`hide()` 會讓還在顯示中的 balloon 一併消失），
  否則使用者會把舊的 toast 誤認成這趟剛跳出來的。
- **模擬中關閉視窗要先恢復真實定位**（修過的 bug）：直接關掉的話 qasync 事件迴圈一停，`GPSSession`
  的 task 被整個銷毀、`sim.clear()` 從來沒被呼叫，只能靠連線中斷時 iPhone 自己恢復。
  [close_guard.py](gps_qt/close_guard.py) 的 `CloseGuard.allow_close()` 由 `closeEvent()` 最先呼叫：
  `session_active` 時先跳確認（「恢復真實定位並關閉」／「取消」），確定後 `event.ignore()`、呼叫
  `restore_real_location()`（**移動中也直接斷線**，不像按鈕那樣要求先按「停止」），等 `session_ended`
  再用 `QTimer.singleShot(0, close)` 關一次——延一輪是讓 `_session_main()` 的 `finally` 先跑完。
  `sim.clear()` 卡住（USB 已拔）時以 `RESTORE_TIMEOUT_MS`(5000) 為限直接關閉，並寫進記錄檔；
  恢復中重複按關閉不會再問。存檔只在真正關閉的那一次 `closeEvent()` 做。

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
  `mark_class(btn, "no-uppercase")` 擋掉。粗體同理用 `.bold`（最愛清單的名稱欄），不要對個別
  widget 呼叫 `setStyleSheet()`。
- 全域字體是 `Noto Sans TC`（比例字體，非等寬；使用者測試過多個等寬字體選項後決定用這個純粹當一般
  UI 字體）。要換字體只改 `apply()` 裡 `extra["font_family"]` 一處。
- 路線/固定定位模式切換按鈕是 `setCheckable(True)` + `QButtonGroup(exclusive=True)`，靠 qt-material
  內建的 `QPushButton:checked` 樣式顯示目前選取狀態，不需要手動切換顏色屬性。

### 視窗幾何：QScreen API
[window_geometry.py](gps_qt/window_geometry.py) 用 `QGuiApplication.screenAt(QPoint(x, y))` 判斷座標是否落在任何一台螢幕
內，回傳 `None` 就代表無效、位置交給 Windows 決定。Qt6 預設開啟 High-DPI scaling，`QWidget.geometry()`
拿到的座標本身就是邏輯像素，不需要手動做實體/邏輯像素換算。`MainWindow` 只在 `not self.isMaximized()`
時才更新 `_normal_geometry`（`resizeEvent`/`moveEvent` 都會呼叫），因為最大化時的幾何不能當還原基準；
`_collect_settings()` 用這份記錄的座標，連同 `last_route` 與 `speed_kmh` 一起寫回 `pindrift_settings.json`
（關閉視窗與自動存檔都走這裡）。

### 路線表格：QTableView 虛擬化
[models.py](gps_qt/models.py) 的 `RouteTableModel(QAbstractTableModel)` + `RoutePanel`（[route_panel.py](gps_qt/widgets/route_panel.py)）
裡的 `QTableView` 原生只 render 可見列，不論路線有幾個點都不需要手動管理列 widget 的重複利用。
- 座標欄（緯度/經度/備註）靠 `Qt.ItemIsEditable` flag + `setData()` 支援直接編輯。
  `setData()` 會用 `geo.is_valid_latitude()`／`is_valid_longitude()` 拒收超出範圍的值（含 NaN），
  寫進模型的座標會原封不動送進 `sim.set()`。地圖端則在 `map.js` 送出點擊／拖曳座標前先
  `latlng.wrap()`，地圖捲過換日線時經度才不會超出 ±180。
- 刪除欄用自訂的 `DeleteButtonDelegate(QStyledItemDelegate)`：`paint()` 畫文字、`editorEvent()` 攔截點擊
  發出 `delete_requested(row)` signal。**刻意不用 `setIndexWidget()`**——那會替每一列建立一個真正的
  `QWidget` 並常駐，等於又要自己管理 widget 生命週期，違背用 `QTableView` 換掉手刻虛擬化的目的。
- 刪除欄畫的是「刪除」二字（不用 icon/emoji），`setColumnWidth(COL_DELETE, ...)` 給的欄寬要能容納
  這兩個字，改文字時兩處要一起改。
- `RoutePanel.delete_point()` 在只剩 2 個點時直接 return：路線至少要兩點才能內插，UI 層先擋掉。
  表格的刪除欄與地圖節點彈出視窗的「刪除此點」都走這個方法，兩邊共用同一道下限檢查——新增其他
  刪除入口時也要接到這裡，不要各自呼叫 `model.remove_point()`。
- **在某點前／後插入新點**走 `RoutePanel.insert_adjacent(row, after)`，入口有兩個：表格右鍵選單
  （`_show_row_menu()`，`customContextMenuRequested`）與地圖節點彈出視窗的「前面新增／後面新增」
  （`bridge.on_point_insert_requested(index, after)` → `MapPanel.point_insert_requested` →
  `MainWindow` 接到 `insert_adjacent`）。同樣先檢查 `_locked` 與列範圍，新增其他插入入口也要接到這裡，
  不要直接呼叫 `model.insert_point_at()`。新點座標由純函式 `geo.adjacent_point()` 決定：兩點之間取中點
  （路線形狀不變，所以不必歸零 `travelled_m`，也不走 `modelReset`）；路線兩端沿端點線段方向延伸同樣長度，
  只有一個點則偏移 `DEFAULT_EXTEND_DEG`；結果夾在合法經緯度內。`insert_point_at()` 要記得重新整理後面
  各列的「#」欄（跟 `remove_point()` 同理）。`map.js` 的彈出視窗按鈕共用 `bindPopupButton()`，
  新增按鈕時沿用，鎖定狀態才會一致。
- 標題列除了「新增點」還有「清空座標點」（`model.clear()`）：清空後路線只剩 0 個點，要重新在地圖上
  點或載入最愛才能再開始移動。清空前一定會先 `QMessageBox.question()` 確認：自動存檔會在兩秒內把
  空路線寫進設定，誤按就救不回來。
- `_update_info()` 由 `RouteTableModel` 的 `on_changed` callback 觸發，每次表格變動就重算總距離
  （`geo.route_length()`）、依目前速度估算的預計時間與節點數，顯示在「路線座標點」標題右邊。
  模型的每一種變動（含 `set_route()` 整條替換與 `clear()`）都經過 `_notify_changed()`，呼叫端不必自己
  再補一次 `_update_info()`。外部一律透過 `model.route`／`RoutePanel.route` 取路線，不要碰 `_route`。

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
  解析第一條 `LineString` 作為路線座標，並用起訖點附近（`KML_MARKER_MATCH_M`，50 公尺內）的 `Point`
  名稱自動當作起訖點備註，其餘中間點備註留空。距離用 `haversine()` 算（修過的 bug）：舊版直接拿經緯度
  的「度」比較，經度 1 度的長度隨緯度縮短，門檻會隨地點忽大忽小。

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

- **打包一律裝 `requirements-lock.txt`**（`build.bat` 就是這樣做的，見上方「相依套件分兩層」）：
  只照 `requirements.txt` 的範圍重新安裝，可能抓到範圍內還沒實測過的新版，打包出來才發現
  pymobiledevice3 的模組路徑變了，那時使用者手上的 exe 一按「開始移動」就「匯入失敗」。

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
- **Qt 的 OpenSSL DLL 要自己打包**（修過的 bug）：Qt 的 OpenSSL backend 在 Windows 只認
  `libssl-3-x64.dll`／`libcrypto-3-x64.dll`，PySide6 不附，`_internal` 裡 Python 的 `libssl-3.dll`
  檔名不同也不會被用到。找不到時 Qt 默默退回 SChannel，在部分電腦上連 Valhalla 會出現
  `SSL handshake failed: ... Unexpected or badly-formatted message received`。開發機通常因為
  Git for Windows 的 `mingw64\bin` 剛好有這組 DLL 而走 OpenSSL，所以只有別台電腦會壞。
  spec 的 `_find_openssl_dll()` 依序找 `PINDRIFT_OPENSSL_DIR` → PATH → `git.exe` 旁邊的
  `mingw64\bin`，都找不到就中止打包。地圖圖磚不受影響（QtWebEngine 用 Chromium 自己的 TLS）。
  - Git for Windows 預設只把 `Git\cmd` 放進 PATH（`mingw64\bin` 不在），而在 Git Bash 裡
    `shutil.which("git")` 找到的卻是 `mingw64\bin\git.exe` 本身，所以退路要**兩種位置都檢查**，
    只往上推一層或兩層都會在其中一個環境漏掉（實測踩過）。
  - **在開發機上驗證不能只看「能連線」**：開發機的 PATH 上有 Git 的 DLL，就算沒打包也會成功。
    要把 PATH 縮到只剩 `C:\Windows\System32` 與 `dist\PinDrift\_internal`，確認
    `QSslSocket.activeBackend()` 是 `openssl`；對照組拿掉 `_internal` 應該變成 `schannel`。
  - 使用者更新版本時必須連 `_internal` 整包換掉，只換 exe 的話這組 DLL 不會過去。
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
