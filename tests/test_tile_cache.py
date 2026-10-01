"""tile_cache.py 的測試：URL 改寫、上游網址驗證、快取路徑、新鮮度與容量上限。"""

import os

from gps_qt import tile_cache

OSM_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def test_http_template_is_routed_through_cache_scheme():
    # Act
    template = tile_cache.cached_url_template(OSM_TEMPLATE)

    # Assert
    assert template == "pdtile:" + OSM_TEMPLATE
    assert tile_cache.upstream_url(template) == OSM_TEMPLATE


def test_non_http_template_is_left_unchanged():
    """自訂的 file:// 圖磚本來就在本機，不需要（也不能）走快取。"""
    template = "file:///C:/tiles/{z}/{x}/{y}.png"

    assert tile_cache.cached_url_template(template) == template


def test_upstream_rejects_non_http_targets():
    """scheme 後面那段是頁面給的字串，不能讓它借道讀取本機檔案。"""
    assert tile_cache.upstream_url("pdtile:file:///C:/Windows/win.ini") is None
    assert tile_cache.upstream_url("https://tile.openstreetmap.org/1/2/3.png") is None
    assert tile_cache.upstream_url("pdtile:") is None


def test_cache_path_stays_inside_root_even_for_traversal_urls(tmp_path):
    # Arrange
    root = str(tmp_path)

    # Act
    path = tile_cache.cache_file_path(root, "https://example.com/../../../evil.png")

    # Assert
    assert os.path.dirname(os.path.dirname(path)) == root
    assert ".." not in os.path.relpath(path, root)


def test_same_url_maps_to_same_path_and_different_urls_differ(tmp_path):
    root = str(tmp_path)
    first = tile_cache.cache_file_path(root, "https://a/1/2/3.png")

    assert first == tile_cache.cache_file_path(root, "https://a/1/2/3.png")
    assert first != tile_cache.cache_file_path(root, "https://a/1/2/4.png")


def test_content_type_is_sniffed_from_magic_bytes():
    assert tile_cache.content_type_of(PNG_HEADER) == "image/png"
    assert tile_cache.content_type_of(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert tile_cache.content_type_of(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert tile_cache.content_type_of(b"unknown") == tile_cache.FALLBACK_CONTENT_TYPE


def test_freshness_boundary():
    now = 1_000_000_000

    assert tile_cache.is_fresh(now - tile_cache.TILE_FRESH_SECONDS + 1, now)
    assert not tile_cache.is_fresh(now - tile_cache.TILE_FRESH_SECONDS, now)


def test_write_then_read_round_trip_leaves_no_tmp_file(tmp_path):
    # Arrange
    path = tile_cache.cache_file_path(str(tmp_path), "https://a/1/2/3.png")

    # Act
    error = tile_cache.write_cached(path, PNG_HEADER)
    cached = tile_cache.read_cached(path)

    # Assert
    assert error is None
    assert cached[0] == PNG_HEADER
    assert not os.path.exists(path + ".tmp")


def test_missing_or_empty_cache_reads_as_miss(tmp_path):
    empty = tmp_path / "empty"
    empty.write_bytes(b"")

    assert tile_cache.read_cached(str(tmp_path / "missing")) is None
    assert tile_cache.read_cached(str(empty)) is None


def test_write_failure_returns_message_instead_of_raising(tmp_path):
    """放在唯讀位置時寫不進快取，地圖仍要照常從網路顯示。"""
    # Arrange：拿一個檔案當成資料夾，makedirs 必定失敗
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"x")

    # Act
    error = tile_cache.write_cached(str(blocker / "ab" / "abcdef"), PNG_HEADER)

    # Assert
    assert error is not None and "圖磚快取寫入失敗" in error


def _make_tile(root, name, size, mtime):
    path = root / name
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_prune_does_nothing_under_limit(tmp_path):
    _make_tile(tmp_path, "a", 100, 1)

    assert tile_cache.prune_cache(str(tmp_path), max_bytes=1000) == (0, 0)


def test_prune_removes_oldest_first_down_to_ratio(tmp_path):
    # Arrange：共 400 bytes，上限 300、目標 300 * 0.5 = 150
    oldest = _make_tile(tmp_path, "oldest", 100, 1)
    older = _make_tile(tmp_path, "older", 100, 2)
    newer = _make_tile(tmp_path, "newer", 100, 3)
    newest = _make_tile(tmp_path, "newest", 100, 4)

    # Act
    removed, freed = tile_cache.prune_cache(str(tmp_path), max_bytes=300, ratio=0.5)

    # Assert
    assert (removed, freed) == (3, 300)
    assert not oldest.exists() and not older.exists() and not newer.exists()
    assert newest.exists()


def test_prune_skips_files_being_written(tmp_path):
    """.tmp 是寫到一半的檔案，刪掉的話那次寫入的 os.replace() 會失敗。"""
    writing = _make_tile(tmp_path, "tile.tmp", 1000, 1)

    assert tile_cache.prune_cache(str(tmp_path), max_bytes=10) == (0, 0)
    assert writing.exists()


def test_is_image_rejects_html_error_pages():
    """captive portal／限流頁常是 HTTP 200，不能被當成圖磚存進快取。"""
    assert tile_cache.is_image(PNG_HEADER)
    assert tile_cache.is_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    assert not tile_cache.is_image(b"<!DOCTYPE html><html>login</html>")
    assert not tile_cache.is_image(b"")


def test_subdomain_variants_share_one_cache_file(tmp_path):
    """Leaflet 把 {s} 隨機展開成 a／b／c，同一張圖磚不該存三份。"""
    root = str(tmp_path)
    paths = {
        tile_cache.cache_file_path(root, f"https://{s}.basemaps.cartocdn.com/dark_all/1/2/3.png")
        for s in "abcd"
    }

    assert len(paths) == 1


def test_non_subdomain_hosts_are_not_merged(tmp_path):
    root = str(tmp_path)

    assert (
        tile_cache.cache_file_path(root, "https://ab.example.com/1.png")
        != tile_cache.cache_file_path(root, "https://sb.example.com/1.png")
    )
