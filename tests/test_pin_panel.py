"""PinPanel 的「座標確定」通知：快速選擇、貼上與打完字都要通知，保持中才能立刻重新注入。"""

import pytest

from gps_qt.widgets.pin_panel import PIN_PRESETS, PinPanel


@pytest.fixture
def panel(qapp):
    panel = PinPanel()
    panel.committed = []
    panel.coordinates_committed.connect(lambda lat, lon: panel.committed.append((lat, lon)))
    return panel


def test_preset_commits_its_coordinates(panel):
    # Act：按下第二個快速選擇（台北101）
    name, lat, lon = PIN_PRESETS[1]
    panel._apply_preset(lat, lon)

    # Assert
    assert panel.committed == [(lat, lon)]


def test_pasted_coordinates_are_committed(panel):
    # Act
    applied = panel._try_apply_pasted_coordinates("25.0338, 121.5645")

    # Assert
    assert applied is True
    assert panel.committed == [(25.0338, 121.5645)]


def test_invalid_paste_does_not_commit(panel):
    # Act / Assert
    assert panel._try_apply_pasted_coordinates("不是座標") is False
    assert panel.committed == []


def test_finishing_editing_commits_the_typed_value(panel):
    # Arrange：手動打字時每按一鍵都會 valueChanged，不能每一鍵都注入
    panel.lat_spin.setValue(23.5)
    assert panel.committed == []

    # Act：打完字（Enter 或離開欄位）
    panel.lat_spin.editingFinished.emit()

    # Assert
    assert panel.committed == [(23.5, panel.lon_spin.value())]
