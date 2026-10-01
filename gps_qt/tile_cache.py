"""圖磚的本機快取：瀏覽過的圖磚存到磁碟，之後（包括離線時）直接從本機讀。

做法是讓 Leaflet 改向自訂的 `pdtile:` scheme 要圖磚（`cached_url_template()`），
由 tile_scheme.TileSchemeHandler 先查這裡的快取，沒有才代為連線下載並存起來。
**只快取「看過的」圖磚，不做範圍批次下載**：OpenStreetMap 官方圖磚政策明文禁止
bulk download，CARTO 免費圖磚的條款也不允許。

這個模組只放純函式（路徑、檔案格式、新鮮度、容量上限），不相依 Qt，可以單獨測試。
"""

import hashlib
import logging
import os
import re
import time

from . import paths

logger = logging.getLogger(__name__)

TILE_SCHEME = "pdtile"
_SCHEME_PREFIX = TILE_SCHEME + ":"
_UPSTREAM_SCHEMES = ("http://", "https://")

TILE_CACHE_DIR = paths.data_file("tile_cache")
# 快取在這段時間內直接使用、不連線；過期後有網路就重新下載，沒網路仍用舊的。
# 90 天內不重新下載，對公用圖磚伺服器也比較友善；代價是地圖資料最多晚 90 天更新。
TILE_FRESH_SECONDS = 90 * 24 * 3600
# 一張圖磚約 10～50 KB，500 MB 大約是十幾萬張，足夠常去的幾個城市各看好幾層縮放。
TILE_CACHE_MAX_BYTES = 500 * 1024 * 1024
# 超過上限時刪到上限的這個比例，不會每次啟動都只刪剛好超出的那幾張。
TILE_CACHE_PRUNE_RATIO = 0.8
_TMP_SUFFIX = ".tmp"

_CONTENT_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
)
FALLBACK_CONTENT_TYPE = "image/png"

# `{s}` 子網域（a／b／c／d）展開後只有一個英文字母的主機標籤，例如 `a.basemaps.cartocdn.com`。
_SUBDOMAIN_LABEL = re.compile(r"^(https?://)[a-d]\.", re.IGNORECASE)


def cached_url_template(url):
    """把圖磚 URL 樣板改走本機快取；非 http(s)（例如自訂的 file://）原樣回傳。

    Leaflet 只做 {z}/{x}/{y}/{s}/{r} 的字串替換，不在乎 scheme，所以直接在前面
    加上 `pdtile:` 即可，展開後的完整上游網址就是 `pdtile:` 後面那一段。
    """
    if not url.lower().startswith(_UPSTREAM_SCHEMES):
        return url
    return _SCHEME_PREFIX + url


def upstream_url(requested):
    """從 `pdtile:https://...` 取回上游網址；格式不對或不是 http(s) 回傳 None。

    這是頁面送進來的字串，只放行 http(s)，不讓頁面透過它讀到 file:// 之類的本機資源。
    """
    if not requested.startswith(_SCHEME_PREFIX):
        return None
    upstream = requested[len(_SCHEME_PREFIX):]
    if not upstream.lower().startswith(_UPSTREAM_SCHEMES):
        return None
    return upstream


def _cache_key(upstream):
    """快取用的網址：把 `{s}` 展開出來的單字母子網域統一成 `s`。

    Leaflet 會把 `{s}` 隨機展開成 a／b／c，同一張圖磚因此有三個網址；不統一的話
    會存三份、命中率也只剩三分之一。下載仍用原網址，這裡只影響檔名。
    """
    return _SUBDOMAIN_LABEL.sub(r"\g<1>s.", upstream)


def cache_file_path(root, upstream):
    """圖磚在快取裡的檔案路徑。

    用上游網址的 SHA-1 當檔名，而不是照著網址路徑建資料夾：網址是頁面給的字串，
    直接拿來組路徑就得自己擋 `..` 之類的路徑穿越；雜湊值只會是十六進位字元。
    前兩碼再分一層資料夾，免得單一資料夾裡塞了十幾萬個檔案。
    """
    digest = hashlib.sha1(_cache_key(upstream).encode("utf-8")).hexdigest()
    return os.path.join(root, digest[:2], digest)


def _sniff_content_type(data):
    for magic, content_type in _CONTENT_TYPES:
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def content_type_of(data):
    """依檔案開頭的特徵碼判斷圖片格式（快取裡沒有另存 Content-Type）。"""
    return _sniff_content_type(data) or FALLBACK_CONTENT_TYPE


def is_image(data):
    """內容是不是看得出來的圖片格式。

    下載回應只看 HTTP 200 不夠：captive portal 的登入頁、限流頁常常也是 200，
    把它們當圖磚存起來，地圖會壞到快取過期為止。
    """
    return _sniff_content_type(data) is not None


def is_fresh(mtime, now):
    return now - mtime < TILE_FRESH_SECONDS


def read_cached(path):
    """回傳 (內容, 存入時間)；沒有快取或讀不到回傳 None（當成沒快取，改走網路）。"""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if not data:
        return None
    return data, mtime


def write_cached(path, data):
    """寫入快取，失敗回傳錯誤訊息字串（成功回傳 None），不丟例外。

    與設定檔一樣先寫 `.tmp` 再 `os.replace()`：寫到一半當機不會留下殘缺的圖磚，
    下次讀到半張圖。放在唯讀位置時寫不進去，地圖照樣從網路顯示，只是沒有快取。
    """
    tmp_path = path + _TMP_SUFFIX
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "wb") as handle:
            handle.write(data)
        os.replace(tmp_path, path)
    except OSError as exc:
        return f"圖磚快取寫入失敗（{path}）：{exc}"
    return None


def _cache_entries(root):
    """列出快取裡的 (修改時間, 大小, 路徑)，讀不到的檔案略過。

    `.tmp` 是正在寫入的檔案，不列入：刪掉的話那次寫入的 os.replace() 會失敗。
    """
    entries = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(_TMP_SUFFIX):
                continue
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
    return entries


def prune_cache(root=TILE_CACHE_DIR, max_bytes=TILE_CACHE_MAX_BYTES,
                ratio=TILE_CACHE_PRUNE_RATIO):
    """總量超過 max_bytes 時從最舊的開始刪，刪到 max_bytes * ratio 以下。

    回傳 (刪掉的檔案數, 釋出的位元組數)。刪不掉的檔案略過（可能正被讀取）。
    """
    entries = _cache_entries(root)
    total = sum(size for _mtime, size, _path in entries)
    if total <= max_bytes:
        return 0, 0
    target = max_bytes * ratio
    removed = freed = 0
    for _mtime, size, path in sorted(entries):
        if total - freed <= target:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


def prune_cache_logged():
    """背景執行緒用的包裝：結果只寫進記錄檔（這裡不能碰 Qt 物件）。"""
    started = time.monotonic()
    removed, freed = prune_cache()
    if removed:
        logger.info(
            "圖磚快取超過上限，刪除 %d 個最舊的檔案（%.1f MB，耗時 %.1f 秒）",
            removed, freed / 1024 / 1024, time.monotonic() - started,
        )
