"""window_geometry.normalize_window() 的測試：手改壞的視窗設定不能讓程式開不起來。"""

import pytest

from gps_qt.window_geometry import DEFAULT_WINDOW_H, DEFAULT_WINDOW_W, normalize_window


def test_normalize_window_keeps_valid_values():
    # Arrange
    raw = {"width": 1200, "height": 700, "x": -1900, "y": 40, "maximized": False}

    # Act / Assert：多螢幕時 x 可以是負數
    assert normalize_window(raw) == raw


@pytest.mark.parametrize("raw", [None, "壞掉的值", [1, 2], {}])
def test_normalize_window_falls_back_when_block_is_missing_or_not_a_dict(raw):
    # Act
    result = normalize_window(raw)

    # Assert：位置交給作業系統決定，第一次啟動的行為（最大化）
    assert result == {
        "width": DEFAULT_WINDOW_W, "height": DEFAULT_WINDOW_H,
        "x": None, "y": None, "maximized": True,
    }


def test_normalize_window_replaces_fields_with_wrong_types():
    # Arrange
    raw = {"width": "1200", "height": float("nan"), "x": True, "y": "40", "maximized": "false"}

    # Act
    result = normalize_window(raw)

    # Assert
    assert result["width"] == DEFAULT_WINDOW_W
    assert result["height"] == DEFAULT_WINDOW_H
    assert result["x"] is None and result["y"] is None
    # "false" 這個字串用 bool() 轉會變成 True，只接受真正的布林值
    assert result["maximized"] is True


def test_normalize_window_accepts_integral_floats():
    # Act / Assert：手改成 1200.0 也能用，但回傳的一定是 int（QWidget.resize() 不收 float）
    result = normalize_window({"width": 1200.0, "height": 700.4})
    assert result["width"] == 1200 and isinstance(result["width"], int)
    assert result["height"] == 700 and isinstance(result["height"], int)
