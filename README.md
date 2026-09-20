# 📍 PinDrift — iPhone GPS 路線模擬器

> 免費、免越獄、免 iTunes，在 Windows 上模擬 iPhone GPS 定位的桌面工具。支援 iOS 26。

![Python](https://img.shields.io/badge/Python-3.14+-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-blue?logo=windows)
![iOS](https://img.shields.io/badge/ios-26-black?logo=apple)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ 功能

- 🗺 **路線移動模式** — 設定多個座標點，讓 iPhone 沿路線緩慢移動
- 📌 **固定定位模式** — 將 iPhone 定位釘在指定座標不動
- 🖱 **在地圖上直接操作** — 內嵌地圖可點選座標、點擊新增路線點、拖曳調整、點節點刪除，
  與座標表格雙向即時同步
- 🛣 **沿道路規劃路徑** — 在地圖上依序點選多個路徑點，自動算出沿實際道路、依序經過每一點的路線（支援步行／單車／開車）
- 🛰 **即時位置與軌跡** — 模擬移動時在地圖上顯示目前座標並畫出已走軌跡，可開關自動跟隨
- 🔍 **地名搜尋** — 輸入地名直接跳到該位置（OpenStreetMap Nominatim）
- 🧩 **圖磚可切換** — 內建 OpenStreetMap／CartoDB 淺色／深色，預設跟著介面主題走，也可填自訂 URL
- 📋 **座標貼上** — 從地圖複製的「緯度, 經度」可直接貼進固定座標欄位，自動拆成兩欄帶入
- ⭐ **最愛地點** — 儲存常用地點或路線，下次一鍵載入（清單依目前模式自動篩選）
- 📥 **KML 路線匯入** — 直接匯入 Google Earth / Google 地圖匯出的 KML 檔案，自動轉成路線最愛
- 🚶 **速度調整** — 支援步行、慢跑、騎車、開車等速度預設，也可自訂 km/h
- 🔄 **循環模式** — 路線走完自動再出發，可選「來回（原路折返）」或「迴圈（回到起點）」兩種走法
  （走到端點才判定，中途可隨時勾選／切換）
- ↔ **隨時切換方向** — 路線模式可隨時設定下次要走的方向（往起點 / 往終點），連線全程保持不中斷
- 🔔 **端點通知** — 沒開循環模式時走到端點會跳系統匣通知，不搶焦點、不打斷全螢幕的其他程式
- 📊 **即時進度** — 顯示目前座標、完成百分比，以及路線總距離與預計時間
- 💾 **記住上次設定** — 自動保留上次的路線座標點與移動速度
- 🌓 **深色 / 淺色主題** — 一鍵切換，偏好會自動記住
- 🚀 **一鍵啟動** — App 會自動偵測並啟動 tunneld，不必自己開系統管理員終端機
- 📦 **免安裝版** — 可打包成一個資料夾，目標機器不需要裝 Python

---

## 📋 系統需求

| 項目 | 需求 |
|------|------|
| 作業系統 | Windows 11 |
| Python | 3.14 64-bit（開發與實測環境） |
| iPhone | iOS 26 |
| 連線方式 | USB（不需 iTunes） |

---

## 🚀 安裝步驟

有兩種方式：直接用打包好的資料夾（使用者），或從原始碼執行（開發者）。

### 方式 A：免安裝版（不需要 Python）

把 `PinDrift` 資料夾整個複製到任何位置，雙擊裡面的 **`PinDrift.exe`** 即可。
資料夾內容缺一不可（`_internal` 放的是程式本體與 Qt/Chromium 執行環境），請整包一起搬。

設定與最愛（`pindrift_settings.json`／`pindrift_favorites.json`）就存在 `PinDrift.exe`
旁邊，整個資料夾複製到隨身碟或另一台機器，設定也會跟著走。

> 因為要寫入自己的資料夾，請把程式放在使用者有寫入權限的位置（桌面、文件夾、隨身碟都可以）。
> 放進 `C:\Program Files\` 會因為權限不足而存不了設定。

> 打包方式見下方 [📦 打包成免安裝版](#-打包成免安裝版)。

### 方式 B：從原始碼執行

**1. 安裝 Python 3.14 64-bit**

前往 [python.org](https://www.python.org/downloads/) 下載並安裝，記得勾選 **Add Python to PATH**。

**2. 下載本專案**

```bash
git clone https://github.com/garykillyou/PinDrift.git
cd PinDrift
```

**3. 安裝相依套件**

```bash
pip install -r requirements.txt
```

---

## ▶️ 使用方式

### Step 1：iPhone 開啟開發者模式

設定 → 隱私與安全性 → 開發者模式 → 開啟（需重開機）

### Step 2：啟動 App

免安裝版雙擊 `PinDrift.exe`；從原始碼執行則雙擊 `run.bat`。

App 一開起來就會偵測 tunneld 是否已經在執行（檢查 `127.0.0.1:49151`）。沒有的話會跳出
**UAC 視窗**要求系統管理員權限，同意後自動啟動 tunneld，過程會寫在 App 的執行日誌裡。

> tunneld 的視窗請保持開著，關掉就會斷線。啟動後等幾秒再按「開始移動」。

<details>
<summary>手動啟動 tunneld（從原始碼執行時）</summary>

以**系統管理員**開啟命令提示字元：

```bash
python -m pymobiledevice3 remote tunneld
```

等到出現以下訊息後保持視窗開著：
```
INFO: Uvicorn running on http://127.0.0.1:49151
```

再開一個新的命令提示字元執行 App：

```bash
python -m gps_qt.main
```

</details>

---

## 🖥️ 介面說明

### 地圖操作
- **固定定位模式**：在地圖上點一下就把該座標帶入緯度/經度欄位；標記也可以直接拖曳。
  如果定位正「保持中」，點地圖會立刻重新注入，人就直接搬過去。
- **路線移動模式**：在地圖上依序點擊即可加點，拖曳標記調整位置，點標記再按「刪除此點」移除
  （剩 2 個點時不能再刪，路線至少要兩點）。地圖與下方座標表格是雙向即時同步的。
- **規劃路徑（沿實際道路）**：路線模式下按「規劃路徑」，然後在地圖上依序點選要經過的點
  （至少兩點，沒有上限），再按「完成規劃」，程式就會算出沿道路依序經過每一點的路線並
  **取代目前整條路線**。游標會變成十字準心，已選的點會依序標上「起」「2」「3」…，按鈕上也會
  顯示目前已選幾點。中途再按一次「規劃路徑」可取消。
  - **移動方式**下拉選單決定走哪種路：步行可走巷弄、階梯、公園，開車只能走車道，算出來的路線差很多。
  - **簡化**下拉選單決定寫進座標表格的節點密度。路徑服務回傳的轉彎點動輒上百個
    （3 公里的步行路線約 130 點），預設「中」會抽稀到 20 幾點，路形幾乎不變但表格好讀、好手動微調。
    想完全貼合真實道路就選「關閉」。
  - 算完會在日誌顯示距離、服務估計時間與節點數。**實際模擬時間仍依你設定的移動速度**，
    不是服務估計的那個時間。
- **模擬移動中會鎖住編輯**，地圖上會顯示提示橫幅，避免走到一半路線被改掉。按「停止」即解鎖。
  此時「規劃路徑」也會一併停用。
- **即時位置與軌跡**：移動時以脈動圓點顯示目前座標並畫出走過的路徑，「清除軌跡」可隨時清掉。
- **跟隨目前位置**：預設開啟；只要你自己拖動地圖就會自動關閉，不會跟你搶畫面。
- **搜尋地名**：在搜尋框輸入後按 Enter。找到多個同名地點時會跳出清單讓你挑一個。
  固定定位模式會直接帶入座標，路線模式只把視野帶過去、不會自動加點。
- **圖磚來源**：預設「自動」跟著深色／淺色主題切換，也可以固定選一種或填自己的圖磚 URL。
- 地圖的位置、縮放、跟隨開關與圖磚選擇都會存進 `pindrift_settings.json`，下次啟動自動還原。

> 地圖圖磚需要網路連線。離線時地圖控制項仍在，只會顯示圖磚載入失敗的提示。

### 路線移動模式
1. 在地圖上點擊加點，或在座標表格中輸入路線點（緯度、經度、備註），也可用「新增點」增加、點該列的
   「刪除」移除，或用「清空座標點」整批清掉重來
2. 選擇移動速度（預設按鈕或自訂 km/h），標題列會即時顯示總距離、預計時間與節點數
3. 按「開始移動」沿路線往終點走
4. 「往起點 / 往終點」只是設定**下次**要走的方向，按下去不會立刻開始走，要再按「開始移動」；
   按鈕文字顯示的是「按下去會變成哪個方向」。移動中不能切換，要先按「停止」
5. 勾選「循環模式」後走到端點會自動繼續，旁邊的下拉選單可選「來回（原路折返）」或
   「迴圈（回到起點）」；沒勾選時走到端點會停在那裡，並跳出系統匣通知
6. 按「停止」暫停在目前座標（連線保持，不會恢復真實定位）
7. 按「恢復真實定位」才會真正斷線，iPhone 恢復真實 GPS（移動中需先按「停止」）

### 固定定位模式
1. 切換到「固定定位」模式
2. 在地圖上點選、輸入緯度/經度，或使用快速選擇；也可以把「24.1368, 120.6862」這種字串直接貼進任一欄自動帶入
3. 按「固定定位」釘住座標
4. 按「停止」保持在目前座標（連線保持，不會恢復真實定位）
5. 按「恢復真實定位」才會真正斷線，iPhone 恢復真實 GPS

### 最愛地點
- 清單只會顯示目前模式對應的項目，按鈕也跟著切換：
  - 固定定位模式：「儲存目前座標」
  - 路線移動模式：「儲存目前路線」、「匯入 KML 路線」
- 「匯入 KML 路線」可選擇 KML 檔案，自動解析路線座標並存成路線最愛
- 點「載入」一鍵套用（會同時切換到對應的模式並把地圖縮放到該地點／路線），「編輯」可重新命名，「刪除」可移除
- 固定定位模式下，已儲存的**地點**最愛會以半透明的紫色圓點畫在地圖上，直接點一下就等同按「載入」
  （路線最愛不畫在地圖上，避免跟正在編輯的路線混淆）
- 資料儲存於 `pindrift_favorites.json`，重開 App 後保留

### 主題切換
- 點右上角的主題按鈕，即可在深色／淺色介面間切換
- 偏好會存於 `pindrift_settings.json`，下次啟動自動套用上次選擇

### 視窗位置記憶
- 關閉 App 時會記住視窗的大小、位置與是否最大化，下次啟動自動還原（多螢幕環境會回到上次使用的那一台螢幕）
- 若上次使用的螢幕已經拔掉或解析度改變，會自動退回預設大小、由 Windows 決定擺放位置，不會讓視窗開在看不見的地方
- 同時也會記住上次的路線座標點與移動速度

---

## 📁 檔案結構

```
PinDrift/
├── gps_qt/                 # 主程式（GUI App，PySide6 + qasync + qt-material）
│   └── web/                # 內嵌地圖頁面（Leaflet，含本地副本，不依賴 CDN）
├── tests/                  # 純函式測試（pytest）
├── conftest.py             # 讓 pytest 找得到 gps_qt 套件
├── requirements.txt        # 相依套件
├── requirements-dev.txt    # 測試相依（執行 App 本身不需要）
├── requirements-build.txt  # 打包相依（PyInstaller，執行 App 本身不需要）
├── run.bat                 # 啟動捷徑（免主控台視窗啟動）
├── build.bat               # 打包捷徑（產生 dist/PinDrift/）
├── PinDrift.spec           # PyInstaller 設定
├── app_entry.py            # 打包用的主程式進入點
├── tunneld_entry.py        # 打包用的 tunneld 進入點
├── pindrift_favorites.json # 最愛地點資料（自動產生）
├── pindrift_settings.json  # 主題、視窗位置、上次路線與速度、地圖設定（自動產生）
├── .gitattributes          # vendored 的 Leaflet 檔案不做行尾轉換
├── LICENSE                 # MIT 授權條款全文
└── README.md
```

打包後的 `dist/PinDrift/` 長這樣：

```
PinDrift/
├── PinDrift.exe            # 主程式（雙擊這個）
├── PinDrift-tunneld.exe    # tunneld，由主程式提權啟動，不用自己點
├── _internal/              # 程式本體與 Qt/Chromium 執行環境（不要刪、不要搬）
├── pindrift_settings.json  # 設定（第一次關閉程式時自動產生）
└── pindrift_favorites.json # 最愛（存了第一筆之後才會出現）
```

---

## 📦 打包成免安裝版

在已經可以從原始碼執行的環境下，雙擊 `build.bat`（或執行下面的指令），會在 `dist\PinDrift\`
產生一個可以整包交付的資料夾，目標機器不需要安裝 Python：

```bash
pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean PinDrift.spec
```

- 成品約 **510 MB**，主要是 QtWebEngine（內嵌的 Chromium）本身的體積，這是內嵌地圖的固定成本。
- 刻意用**資料夾**而不是單一 exe：QtWebEngine 會另外開子行程，單檔模式每次啟動都要解壓縮，
  又慢又容易出問題。
- 要縮成一個檔案交付的話，把資料夾用 7-Zip 之類的工具壓成自解壓縮檔，或用 Inno Setup 做成安裝檔。

---

## ⚠️ 注意事項

- 本工具僅供學習、測試用途
- 部分遊戲或 App 有反作弊機制，使用需自行承擔風險
- **按「停止」不會恢復真實定位**：連線會保持著、定位停在目前座標。要讓 iPhone 回到真實 GPS，
  必須按「恢復真實定位」（或直接關閉 App / tunneld）

---

## 🛠️ 技術說明

本專案使用 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 與 iPhone 通訊。

iOS 26 需透過 RemoteXPC tunnel 連線，因此需要先啟動 `tunneld` 服務建立加密通道，再透過 DVT（Developer Tools）的 `LocationSimulation` 服務注入模擬座標。

App 全程只建立一條長連線：開始、切換方向、停止都只是改變狀態，不會重連；唯有按下「恢復真實定位」才會
關閉連線並讓裝置回到真實 GPS。

地圖是用 `QWebEngineView` 載入本地的 [Leaflet](https://leafletjs.com/) 頁面，與 Python 之間透過
`QWebChannel` 雙向溝通。Leaflet 本體放在專案內（`gps_qt/web/vendor/`），不依賴 CDN。

路徑規劃使用 [Valhalla](https://valhalla.github.io/valhalla/) 的 FOSSGIS 公用實例，免申請金鑰，
支援步行／單車／開車三種路網。回傳的路徑會用 Douglas-Peucker 演算法抽稀後才寫進座標表格。

> 圖磚來自 [OpenStreetMap](https://www.openstreetmap.org/copyright) 與
> [CARTO](https://carto.com/attributions) 的公用服務，僅適合個人輕量使用，並保留了原始的版權標示。
> 地名搜尋使用 [Nominatim](https://operations.osmfoundation.org/policies/nominatim/)，
> 依其政策限制為每秒最多一次請求。路徑規劃使用
> [FOSSGIS 的 Valhalla 實例](https://gis-ops.com/global-open-valhalla-server-online/)，政策為合理使用。
> 這些都是社群維運的免費服務，請勿拿來做批次大量查詢。App 本身也把地名搜尋與路徑規劃限制成每秒
> 最多一次請求，按太快會在日誌顯示「請稍候再試」。

---

## 🧪 測試

只涵蓋不需要 Qt 事件迴圈的純邏輯（距離計算、內插、路徑簡化、polyline 解碼、
地圖 payload 序列化、搜尋結果解析、設定正規化、JSON 存檔失敗處理）：

```bash
pip install -r requirements-dev.txt
python -m pytest
```

---

## 📄 License

MIT License — 條款全文見 [LICENSE](LICENSE)。

---

## 🙏 致謝

本專案最初 fork 自 [JRTTF/PikminBloom](https://github.com/JRTTF/PikminBloom)，該專案在其 README 中
聲明採用 MIT License。原始的 CustomTkinter 版本（`gps_app.py`）已完全移除，目前的 `gps_qt/` 是
以 PySide6 從頭重寫的版本。
