"""geo.py 的純函式測試。"""

import math

import pytest

from gps_qt.geo import (
    RouteSampler,
    cumulative_distances,
    douglas_peucker,
    haversine,
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


def _all_points(sampler):
    return [sampler.point(k) for k in range(sampler.last_index + 1)]


def test_sampler_keeps_both_endpoints():
    # Arrange
    route = [(24.0, 120.0, ""), (25.0, 120.0, "")]
    step_m = ONE_DEGREE_LAT_M / 10  # 每步走十分之一段，預期切成 10 段

    # Act
    sampler = RouteSampler(route, step_m)

    # Assert
    assert sampler.last_index == 10
    assert sampler.point(0) == (24.0, 120.0)
    assert sampler.point(sampler.last_index) == (25.0, 120.0)


def test_sampler_handles_step_longer_than_whole_route():
    # Arrange：一步就走完整段，至少也要保留起點與終點
    route = [(24.0, 120.0, ""), (24.001, 120.0, "")]

    # Act
    sampler = RouteSampler(route, 10000.0)

    # Assert
    assert _all_points(sampler) == [(24.0, 120.0), (24.001, 120.0)]


def _step_lengths(points):
    return [haversine(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])]


def test_sampler_keeps_speed_on_segments_shorter_than_one_step():
    """路線點比「每一步該走的距離」還密時，每一步仍要走滿設定的距離。

    舊版逐段切割，一段不到一步也會佔掉一整秒：3 公尺一段、以 11 公尺/秒走，
    實際速度只剩四分之一左右（修過的 bug）。
    """
    # Arrange：每段約 3.3 公尺，共 300 段、約 1 公里
    route = [(24.0 + i * 0.00003, 120.0, "") for i in range(301)]
    step_m = 11.0

    # Act
    sampler = RouteSampler(route, step_m)

    # Assert：每一步都接近 11 公尺，總步數接近「總距離 / 步長」
    steps = _step_lengths(_all_points(sampler))
    assert all(step == pytest.approx(step_m, rel=0.02) for step in steps)
    assert len(steps) == round(route_length(route) / step_m)


def test_sampler_does_not_speed_up_on_a_segment_just_under_two_steps():
    """一段是 1.9 步長時，舊版 int() 捨去成 1 步，那一秒會跑出將近兩倍速。"""
    # Arrange：兩段各約 19 公尺，步長 10 公尺
    route = [(24.0, 120.0, ""), (24.00017, 120.0, ""), (24.00034, 120.0, "")]

    # Act
    sampler = RouteSampler(route, 10.0)

    # Assert
    assert max(_step_lengths(_all_points(sampler))) < 12.0


def test_sampler_samples_on_the_route_across_corners():
    # Arrange：L 形路線，各邊約 111 公尺
    route = [(24.0, 120.0, ""), (24.001, 120.0, ""), (24.001, 120.001, "")]

    # Act
    points = _all_points(RouteSampler(route, 5.0))

    # Assert：每個取樣點都落在兩條邊之一上
    for lat, lon in points:
        on_first_leg = lon == pytest.approx(120.0) and 24.0 <= lat <= 24.001 + 1e-12
        on_second_leg = lat == pytest.approx(24.001) and 120.0 <= lon <= 120.001 + 1e-12
        assert on_first_leg or on_second_leg


def test_sampler_handles_route_with_zero_length():
    # Arrange：所有點重疊，總長為 0
    route = [(24.0, 120.0, ""), (24.0, 120.0, ""), (24.0, 120.0, "")]

    # Act
    sampler = RouteSampler(route, 5.0)

    # Assert
    assert _all_points(sampler) == [(24.0, 120.0), (24.0, 120.0)]
    assert sampler.index_at(0.0) == 0


def test_sampler_distances_are_arc_lengths_along_the_route():
    """distance_at() 是沿原路線的弧長：與步長無關，換速度後才對得回同一個位置。"""
    # Arrange：L 形路線，總長約 222 公尺，步長 10 公尺
    route = [(24.0, 120.0, ""), (24.001, 120.0, ""), (24.001, 120.001, "")]
    sampler = RouteSampler(route, 10.0)

    # Act / Assert
    assert sampler.distance_at(0) == 0.0
    assert sampler.distance_at(sampler.last_index) == pytest.approx(route_length(route))
    assert sampler.distance_at(sampler.last_index + 5) == sampler.distance_at(sampler.last_index)
    assert sampler.distance_at(3) == pytest.approx(3 * sampler.spacing_m)


def test_sampler_index_at_picks_the_nearest_step():
    # Arrange：約 100 公尺，切成 10 步、每步約 10 公尺
    route = [(24.0, 120.0, ""), (24.0009, 120.0, "")]
    sampler = RouteSampler(route, 10.0)
    spacing = sampler.spacing_m

    # Act / Assert
    assert sampler.index_at(-5.0) == 0
    assert sampler.index_at(spacing * 0.9) == 1
    assert sampler.index_at(spacing * 1.4) == 1
    assert sampler.index_at(spacing * 1.6) == 2
    assert sampler.index_at(99999.0) == sampler.last_index


def test_sampler_does_not_expand_the_whole_route_up_front(monkeypatch):
    """10 公里以 0.1 km/h 走會切成約 36 萬步：建立時只能處理原本的路線點，
    不能先把每一步都算出來（在 UI 執行緒上會卡住好一陣子）。"""
    import gps_qt.geo as geo_module

    calls = []
    real_haversine = geo_module.haversine

    def counting_haversine(*args):
        calls.append(1)
        return real_haversine(*args)
    monkeypatch.setattr(geo_module, "haversine", counting_haversine)
    route = [(24.0, 120.0, ""), (24.09, 120.0, "")]  # 約 10 公里

    # Act
    sampler = RouteSampler(route, 0.1 / 3.6)
    middle = sampler.point(sampler.last_index // 2)

    # Assert
    assert sampler.last_index > 300000
    assert len(calls) < 10
    assert middle[0] == pytest.approx(24.045, abs=1e-6)


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


def test_progress_survives_a_speed_change_midway():
    """停止後改速度再開始移動，必須從原地繼續，不能被夾到路線終點。

    進度若記成「第幾個內插點」，加速後內插點變少，中途的索引會超出範圍而被
    夾到最後一點，人就直接瞬移到終點（修過的 bug）。
    """
    route = [(25.0, 121.0, ""), (25.02, 121.0, "")]  # 約 2.2 公里

    slow = RouteSampler(route, 1.4)       # 步行速度，步數很多
    stopped_at = slow.last_index // 2
    travelled = slow.distance_at(stopped_at)

    fast = RouteSampler(route, 16.7)      # 加速到 60 km/h，步數變少
    resumed_at = fast.index_at(travelled)

    assert resumed_at < fast.last_index
    assert fast.distance_at(resumed_at) == pytest.approx(travelled, abs=20.0)
    assert fast.point(resumed_at)[0] == pytest.approx(slow.point(stopped_at)[0], abs=0.0002)


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
