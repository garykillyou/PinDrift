"""路徑規劃：Valhalla（FOSSGIS 公用實例）。

沿實際道路算出依序經過多個點的路徑，取代原本點與點之間走直線的內插。選 Valhalla 的
公用實例是因為它不需要申請 API 金鑰，而且支援步行／單車／開車三種 costing——
步行與開車算出來的路線差很多（行人可走巷弄、階梯、公園，車輛只能走車道），
對這個工具來說是必要的區分。

與 geocode.py 一樣用 QNetworkAccessManager 而非 urllib：非同步、直接跑在 Qt
事件迴圈上，等待路徑期間 UI 不會卡住。

> 這是社群維運的免費服務，使用政策是「合理使用」。個人工具的用量沒有問題，
> 但不要拿去做批次大量查詢。
"""

import json

from PySide6.QtCore import QDateTime, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
USER_AGENT = "PinDrift-GPS-Simulator/1.0 (https://github.com/garykillyou/PinDrift)"
MIN_REQUEST_INTERVAL_MS = 1000

COSTING_PEDESTRIAN = "pedestrian"
COSTING_BICYCLE = "bicycle"
COSTING_AUTO = "auto"

# Valhalla 的 shape 是 Google polyline 演算法、精度 1e6（一般的 polyline 是 1e5）。
POLYLINE_PRECISION = 1e6


class Router(QObject):
    """把一次路徑查詢包成 route_ready / failed 兩個 signal。

    同時間只保留最後一次查詢：使用者連續規劃兩次時，前一個還沒回來的請求直接
    中止，避免舊路徑比新路徑晚到而覆蓋掉座標表格。
    """

    route_ready = Signal(list, float, float)  # [(lat, lon), ...], 距離(公里), 時間(秒)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._last_request_ms = 0

    def route(self, waypoints, costing=COSTING_PEDESTRIAN):
        """waypoints 為 [(lat, lon), ...]，依序經過每一點，至少要有 2 個。"""
        now = QDateTime.currentMSecsSinceEpoch()
        if now - self._last_request_ms < MIN_REQUEST_INTERVAL_MS:
            self.failed.emit("路徑規劃請求太頻繁，請稍候再試")
            return
        self._last_request_ms = now

        self._abort_pending()
        request = QNetworkRequest(QUrl(VALHALLA_URL))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        body = json.dumps({
            "locations": [
                {"lat": float(lat), "lon": float(lon)} for lat, lon in waypoints
            ],
            "costing": costing,
            "directions_options": {"units": "kilometers"},
        }).encode("utf-8")
        self._reply = self._manager.post(request, body)
        self._reply.finished.connect(self._on_finished)

    def _abort_pending(self):
        if self._reply is not None and not self._reply.isFinished():
            self._reply.abort()
        self._reply = None

    def _on_finished(self):
        reply = self.sender()
        reply.deleteLater()
        if reply is not self._reply:
            return  # 已被新的查詢取代，忽略這份過期結果
        self._reply = None

        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return
        body = bytes(reply.readAll().data())
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.failed.emit("路徑規劃失敗：" + (_error_message(body) or reply.errorString()))
            return

        try:
            raw = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            self.failed.emit("路徑規劃結果解析失敗：" + str(e))
            return

        try:
            points, length_km, time_sec = parse_route(raw)
        except ValueError as e:
            self.failed.emit("路徑規劃結果解析失敗：" + str(e))
            return
        if len(points) < 2:
            self.failed.emit("路徑規劃失敗：這兩個座標之間找不到可通行的路徑")
            return
        self.route_ready.emit(points, length_km, time_sec)


def _error_message(body):
    """Valhalla 失敗時回的是 JSON 錯誤物件，取出裡面的說明比 HTTP 狀態碼有用。"""
    try:
        return str(json.loads(body.decode("utf-8")).get("error", "")) or None
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None


def _decode_value(encoded, index):
    """解出一個 polyline 變長整數，回傳 (數值, 下一個起始位置)。"""
    shift = result = 0
    while index < len(encoded):
        byte = ord(encoded[index]) - 63
        index += 1
        result |= (byte & 0x1F) << shift
        shift += 5
        if byte < 0x20:
            return (~(result >> 1) if result & 1 else result >> 1), index
    raise ValueError("polyline 字串在編碼中途結束")


def decode_polyline6(encoded):
    """解碼 Valhalla 的 shape 字串，回傳 [(lat, lon), ...]。

    就是 Google 的 polyline 演算法，只是精度用 1e6 而非常見的 1e5；
    用錯精度不會報錯，只會讓座標差了十倍，所以這裡把精度寫成具名常數。
    """
    points = []
    index = lat = lon = 0
    while index < len(encoded):
        dlat, index = _decode_value(encoded, index)
        dlon, index = _decode_value(encoded, index)
        lat += dlat
        lon += dlon
        points.append((lat / POLYLINE_PRECISION, lon / POLYLINE_PRECISION))
    return points


def parse_route(raw):
    """把 Valhalla 的回應整理成 (points, 距離公里, 時間秒)。

    抽成純函式方便測試。多個 leg 之間的接縫點會重複（前一段的終點等於下一段的
    起點），這裡會去掉重複的那一個，避免路線裡出現距離為零的相鄰點。
    """
    trip = raw.get("trip") or {}
    points = []
    for leg in trip.get("legs") or []:
        shape = leg.get("shape")
        if not shape:
            continue
        decoded = decode_polyline6(shape)
        if points and decoded and points[-1] == decoded[0]:
            decoded = decoded[1:]
        points.extend(decoded)
    summary = trip.get("summary") or {}
    try:
        length_km = float(summary.get("length", 0.0))
        time_sec = float(summary.get("time", 0.0))
    except (TypeError, ValueError):
        length_km = time_sec = 0.0
    return points, length_km, time_sec
