"""路線幾何計算：純函式，不相依任何 UI 框架。"""

import bisect
import math


LAT_LIMIT = 90.0
LON_LIMIT = 180.0


def is_valid_latitude(value):
    """value（數值）是否落在 ±90 內。NaN 的比較結果恆為假，所以也會被擋掉。"""
    return -LAT_LIMIT <= value <= LAT_LIMIT


def is_valid_longitude(value):
    """value（數值）是否落在 ±180 內。NaN 的比較結果恆為假，所以也會被擋掉。"""
    return -LON_LIMIT <= value <= LON_LIMIT


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


METERS_PER_DEGREE = math.radians(1) * 6371000  # 緯度 1 度約 111194.9 公尺

DEFAULT_EXTEND_DEG = 0.001  # 路線只有一個點、沒有線段可延伸時的偏移量（約 110 公尺）


def adjacent_point(route, row, after):
    """回傳在 route[row] 前面（after=False）或後面（after=True）新增的座標 [lat, lon]。

    兩點之間插入時取中點；插在路線兩端時沿著端點線段的方向延伸同樣的長度，
    路線只有一個點則偏移 DEFAULT_EXTEND_DEG。結果夾在合法經緯度內。
    """
    lat, lon = route[row][0], route[row][1]
    neighbor_row = row + 1 if after else row - 1
    if 0 <= neighbor_row < len(route):
        other = route[neighbor_row]
        return [(lat + other[0]) / 2, (lon + other[1]) / 2]

    # 這一側沒有鄰居：以另一側的鄰居定出方向，往外延伸。
    behind_row = row - 1 if after else row + 1
    if 0 <= behind_row < len(route):
        behind = route[behind_row]
        d_lat, d_lon = lat - behind[0], lon - behind[1]
    else:
        sign = 1 if after else -1
        d_lat, d_lon = sign * DEFAULT_EXTEND_DEG, sign * DEFAULT_EXTEND_DEG
    new_lat = max(-LAT_LIMIT, min(LAT_LIMIT, lat + d_lat))
    new_lon = max(-LON_LIMIT, min(LON_LIMIT, lon + d_lon))
    return [new_lat, new_lon]


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


def simplify_route(route, tolerance_m):
    """抽稀路線表格的列（[lat, lon, note]），回傳新的列，不改動輸入。

    有備註的點一律保留：備註是使用者自己標的（起訖點、KML 匯入的地名），
    就算落在直線上也有意義。做法是在這些點把路線切段，各段分別跑
    douglas_peucker() 再接起來，每段的端點本來就會保留，備註點自然不會被抽掉。
    """
    if tolerance_m <= 0 or len(route) <= 2:
        return [list(row) for row in route]

    last = len(route) - 1
    anchors = [0] + [i for i in range(1, last) if str(route[i][2]).strip()] + [last]
    simplified = [list(route[0])]
    for start, end in zip(anchors, anchors[1:]):
        segment = douglas_peucker(route[start:end + 1], tolerance_m)
        simplified.extend(list(row) for row in segment[1:])
    return simplified


def cumulative_distances(points):
    """回傳與 points 等長的累積距離（公尺），[0] 固定為 0。"""
    if not points:
        return []
    totals = [0.0]
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        totals.append(totals[-1] + haversine(lat1, lon1, lat2, lon2))
    return totals


def route_length(route):
    """路線（[lat, lon, ...] 的列）的總長度（公尺），不到兩點時為 0。"""
    return sum(
        haversine(a[0], a[1], b[0], b[1]) for a, b in zip(route, route[1:])
    )


class RouteSampler:
    """沿整條路線依弧長等距切步，需要哪一步才算出那一步的座標。

    刻意把整條路線當成一條連續的線來切，而不是逐段切（修過的 bug）：逐段切時
    比一步還短的段也會佔掉一整秒（路線點越密越慢），1.9 步長的段又被 int()
    捨去成一步（那一秒快將近一倍），實際速度與設定值、預計時間都對不上。

    步數取「總長 / 步長」四捨五入，再把總長平均分配，每一步的距離都一樣、
    整條路線的誤差不到半步。代價是轉角處會被截掉一點（最多約半步），
    取樣點本身仍一律落在原本的路線上。

    不一次展開成整串內插點（修過的效能問題）：10 公里以 0.1 km/h 走會切成約
    36 萬步，每一圈與每次改速度都在 UI 執行緒上整個重算會卡住畫面。建立時只算
    原本路線點的累積距離，point() 再用二分搜尋找出所在的線段。

    索引 0 是起點、last_index 是終點。distance_at() 回傳的是沿原路線的弧長，
    與步長無關，所以進度可以記成距離，換速度後再用 index_at() 換回新的索引。
    """

    def __init__(self, route, step_m):
        """route：[lat, lon, ...] 的列，至少兩點；step_m：每一步的距離（公尺）。"""
        if len(route) < 2:
            raise ValueError("路線至少要兩個點")
        self._vertices = [(point[0], point[1]) for point in route]
        self._cumulative = cumulative_distances(self._vertices)
        self.total_m = self._cumulative[-1]
        steps = max(1, round(self.total_m / step_m)) if step_m > 0 else 1
        self.last_index = steps
        self.spacing_m = self.total_m / steps

    def distance_at(self, index):
        """第 index 步在路線上的弧長位置（公尺）；超過終點時回傳總長。"""
        if index >= self.last_index:
            return self.total_m
        return max(index, 0) * self.spacing_m

    def index_at(self, distance_m):
        """最接近 distance_m 的步數索引，夾在 0～last_index 之間。"""
        if self.spacing_m <= 0:
            return 0
        index = math.floor(distance_m / self.spacing_m + 0.5)
        return max(0, min(index, self.last_index))

    def point(self, index):
        """第 index 步的座標 (lat, lon)；起點與終點原樣回傳路線的端點。"""
        target = self.distance_at(index)
        if target <= 0:
            return self._vertices[0]
        if target >= self.total_m:
            return self._vertices[-1]
        # 找出 cumulative[seg] < target <= cumulative[seg + 1] 的線段。
        seg = bisect.bisect_left(self._cumulative, target) - 1
        seg_len = self._cumulative[seg + 1] - self._cumulative[seg]
        t = (target - self._cumulative[seg]) / seg_len if seg_len > 0 else 0.0
        (lat1, lon1), (lat2, lon2) = self._vertices[seg], self._vertices[seg + 1]
        return (lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t)
