"""persistence.parse_kml_route() 的測試。"""

import math

from gps_qt.geo import METERS_PER_DEGREE
from gps_qt.persistence import parse_kml_route

KML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>測試路線</name>
    <Placemark><name>路線</name>
      <LineString><coordinates>{start_lon},{start_lat},0 {end_lon},{end_lat},0</coordinates></LineString>
    </Placemark>
    <Placemark><name>{marker_name}</name>
      <Point><coordinates>{marker_lon},{marker_lat},0</coordinates></Point>
    </Placemark>
  </Document>
</kml>
"""


def _write_kml(tmp_path, start, end, marker, marker_name="車站"):
    path = tmp_path / "route.kml"
    path.write_text(KML_TEMPLATE.format(
        start_lat=start[0], start_lon=start[1], end_lat=end[0], end_lon=end[1],
        marker_lat=marker[0], marker_lon=marker[1], marker_name=marker_name,
    ), encoding="utf-8")
    return str(path)


def _east_of(point, meters):
    """point 往東 meters 公尺的座標（經度 1 度的長度要乘上 cos(緯度)）。"""
    lat, lon = point
    return lat, lon + meters / (METERS_PER_DEGREE * math.cos(math.radians(lat)))


def test_parse_kml_route_names_the_start_from_a_nearby_marker(tmp_path):
    # Arrange
    start, end = (24.0, 120.0), (24.01, 120.0)
    path = _write_kml(tmp_path, start, end, marker=_east_of(start, 20))

    # Act
    route, doc_name = parse_kml_route(path)

    # Assert
    assert doc_name == "測試路線"
    assert route[0] == [24.0, 120.0, "車站"]
    assert route[-1][2] == ""


def test_parse_kml_route_uses_real_distance_at_high_latitude(tmp_path):
    """門檻是 50 公尺的實際距離，不是 0.0005 度。

    舊版直接拿經緯度的「度」算距離，沒有乘上 cos(緯度)：緯度 60 度時經度 0.0005 度
    只有約 28 公尺，往東 45 公尺的地標會被誤判成太遠（修過的 bug）。
    """
    # Arrange
    start, end = (60.0, 10.0), (60.01, 10.0)
    path = _write_kml(tmp_path, start, end, marker=_east_of(start, 45))

    # Act
    route, _doc_name = parse_kml_route(path)

    # Assert
    assert route[0][2] == "車站"


def test_parse_kml_route_ignores_markers_beyond_threshold(tmp_path):
    # Arrange：地標在起點東邊 80 公尺
    start, end = (24.0, 120.0), (24.01, 120.0)
    path = _write_kml(tmp_path, start, end, marker=_east_of(start, 80))

    # Act
    route, _doc_name = parse_kml_route(path)

    # Assert
    assert route[0][2] == ""
