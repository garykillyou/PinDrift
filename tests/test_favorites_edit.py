"""路線最愛編輯對話框：名稱與速度的修改結果。"""

from gps_qt.widgets.favorites_panel import _RouteEditDialog

ROUTE = [[24.0, 121.0, "起"], [24.1, 121.1, "終"]]


def test_edit_updates_name_and_speed(qapp):
    fav = {"type": "route", "name": "舊名", "route": ROUTE, "speed_kmh": 5.0}
    dialog = _RouteEditDialog(fav, default_speed=20.0)
    dialog.name_edit.setText("  新名  ")
    dialog.speed_spin.setValue(12.5)

    result = dialog.edited(fav)

    assert result == {"type": "route", "name": "新名", "route": ROUTE, "speed_kmh": 12.5}
    assert fav["name"] == "舊名" and fav["speed_kmh"] == 5.0  # 不改動原本的 dict


def test_unchecking_speed_removes_field(qapp):
    fav = {"type": "route", "name": "路線", "route": ROUTE, "speed_kmh": 5.0}
    dialog = _RouteEditDialog(fav, default_speed=20.0)
    dialog.speed_check.setChecked(False)

    assert "speed_kmh" not in dialog.edited(fav)


def test_route_without_speed_defaults_to_current_speed(qapp):
    fav = {"type": "route", "name": "KML 路線", "route": ROUTE}
    dialog = _RouteEditDialog(fav, default_speed=20.0)

    assert not dialog.speed_check.isChecked()
    assert not dialog.speed_spin.isEnabled()
    assert dialog.speed_spin.value() == 20.0
    assert "speed_kmh" not in dialog.edited(fav)

    dialog.speed_check.setChecked(True)
    assert dialog.edited(fav)["speed_kmh"] == 20.0


def test_ok_disabled_when_name_blank(qapp):
    fav = {"type": "route", "name": "路線", "route": ROUTE}
    dialog = _RouteEditDialog(fav, default_speed=20.0)
    dialog.name_edit.setText("   ")

    assert not dialog._ok_btn.isEnabled()
