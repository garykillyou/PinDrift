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


def test_insert_after_puts_midpoint_between_neighbors(panel):
    # Act
    panel.insert_adjacent(0, after=True)

    # Assert：插在第 0 與第 1 個點之間，取中點，後面的點往後移
    assert len(panel.route) == 4
    assert panel.route[1][:2] == pytest.approx([24.0005, 120.0])
    assert panel.route[2] == ROUTE[1]


def test_insert_before_puts_midpoint_between_neighbors(panel):
    # Act
    panel.insert_adjacent(2, after=False)

    # Assert
    assert panel.route[2][:2] == pytest.approx([24.0015, 120.0])
    assert panel.route[3] == ROUTE[2]


def test_insert_at_ends_extends_along_the_end_segment(panel):
    # Act
    panel.insert_adjacent(0, after=False)
    panel.insert_adjacent(len(panel.route) - 1, after=True)

    # Assert：沿端點線段方向延伸同樣的長度
    assert panel.route[0][:2] == pytest.approx([23.999, 120.0])
    assert panel.route[-1][:2] == pytest.approx([24.003, 120.0])


def test_insert_is_clamped_to_valid_coordinates(qapp):
    # Arrange
    edge = RoutePanel([[89.9995, 179.9995, ""], [89.9999, 179.9999, ""]])

    # Act
    edge.insert_adjacent(1, after=True)

    # Assert
    assert edge.route[-1][0] <= 90.0 and edge.route[-1][1] <= 180.0


def test_insert_ignored_when_locked_or_row_invalid(panel):
    # Act
    panel.insert_adjacent(9, after=True)
    panel.set_locked(True)
    panel.insert_adjacent(0, after=True)

    # Assert
    assert panel.route == ROUTE
