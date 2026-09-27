"""geo.py 的純函式測試。"""

import math

import pytest

from gps_qt.geo import (
    cumulative_distances,
    douglas_peucker,
    haversine,
    index_at_distance,
    interpolate_points,
    route_length,
    simplify_route,
)

EARTH_RADIUS_M = 6371000
ONE_DEGREE_LAT_M = math.radians(1) * EARTH_RADIUS_M  # 約 111194.9 公尺


def test_haversine_returns_zero_for_identical_points():
    # Arrange / Act
    distance = haversine(24.1368, 120.6862, 24.1368, 120.6862)

    # Assert
    assert distance == 0


def test_haversine_matches_one_degree_of_latitude():
    # Arrange / Act
    distance = haversine(24.0, 120.0, 25.0, 120.0)

    # Assert：容差 1 公尺
    assert distance == pytest.approx(ONE_DEGREE_LAT_M, abs=1.0)


def test_interpolate_points_keeps_both_endpoints():
    # Arrange
    route = [(24.0, 120.0, ""), (25.0, 120.0, "")]
    speed_ms = ONE_DEGREE_LAT_M / 10  # 每秒走十分之一段，預期切成 10 段

    # Act
    points = interpolate_points(route, speed_ms, 1.0)

    # Assert
    assert points[0] == (24.0, 120.0)
    assert points[-1] == (25.0, 120.0)
    assert len(points) == 11


def test_interpolate_points_handles_speed_faster_than_whole_route():
    # Arrange：速度快到一秒就走完整段，至少也要保留起點與終點
    route = [(24.0, 120.0, ""), (24.001, 120.0, "")]

    # Act
    points = interpolate_points(route, 10000.0, 1.0)

    # Assert
    assert points[0] == (24.0, 120.0)
    assert points[-1] == (24.001, 120.0)


def _step_lengths(points):
    return [haversine(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])]


def test_interpolate_points_keeps_speed_on_segments_shorter_than_one_step():
    """路線點比「每秒該走的距離」還密時，每秒仍要走滿設定的速度。

    舊版逐段切割，一段不到一步也會佔掉一整秒：3 公尺一段、以 11 公尺/秒走，
    實際速度只剩四分之一左右（修過的 bug）。
    """
    # Arrange：每段約 3.3 公尺，共 300 段、約 1 公里
    route = [(24.0 + i * 0.00003, 120.0, "") for i in range(301)]
    speed_ms = 11.0

    # Act
    points = interpolate_points(route, speed_ms, 1.0)

    # Assert：每一步都接近 11 公尺，總步數接近「總距離 / 速度」
    steps = _step_lengths(points)
    total = cumulative_distances([(r[0], r[1]) for r in route])[-1]
    assert all(step == pytest.approx(speed_ms, rel=0.02) for step in steps)
    assert len(steps) == round(total / speed_ms)


def test_interpolate_points_does_not_speed_up_on_a_segment_just_under_two_steps():
    """一段是 1.9 步長時，舊版 int() 捨去成 1 步，那一秒會跑出將近兩倍速。"""
    # Arrange：兩段各約 19 公尺，速度 10 公尺/秒
    route = [(24.0, 120.0, ""), (24.00017, 120.0, ""), (24.00034, 120.0, "")]

    # Act
    points = interpolate_points(route, 10.0, 1.0)

    # Assert
    assert max(_step_lengths(points)) < 12.0


def test_interpolate_points_samples_on_the_route_across_corners():
    # Arrange：L 形路線，各邊約 111 公尺
    route = [(24.0, 120.0, ""), (24.001, 120.0, ""), (24.001, 120.001, "")]

    # Act
    points = interpolate_points(route, 5.0, 1.0)

    # Assert：每個取樣點都落在兩條邊之一上
    for lat, lon in points:
        on_first_leg = lon == pytest.approx(120.0) and 24.0 <= lat <= 24.001 + 1e-12
        on_second_leg = lat == pytest.approx(24.001) and 120.0 <= lon <= 120.001 + 1e-12
        assert on_first_leg or on_second_leg


def test_interpolate_points_handles_route_with_zero_length():
    # Arrange：所有點重疊，總長為 0
    route = [(24.0, 120.0, ""), (24.0, 120.0, ""), (24.0, 120.0, "")]

    # Act
    points = interpolate_points(route, 5.0, 1.0)

    # Assert
    assert points == [(24.0, 120.0), (24.0, 120.0)]


def test_douglas_peucker_keeps_endpoints_and_drops_collinear_points():
    # Arrange：一條直線上均勻取點，中間點對路形沒有貢獻
    points = [(24.0 + i * 0.001, 120.0) for i in range(11)]

    # Act
    simplified = douglas_peucker(points, 5.0)

    # Assert
    assert simplified == [points[0], points[-1]]


def test_douglas_peucker_keeps_a_significant_corner():
    # Arrange：中間點偏離直線約 111 公尺，遠大於 5 公尺容差
    points = [(24.0, 120.0), (24.0005, 120.001), (24.0, 120.002)]

    # Act
    simplified = douglas_peucker(points, 5.0)

    # Assert
    assert simplified == points


