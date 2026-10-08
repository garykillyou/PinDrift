"""upsert_favorite()：同類型同名的最愛覆蓋，否則加在最後。"""

from gps_qt.persistence import upsert_favorite

ROUTE_A = [[24.0, 121.0, ""], [24.1, 121.1, ""]]
ROUTE_B = [[25.0, 121.5, ""], [25.1, 121.6, ""]]


def test_appends_when_name_is_new():
    favs = [{"type": "route", "name": "上班", "route": ROUTE_A}]
    new = {"type": "route", "name": "下班", "route": ROUTE_B}

    assert upsert_favorite(favs, new) == [*favs, new]


def test_overwrites_same_name_route_in_place():
    first = {"type": "pin", "name": "家", "lat": 24.0, "lon": 121.0}
    old = {"type": "route", "name": "上班", "route": ROUTE_A, "speed_kmh": 5.0}
    last = {"type": "route", "name": "下班", "route": ROUTE_A}
    new = {"type": "route", "name": "上班", "route": ROUTE_B, "speed_kmh": 20.0}

    result = upsert_favorite([first, old, last], new)

    assert result == [first, new, last]


def test_does_not_overwrite_pin_with_same_name():
    pin = {"type": "pin", "name": "公園", "lat": 24.0, "lon": 121.0}
    route = {"type": "route", "name": "公園", "route": ROUTE_A}

    assert upsert_favorite([pin], route) == [pin, route]


def test_does_not_mutate_input():
    favs = [{"type": "route", "name": "上班", "route": ROUTE_A}]
    snapshot = list(favs)

    upsert_favorite(favs, {"type": "route", "name": "上班", "route": ROUTE_B})

    assert favs == snapshot
