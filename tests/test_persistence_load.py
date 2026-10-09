"""persistence 讀檔的防呆測試：壞掉的檔案不能讓程式當掉，也不能在下次存檔時被默默蓋掉。"""

import json

import pytest

from gps_qt import persistence


@pytest.fixture
def favorites_file(tmp_path, monkeypatch):
    path = tmp_path / "pindrift_favorites.json"
    monkeypatch.setattr(persistence, "FAVORITES_FILE", str(path))
    return path


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "pindrift_settings.json"
    monkeypatch.setattr(persistence, "SETTINGS_FILE", str(path))
    return path


def _backups(path):
    return sorted(path.parent.glob(path.stem + ".corrupt-*" + path.suffix))


def test_load_favorites_returns_empty_without_message_when_file_missing(favorites_file):
    # Act
    favorites, message = persistence.load_favorites()

    # Assert
    assert favorites == []
    assert message is None


def test_load_favorites_backs_up_unparsable_file(favorites_file):
    # Arrange：寫到一半當掉的檔案
    favorites_file.write_text('[{"type": "pin", "name": "家', encoding="utf-8")

    # Act
    favorites, message = persistence.load_favorites()

    # Assert：回傳空清單，但原內容留在備份檔裡，訊息要講出備份位置
    assert favorites == []
    backups = _backups(favorites_file)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '[{"type": "pin", "name": "家'
    assert str(backups[0]) in message


def test_load_favorites_backs_up_file_with_wrong_top_level_type(favorites_file):
    # Arrange：最外層應該是陣列
    favorites_file.write_text('{"type": "pin"}', encoding="utf-8")

    # Act
    favorites, message = persistence.load_favorites()

    # Assert
    assert favorites == []
    assert len(_backups(favorites_file)) == 1
    assert message


def test_load_favorites_skips_invalid_entries_and_keeps_a_backup(favorites_file):
    # Arrange
    entries = [
        {"type": "pin", "name": "家", "lat": 24.1, "lon": 120.6},
        {"type": "pin", "name": "缺座標"},
        {"type": "pin", "name": "超出範圍", "lat": 999, "lon": 120.6},
        {"type": "route", "name": "只有一點", "route": [[24.0, 120.0, ""]]},
        {"type": "route", "name": "上學", "route": [[24.0, 120.0], [24.1, 120.1, "學校"]]},
        {"type": "unknown", "name": "未知類型"},
        "不是物件",
    ]
    favorites_file.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    # Act
    favorites, message = persistence.load_favorites()

    # Assert：只留下合法的兩筆，路線點補齊備註欄
    assert [fav["name"] for fav in favorites] == ["家", "上學"]
    assert favorites[1]["route"] == [[24.0, 120.0, ""], [24.1, 120.1, "學校"]]
    assert "5" in message
    assert len(_backups(favorites_file)) == 1


def test_load_favorites_keeps_valid_file_untouched(favorites_file):
    # Arrange
    entries = [{"type": "pin", "name": "家", "lat": 24.1, "lon": 120.6, "extra": 1}]
    favorites_file.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    # Act
    favorites, message = persistence.load_favorites()

    # Assert：沒有訊息、沒有備份，未知欄位原樣保留（相容日後新增的欄位）
    assert favorites == entries
    assert message is None
    assert _backups(favorites_file) == []


def test_load_favorites_accepts_utf8_bom(favorites_file):
    # Arrange：記事本另存 UTF-8 時會加 BOM
    entries = [{"type": "pin", "name": "家", "lat": 24.1, "lon": 120.6}]
    favorites_file.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8-sig")

    # Act
    favorites, message = persistence.load_favorites()

    # Assert
    assert favorites == entries
    assert message is None


def test_load_settings_backs_up_unparsable_file(settings_file):
    # Arrange
    settings_file.write_text("{壞掉", encoding="utf-8")

    # Act
    settings, message = persistence.load_settings()

    # Assert
    assert settings == {}
    assert len(_backups(settings_file)) == 1
    assert message


def test_load_settings_backs_up_non_dict_file(settings_file):
    # Arrange
    settings_file.write_text("[1, 2]", encoding="utf-8")

    # Act
    settings, message = persistence.load_settings()

    # Assert
    assert settings == {}
    assert message


def test_load_saved_route_rejects_out_of_range_points():
    # Arrange
    settings = {"last_route": [[24.0, 120.0, "起點"], [95.0, 120.0, "終點"]]}

    # Act / Assert
    assert persistence.load_saved_route(settings) is None


@pytest.mark.parametrize("value", ["33", None, float("nan"), float("inf"), 0, -5, True, [33]])
def test_load_speed_kmh_falls_back_on_invalid_values(value):
    # Act / Assert
    assert persistence.load_speed_kmh({"speed_kmh": value}, 20.0) == 20.0


def test_load_speed_kmh_keeps_valid_value():
    assert persistence.load_speed_kmh({"speed_kmh": 33}, 20.0) == 33.0
    assert persistence.load_speed_kmh({}, 20.0) == 20.0


ROUTE = [[24.0, 120.0, ""], [24.1, 120.1, ""]]


def test_normalize_favorite_keeps_valid_route_speed():
    fav = persistence.normalize_favorite({"type": "route", "name": "a", "route": ROUTE, "speed_kmh": 12})

    assert fav["speed_kmh"] == 12.0


@pytest.mark.parametrize("bad", ["fast", True, 0, -5, float("nan"), float("inf"), None])
def test_normalize_favorite_drops_invalid_speed_but_keeps_favorite(bad):
    fav = persistence.normalize_favorite({"type": "route", "name": "a", "route": ROUTE, "speed_kmh": bad})

    assert fav is not None
    assert "speed_kmh" not in fav


def test_normalize_favorite_route_without_speed_stays_without_speed():
    fav = persistence.normalize_favorite({"type": "route", "name": "a", "route": ROUTE})

    assert "speed_kmh" not in fav


@pytest.mark.parametrize("value,expected", [
    ("https://discord.com/api/webhooks/1/token", "https://discord.com/api/webhooks/1/token"),
    ("https://evil.com/api/webhooks/1/token", ""),
    (123, ""),
    (None, ""),
])
def test_load_discord_webhook_only_accepts_discord_urls(value, expected):
    assert persistence.load_discord_webhook({"discord_webhook": value}) == expected


def test_load_discord_webhook_defaults_to_empty_when_missing():
    assert persistence.load_discord_webhook({}) == ""
