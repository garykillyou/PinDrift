"""models.RouteTableModel 的輸入驗證測試（只用到 QtCore，不需要事件迴圈）。"""

import pytest

from gps_qt.models import COL_LAT, COL_LON, COL_NOTE, RouteTableModel


@pytest.fixture
def model():
    return RouteTableModel([[24.0, 120.0, "起點"], [24.1, 120.1, "終點"]])


@pytest.mark.parametrize("value", [90.5, -91, "999", "nan", "inf", "abc"])
def test_set_data_rejects_invalid_latitude(model, value):
    # Act
    accepted = model.setData(model.index(0, COL_LAT), value)

    # Assert：拒絕寫入，原值不變
    assert accepted is False
    assert model.route[0][0] == 24.0


@pytest.mark.parametrize("value", [180.5, -181, "360"])
def test_set_data_rejects_invalid_longitude(model, value):
    # Act
    accepted = model.setData(model.index(0, COL_LON), value)

    # Assert
    assert accepted is False
    assert model.route[0][1] == 120.0


def test_set_data_accepts_boundary_coordinates(model):
    # Act / Assert
    assert model.setData(model.index(0, COL_LAT), -90.0) is True
    assert model.setData(model.index(0, COL_LON), "180") is True
    assert model.route[0][:2] == [-90.0, 180.0]


def test_set_data_still_accepts_any_note(model):
    # Act / Assert
    assert model.setData(model.index(1, COL_NOTE), "便利商店") is True
    assert model.route[1][2] == "便利商店"


def test_set_route_notifies_on_changed_like_other_edits():
    # Arrange：整條替換也要通知，路線資訊（總距離、預計時間）才會跟著更新
    calls = []
    model = RouteTableModel([[24.0, 120.0, ""], [24.1, 120.1, ""]], on_changed=lambda: calls.append(1))

    # Act
    model.set_route([[25.0, 121.0, ""], [25.1, 121.1, ""], [25.2, 121.2, ""]])

    # Assert
    assert calls == [1]
    assert model.rowCount() == 3
