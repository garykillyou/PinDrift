"""persistence.load_map_settings() 的正規化測試。"""

from gps_qt.persistence import DEFAULT_MAP_SETTINGS, load_map_settings


def test_load_map_settings_fills_defaults_when_absent():
    # Arrange
    settings = {}

    # Act
    result = load_map_settings(settings)

    # Assert
    assert result == DEFAULT_MAP_SETTINGS
    # 回傳的必須就是 settings["map"] 本身，MapPanel 才能就地更新後隨設定一起存檔
    assert settings["map"] is result


def test_load_map_settings_keeps_valid_values():
    # Arrange
    settings = {"map": {"tile_source": "dark", "center": [25.0, 121.5],
                        "zoom": 12, "follow": False}}

    # Act
    result = load_map_settings(settings)

    # Assert
    assert result["tile_source"] == "dark"
    assert result["center"] == [25.0, 121.5]
    assert result["zoom"] == 12
    assert result["follow"] is False


def test_load_map_settings_falls_back_on_bad_types():
    # Arrange：手改壞的設定檔不該讓程式開不起來
    settings = {"map": {"center": "不是座標", "zoom": "abc"}}

    # Act
    result = load_map_settings(settings)

    # Assert
    assert result["center"] == DEFAULT_MAP_SETTINGS["center"]
    assert result["zoom"] == DEFAULT_MAP_SETTINGS["zoom"]


def test_load_map_settings_ignores_non_dict_block():
    # Arrange
    settings = {"map": "壞掉的值"}

    # Act / Assert
    assert load_map_settings(settings) == DEFAULT_MAP_SETTINGS


def test_load_map_settings_rejects_out_of_range_or_nan_center():
    # Arrange：NaN 或超出範圍的中心點會讓 Leaflet 的 setView() 整張地圖壞掉
    for center in ([float("nan"), 121.0], [999.0, 121.0], [25.0, 200.0], [True, 121.0]):
        settings = {"map": {"center": center}}

        # Act
        result = load_map_settings(settings)

        # Assert
        assert result["center"] == DEFAULT_MAP_SETTINGS["center"], center


def test_load_map_settings_rejects_zoom_outside_tile_range():
    for zoom in (-3, 42, float("nan"), True):
        assert load_map_settings({"map": {"zoom": zoom}})["zoom"] == DEFAULT_MAP_SETTINGS["zoom"], zoom


def test_load_map_settings_only_accepts_real_booleans_for_follow():
    # Arrange："false" 這個字串用 bool() 轉會變成 True
    settings = {"map": {"follow": "false"}}

    # Act / Assert
    assert load_map_settings(settings)["follow"] is DEFAULT_MAP_SETTINGS["follow"]
    assert load_map_settings({"map": {"follow": 0}})["follow"] is DEFAULT_MAP_SETTINGS["follow"]
    assert load_map_settings({"map": {"follow": False}})["follow"] is False


def test_load_map_settings_rejects_nan_simplify_tolerance():
    assert load_map_settings({"map": {"simplify_m": float("nan")}})["simplify_m"] == DEFAULT_MAP_SETTINGS["simplify_m"]
