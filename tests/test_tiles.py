"""tiles.py 的測試：目前該用哪組圖磚，以及自訂版權標示的 escape。"""

from gps_qt.tiles import AUTO_TILE, CUSTOM_TILE, TILE_BY_KEY, resolve_tile

CUSTOM_URL = "https://tiles.example.com/{z}/{x}/{y}.png"


def test_custom_attribution_is_escaped_before_reaching_leaflet():
    """Leaflet 會把 attribution 當 HTML 插進頁面，而這個頁面能呼叫 QWebChannel bridge。"""
    # Arrange
    settings = {
        "tile_source": CUSTOM_TILE,
        "custom_tile_url": CUSTOM_URL,
        "custom_attribution": '<img src=x onerror="bridge.on_js_error(1)"> & Co',
    }

    # Act
    url, attribution = resolve_tile(settings, "dark")

    # Assert
    assert url == CUSTOM_URL
    assert "<" not in attribution and ">" not in attribution and '"' not in attribution
    assert attribution == (
        "&lt;img src=x onerror=&quot;bridge.on_js_error(1)&quot;&gt; &amp; Co"
    )


def test_custom_attribution_keeps_plain_text_unchanged():
    # Arrange
    settings = {
        "tile_source": CUSTOM_TILE,
        "custom_tile_url": CUSTOM_URL,
        "custom_attribution": "© 我的圖磚",
    }

    # Act / Assert
    assert resolve_tile(settings, "dark") == (CUSTOM_URL, "© 我的圖磚")


def test_builtin_attribution_keeps_its_html_entities():
    # Arrange
    settings = {"tile_source": "osm", "custom_attribution": "<b>不該被用到</b>"}

    # Act
    url, attribution = resolve_tile(settings, "light")

    # Assert：內建的 &copy; 是刻意寫的 HTML 實體，不能被 escape 成 &amp;copy;
    assert (url, attribution) == (TILE_BY_KEY["osm"][2], TILE_BY_KEY["osm"][3])
    assert attribution.startswith("&copy;")


def test_auto_tile_follows_the_theme():
    # Arrange
    settings = {"tile_source": AUTO_TILE}

    # Act / Assert
    assert resolve_tile(settings, "dark")[0] == TILE_BY_KEY["dark"][2]
    assert resolve_tile(settings, "light")[0] == TILE_BY_KEY["positron"][2]


def test_custom_tile_without_url_falls_back_to_osm():
    # Arrange
    settings = {"tile_source": CUSTOM_TILE, "custom_tile_url": "", "custom_attribution": "x"}

    # Act / Assert
    assert resolve_tile(settings, "dark") == (TILE_BY_KEY["osm"][2], TILE_BY_KEY["osm"][3])
