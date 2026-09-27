"""地名搜尋：OpenStreetMap Nominatim。

刻意由 Python 端發送而不是在 map.js 裡 fetch()：Nominatim 的使用政策要求
每個請求帶可識別的 User-Agent、且每秒最多一次；在 QWebEngine 裡發出的
fetch() 帶的是瀏覽器的 User-Agent，改不掉也不合規，節流也難以控管。
節流、User-Agent 與「只保留最後一次查詢」都在 netclient.SingleFlightClient。
"""

import json

from PySide6.QtCore import QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkReply

from .netclient import SingleFlightClient

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RESULT_LIMIT = 8


class Geocoder(SingleFlightClient):
    """把一次地名查詢包成 results_ready / failed 兩個 signal。

    同時間只保留最後一次查詢：使用者連打兩次 Enter 時，前一個還沒回來的請求
    直接中止，避免舊結果比新結果晚到而覆蓋掉畫面。
    """

    results_ready = Signal(list)  # [{"name": str, "lat": float, "lon": float}, ...]
    THROTTLED_MESSAGE = "搜尋請求太頻繁（Nominatim 限制每秒 1 次），請稍候再試"

    def search(self, query):
        query = (query or "").strip()
        if not query:
            return
        url = QUrl(NOMINATIM_URL)
        params = QUrlQuery()
        params.addQueryItem("q", query)
        params.addQueryItem("format", "json")
        params.addQueryItem("limit", str(RESULT_LIMIT))
        params.addQueryItem("accept-language", "zh-TW")
        url.setQuery(params)
        request = self.new_request(url)
        self._send(lambda manager: manager.get(request))

    def _handle_reply(self, reply):
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.failed.emit("搜尋失敗：" + reply.errorString())
            return

        try:
            raw = json.loads(bytes(reply.readAll().data()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            self.failed.emit("搜尋結果解析失敗：" + str(e))
            return

        self.results_ready.emit(parse_results(raw))


def parse_results(raw):
    """把 Nominatim 的回應整理成 [{"name", "lat", "lon"}, ...]。

    抽成純函式方便測試；格式不合的項目直接跳過而不是讓整次查詢失敗——
    Nominatim 偶爾會回傳沒有座標的項目。
    """
    if not isinstance(raw, list):
        return []
    results = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            results.append({
                "name": str(item.get("display_name", "")),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return results
