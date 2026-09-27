"""地圖圖磚來源：內建清單，以及依設定與主題決定目前要用哪一組。

純資料與純函式，不相依 QtWebEngine，所以不開地圖也能單獨測試。
"""

import html

AUTO_TILE = "auto"
CUSTOM_TILE = "custom"
FALLBACK_TILE = "osm"

# (設定值, 下拉選單文字, URL 樣板, 版權標示)
# Leaflet 原生支援 {s}（子網域）與 {r}（高解析度後綴），不需要自己展開。
# 版權標示會被 Leaflet 當成 HTML 插入頁面，這裡的 &copy; 是刻意寫的 HTML 實體。
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


def resolve_tile(map_settings, theme_name):
    """回傳 (URL 樣板, 可直接交給 Leaflet 的版權標示 HTML)。

    自訂圖磚的版權標示是使用者輸入的純文字，一律 escape 後才交出去（修過的
    安全問題）：Leaflet 會把 attribution 當 HTML 插進頁面，而那個頁面能呼叫
    QWebChannel bridge，貼進一段 <img onerror=...> 就等於能在頁面裡執行任意 JS。
    內建清單的版權標示是寫死的 HTML，原樣交出，&copy; 才不會被 escape 壞掉。
    """
    key = map_settings.get("tile_source", AUTO_TILE)
    if key == AUTO_TILE:
        key = THEME_TILE.get(theme_name, FALLBACK_TILE)
    if key == CUSTOM_TILE:
        url = map_settings.get("custom_tile_url", "")
        if url:
            return url, html.escape(map_settings.get("custom_attribution", ""))
        key = FALLBACK_TILE
    entry = TILE_BY_KEY.get(key) or TILE_BY_KEY[FALLBACK_TILE]
    return entry[2], entry[3]
