"""RoutePanel 的移動中鎖定與「清空座標點」確認（offscreen widget 測試）。"""

import pytest
from PySide6.QtWidgets import QMessageBox

from gps_qt.widgets.route_panel import RoutePanel

ROUTE = [[24.0, 120.0, "起點"], [24.001, 120.0, ""], [24.002, 120.0, "終點"]]


@pytest.fixture
def panel(qapp):
    return RoutePanel([list(row) for row in ROUTE])


def _answer(monkeypatch, button):
    asked = []

    def fake_question(*args, **kwargs):
        asked.append(args)
        return button
    monkeypatch.setattr(QMessageBox, "question", fake_question)
    return asked


def test_clear_asks_first_and_keeps_route_when_declined(panel, monkeypatch):
    # Arrange
    asked = _answer(monkeypatch, QMessageBox.No)

    # Act
    panel._clear_points()

    # Assert：自動存檔會在兩秒內寫進設定，誤按就救不回來，所以一定要先問
    assert len(asked) == 1
    assert "3" in asked[0][2]
    assert len(panel.route) == 3


def test_clear_empties_route_when_confirmed(panel, monkeypatch):
    # Arrange
    _answer(monkeypatch, QMessageBox.Yes)

    # Act
    panel._clear_points()

    # Assert
    assert panel.route == []


def test_clear_does_not_ask_when_route_is_already_empty(qapp, monkeypatch):
    # Arrange
    empty = RoutePanel([])
    asked = _answer(monkeypatch, QMessageBox.Yes)

    # Act
    empty._clear_points()

    # Assert
    assert asked == []


def test_locked_panel_ignores_every_edit_entry(panel, monkeypatch):
    # Arrange：移動中鎖定
    _answer(monkeypatch, QMessageBox.Yes)
    panel.set_locked(True)

    # Act
    panel._add_point()
    panel.add_point_at(24.5, 120.5)
    panel.delete_point(1)
    panel.move_point(0, 24.9, 120.9)
    panel._clear_points()

    # Assert：路線完全沒變，按鈕也停用
    assert panel.route == ROUTE
    assert not panel.add_btn.isEnabled()
    assert not panel.clear_btn.isEnabled()


def test_unlocking_restores_editing(panel):
    # Arrange
    panel.set_locked(True)

    # Act
    panel.set_locked(False)
    panel.delete_point(1)

    # Assert
    assert len(panel.route) == 2
    assert panel.add_btn.isEnabled()
