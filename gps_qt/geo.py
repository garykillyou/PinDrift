"""路線幾何計算：純函式，不相依任何 UI 框架。"""

import bisect
import math


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


METERS_PER_DEGREE = math.radians(1) * 6371000  # 緯度 1 度約 111194.9 公尺


def _perpendicular_distance_m(point, start, end):
    """point 到 start-end 線段的垂直距離（公尺）。

    用等距長方投影把經緯度換成平面座標再算：路徑規劃回傳的相鄰點間距通常只有
    幾十公尺，在這個尺度下投影誤差遠小於簡化容差本身，不值得為此做球面幾何。
    """
    scale_x = math.cos(math.radians(start[0])) * METERS_PER_DEGREE
    px = (point[1] - start[1]) * scale_x
    py = (point[0] - start[0]) * METERS_PER_DEGREE
    ex = (end[1] - start[1]) * scale_x
    ey = (end[0] - start[0]) * METERS_PER_DEGREE
    segment_len_sq = ex * ex + ey * ey
    if segment_len_sq == 0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * ex + py * ey) / segment_len_sq))
    return math.hypot(px - t * ex, py - t * ey)


def douglas_peucker(points, tolerance_m):
    """用 Douglas-Peucker 演算法抽稀座標點，保留路形。

    路徑規劃服務回傳的轉彎點動輒上千個，直接塞進座標表格會難以手動微調；
    容差 5 公尺左右就能把點數降到幾十個，而路形肉眼幾乎看不出差別。
    tolerance_m <= 0 代表不簡化，原樣回傳。

    刻意用顯式堆疊而非遞迴：點數可能上千，遞迴版的深度最壞會等於點數，
    會撞到 Python 預設的遞迴上限。
    """
    if tolerance_m <= 0 or len(points) <= 2:
        return list(points)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        max_dist, farthest = 0.0, first
        for i in range(first + 1, last):
            dist = _perpendicular_distance_m(points[i], points[first], points[last])
            if dist > max_dist:
                max_dist, farthest = dist, i
        if max_dist > tolerance_m:
            keep[farthest] = True
            stack.append((first, farthest))
            stack.append((farthest, last))
    return [point for point, kept in zip(points, keep) if kept]


def cumulative_distances(points):
    """回傳與 points 等長的累積距離（公尺），[0] 固定為 0。

    內插點的「第幾個」會隨速度改變（速度越快點越少），但「走到路線的第幾公尺」
    不會，所以進度一律用距離記錄，再由 index_at_distance() 換回目前這份內插
    結果的索引。
    """
    totals = [0.0]
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        totals.append(totals[-1] + haversine(lat1, lon1, lat2, lon2))
    return totals


def index_at_distance(cumulative, distance_m):
    """在 cumulative（遞增的累積距離）裡找出最接近 distance_m 的索引。"""
    if not cumulative:
        return 0
    pos = bisect.bisect_left(cumulative, distance_m)
    if pos <= 0:
        return 0
    if pos >= len(cumulative):
        return len(cumulative) - 1
    before, after = cumulative[pos - 1], cumulative[pos]
    return pos if (after - distance_m) < (distance_m - before) else pos - 1


def interpolate_points(route, speed_ms, interval_sec):
    points = []
    for i in range(len(route) - 1):
        lat1, lon1 = route[i][0], route[i][1]
        lat2, lon2 = route[i + 1][0], route[i + 1][1]
        dist = haversine(lat1, lon1, lat2, lon2)
        steps = max(1, int(dist / (speed_ms * interval_sec)))
        for s in range(steps):
            t = s / steps
            points.append((lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t))
    points.append((route[-1][0], route[-1][1]))
    return points
