"""persistence._write_json() 的錯誤處理測試。

寫入失敗要回傳錯誤訊息而不是丟例外——關閉視窗時存檔失敗不該讓關閉流程炸掉。
"""

import json

from gps_qt.persistence import _write_json


def test_write_json_returns_none_on_success(tmp_path):
    # Arrange
    target = tmp_path / "settings.json"

    # Act
    result = _write_json(str(target), {"theme": "dark", "名稱": "台中"})

    # Assert
    assert result is None
    assert json.loads(target.read_text(encoding="utf-8")) == {"theme": "dark", "名稱": "台中"}


def test_write_json_returns_message_when_path_unwritable(tmp_path):
    # Arrange：把檔案放進一個不存在的子目錄，等同於寫不進去的資料夾
    target = tmp_path / "沒有這個資料夾" / "settings.json"

    # Act
    result = _write_json(str(target), {"theme": "dark"})

    # Assert
    assert isinstance(result, str)
    assert str(target) in result


def test_write_json_propagates_serialization_bug(tmp_path):
    # Arrange：不可序列化的值是程式的 bug，不該被當成「寫入失敗」吞掉
    target = tmp_path / "settings.json"

    # Act / Assert
    try:
        _write_json(str(target), {"bad": object()})
    except TypeError:
        pass
    else:
        raise AssertionError("序列化錯誤應該照常拋出 TypeError")


def test_write_json_leaves_original_intact_on_serialization_bug(tmp_path):
    # Arrange：序列化失敗發生在碰到磁碟之前，原檔不能被清空，也不能留下暫存檔
    target = tmp_path / "settings.json"
    target.write_text('{"theme": "dark"}', encoding="utf-8")

    # Act
    try:
        _write_json(str(target), {"bad": object()})
    except TypeError:
        pass

    # Assert
    assert json.loads(target.read_text(encoding="utf-8")) == {"theme": "dark"}
    assert list(tmp_path.iterdir()) == [target]


def test_write_json_replaces_existing_file_without_leaving_temp_files(tmp_path):
    # Arrange
    target = tmp_path / "settings.json"
    target.write_text('{"theme": "dark"}', encoding="utf-8")

    # Act
    result = _write_json(str(target), {"theme": "light"})

    # Assert
    assert result is None
    assert json.loads(target.read_text(encoding="utf-8")) == {"theme": "light"}
    assert list(tmp_path.iterdir()) == [target]