def test_douglas_peucker_drops_a_corner_below_tolerance():
    # Arrange：中間點只偏離約 1 公分，遠小於 5 公尺容差
    points = [(24.0, 120.0), (24.0000001, 120.001), (24.0, 120.002)]

    # Act
    simplified = douglas_peucker(points, 5.0)

    # Assert
    assert simplified == [points[0], points[-1]]


def test_douglas_peucker_returns_input_when_disabled():
    # Arrange
    points = [(24.0, 120.0), (24.0005, 120.001), (24.0, 120.002)]

    # Act / Assert：容差 0 代表關閉簡化
    assert douglas_peucker(points, 0) == points


def test_douglas_peucker_handles_long_input_without_recursion_limit():
    # Arrange：用顯式堆疊而非遞迴，點數上千也不該撞到遞迴上限
    points = [(24.0 + i * 0.00001, 120.0 + (i % 2) * 0.00002) for i in range(3000)]

    # Act
    simplified = douglas_peucker(points, 5.0)

    # Assert
    assert simplified[0] == points[0]
    assert simplified[-1] == points[-1]
    assert len(simplified) < len(points)


def test_cumulative_distances_starts_at_zero_and_accumulates():
    points = [(25.0, 121.0), (25.001, 121.0), (25.002, 121.0)]

    totals = cumulative_distances(points)

    assert len(totals) == len(points)
    assert totals[0] == 0.0
    assert totals[1] == pytest.approx(111.19, abs=0.1)
    assert totals[2] == pytest.approx(222.39, abs=0.1)


def test_index_at_distance_picks_the_nearest_index():
    cumulative = [0.0, 10.0, 20.0, 30.0]

    assert index_at_distance(cumulative, -5.0) == 0
    assert index_at_distance(cumulative, 9.0) == 1
    assert index_at_distance(cumulative, 14.0) == 1
    assert index_at_distance(cumulative, 16.0) == 2
    assert index_at_distance(cumulative, 999.0) == 3


def test_progress_survives_a_speed_change_midway():
    """停止後改速度再開始移動，必須從原地繼續，不能被夾到路線終點。

    進度若記成「第幾個內插點」，加速後內插點變少，中途的索引會超出範圍而被
    夾到最後一點，人就直接瞬移到終點（修過的 bug）。
    """
    route = [(25.0, 121.0, ""), (25.02, 121.0, "")]  # 約 2.2 公里

    slow = interpolate_points(route, 1.4, 1.0)       # 步行速度，內插點很多
    slow_totals = cumulative_distances(slow)
    stopped_at = len(slow) // 2
    travelled = slow_totals[stopped_at]

    fast = interpolate_points(route, 16.7, 1.0)      # 加速到 60 km/h，內插點變少
    fast_totals = cumulative_distances(fast)
    resumed_at = index_at_distance(fast_totals, travelled)

    assert resumed_at < len(fast) - 1
    assert fast_totals[resumed_at] == pytest.approx(travelled, abs=20.0)
    assert fast[resumed_at][0] == pytest.approx(slow[stopped_at][0], abs=0.0002)


def test_simplify_route_drops_collinear_rows_and_keeps_endpoint_notes():
    # Arrange：路線表格的列是 [lat, lon, note]，中間點都在直線上
    route = [[24.0 + i * 0.001, 120.0, ""] for i in range(11)]
    route[0][2], route[-1][2] = "起點", "終點"

    # Act
    simplified = simplify_route(route, 5.0)

    # Assert
    assert simplified == [[24.0, 120.0, "起點"], [24.01, 120.0, "終點"]]


def test_simplify_route_keeps_rows_with_notes_even_on_a_straight_line():
    # Arrange：第 5 點落在直線上，但有使用者備註，不能被抽掉
    route = [[24.0 + i * 0.001, 120.0, ""] for i in range(11)]
    route[5][2] = "便利商店"

    # Act
    simplified = simplify_route(route, 5.0)

    # Assert
    assert [row[2] for row in simplified] == ["", "便利商店", ""]
    assert simplified[1][:2] == route[5][:2]


def test_simplify_route_returns_copies_without_mutating_input():
    # Arrange
    route = [[24.0, 120.0, "起點"], [24.001, 120.0, ""], [24.002, 120.0, "終點"]]
    original = [list(row) for row in route]

    # Act
    simplified = simplify_route(route, 5.0)
    simplified[0][2] = "改過"

    # Assert
    assert route == original


def test_simplify_route_returns_input_when_disabled():
    # Arrange
    route = [[24.0 + i * 0.001, 120.0, ""] for i in range(5)]

    # Act / Assert：容差 0 代表關閉簡化
    assert simplify_route(route, 0) == route


def test_route_length_sums_segment_distances():
    # Arrange：[lat, lon, note] 的列，兩段各約 111.19 公尺
    route = [[25.0, 121.0, "起點"], [25.001, 121.0, ""], [25.002, 121.0, "終點"]]

    # Act / Assert
    assert route_length(route) == pytest.approx(222.39, abs=0.1)


def test_route_length_is_zero_for_fewer_than_two_points():
    assert route_length([]) == 0.0
    assert route_length([[25.0, 121.0, ""]]) == 0.0


def test_cumulative_distances_of_empty_input_is_empty():
    # 長度必須與輸入相同：回傳 [0.0] 會讓呼叫端以為有一個點
    assert cumulative_distances([]) == []
