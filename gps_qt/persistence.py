"""JSON 存讀與 KML 解析：最愛地點／路線與本機設定的檔案格式。"""

import json
import os
import shutil
import time
import xml.etree.ElementTree as ET

from . import paths
from .geo import haversine, is_valid_latitude, is_valid_longitude

# 存放位置由 paths.data_file() 決定：一律放在執行檔（未凍結時是專案根目錄）
# 所在的資料夾，整包搬走設定就跟著走。
FAVORITES_FILE = paths.data_file("pindrift_favorites.json")
SETTINGS_FILE = paths.data_file("pindrift_settings.json")

# KML 匯入時，起訖點附近多少公尺內的地標名稱會被拿來當備註。
KML_MARKER_MATCH_M = 50.0


def load_favorites():
    """讀取最愛，回傳 (favorites, message)；message 為 None 代表一切正常。

    格式不對的項目直接略過（不讓一筆壞資料把整個清單或啟動流程弄掛），但只要
    有略過任何東西，就先把原檔備份起來——否則使用者下一次存最愛時，被略過的
    那些資料就會隨著覆寫永遠消失。
    """
    raw, message = _read_json(FAVORITES_FILE, list, "陣列")
    if raw is None:
        return [], message
    favorites = [fav for fav in (normalize_favorite(item) for item in raw) if fav is not None]
    dropped = len(raw) - len(favorites)
    if dropped:
        message = _backup_corrupt(FAVORITES_FILE, f"有 {dropped} 筆最愛格式不正確，已略過")
    return favorites, message


def save_favorites(favs):
    """寫入最愛；成功回傳 None，失敗回傳錯誤訊息（見 _write_json）。"""
    return _write_json(FAVORITES_FILE, favs)


def load_settings():
    """讀取設定，回傳 (settings, message)；壞掉的檔案會先備份再改用空設定。"""
    raw, message = _read_json(SETTINGS_FILE, dict, "物件")
    return (raw if raw is not None else {}), message


def save_settings(settings):
    """寫入設定；成功回傳 None，失敗回傳錯誤訊息（見 _write_json）。"""
    return _write_json(SETTINGS_FILE, settings)


def _read_json(path, expected_type, type_label):
    """讀取 JSON，回傳 (data, message)。

    - 檔案不存在：(None, None)，第一次啟動的正常情況。
    - 讀不到（權限不足等）：(None, 訊息)。檔案本身沒壞，不需要備份。
    - 內容無法解析，或最外層不是 expected_type：先備份原檔再回傳 (None, 訊息)。
      舊版在這裡默默吞掉例外並回傳預設值，下一次存檔就把壞檔（連同裡面還救得
      回來的資料）整個蓋掉，使用者連發生過什麼事都不知道（修過的 bug）。

    用 utf-8-sig 解碼：記事本另存 UTF-8 時會在開頭加 BOM，json 不接受 BOM。
    """
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            raw_bytes = f.read()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"無法讀取 {path}：{exc}，已改用預設值"
    try:
        data = json.loads(raw_bytes.decode("utf-8-sig"))
    except ValueError as exc:  # JSONDecodeError 與 UnicodeDecodeError 都是 ValueError
        return None, _backup_corrupt(path, f"{name} 內容無法解析（{exc}），已改用預設值")
    if not isinstance(data, expected_type):
        return None, _backup_corrupt(path, f"{name} 格式不正確（最外層應為{type_label}），已改用預設值")
    return data, None


def _backup_corrupt(path, reason):
    """把有問題的原檔複製一份帶時間戳的備份，回傳要告訴使用者的訊息。

    檔名帶時間戳，同一個檔案壞第二次也不會蓋掉前一次的備份。
    """
    base, ext = os.path.splitext(path)
    backup = f"{base}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}{ext}"
    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        return f"{reason}；備份原檔失敗（{exc}），下次存檔會覆蓋 {path}，請先自行備份"
    return f"{reason}；原檔已備份為 {backup}"


def _write_json(path, payload):
    """把 payload 寫成 JSON。

    寫不進去（唯讀資料夾、權限不足、磁碟滿了）時回傳錯誤訊息而不是丟例外：
    存檔失敗不該讓關閉視窗的流程整個炸掉，由呼叫端決定要用執行日誌還是對話框提示。
    只攔 OSError——序列化本身失敗是程式的 bug，要讓它照常拋出來。

    先序列化成字串再碰磁碟，並寫到暫存檔後用 os.replace() 一次換掉原檔：
    直接開原檔寫入的話，序列化失敗或寫到一半當機都會留下被清空/截斷的檔案。
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        _remove_if_exists(tmp_path)
        return f"無法寫入 {path}：{exc}"
    return None


def _remove_if_exists(path):
    # 只是清掉寫失敗留下的暫存檔；清不掉也不影響原檔，真正的錯誤已由呼叫端回報。
    try:
        os.remove(path)
    except OSError:
        pass


def _is_number(value):
    # bool 是 int 的子類別，true/false 不能被當成座標。
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize_point(item):
    """[lat, lon] 或 [lat, lon, note] 正規化成新的 [lat, lon, note]；不合法回傳 None。"""
    if not isinstance(item, (list, tuple)) or len(item) not in (2, 3):
        return None
    lat, lon = item[0], item[1]
    if not (_is_number(lat) and _is_number(lon)):
        return None
    lat, lon = float(lat), float(lon)
    if not (is_valid_latitude(lat) and is_valid_longitude(lon)):
        return None
    note = item[2] if len(item) == 3 else ""
    return [lat, lon, str(note)]


def normalize_favorite(fav):
    """驗證一筆最愛，回傳正規化後的新 dict；格式不合回傳 None。

    未知的欄位原樣保留，日後新增欄位時舊版讀到也不會把它弄丟。
    """
    if not isinstance(fav, dict) or not isinstance(fav.get("name"), str):
        return None
    if fav.get("type") == "pin":
        point = _normalize_point([fav.get("lat"), fav.get("lon")])
        if point is None:
            return None
        return {**fav, "lat": point[0], "lon": point[1]}
    if fav.get("type") == "route":
        raw = fav.get("route")
        if not isinstance(raw, list) or len(raw) < 2:
            return None
        route = [_normalize_point(item) for item in raw]
        if any(point is None for point in route):
            return None
        return {**fav, "route": route}
    return None


def load_saved_route(settings):
    """讀取上次關閉程式前的路線座標點；沒有存檔或格式不對就回傳 None，讓呼叫端 fallback 回預設路線。"""
    raw = settings.get("last_route")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    route = [_normalize_point(item) for item in raw]
    if any(point is None for point in route):
        return None
    return route


DEFAULT_MAP_SETTINGS = {
    "tile_source": "auto",       # "auto" 跟隨主題；其餘見 widgets/map_panel.py 的 TILE_SOURCES
    "custom_tile_url": "",
    "custom_attribution": "",
    "center": [24.1368, 120.6862],
    "zoom": 15,
    "follow": True,
    "routing_costing": "pedestrian",  # 路徑規劃的移動方式，見 widgets/route_planner.py
    "simplify_m": 5.0,                # 規劃結果的抽稀容差（公尺），0 為不簡化
}


def load_map_settings(settings):
    """讀出 settings["map"]，補齊缺漏或型別不對的欄位後放回 settings。

    回傳的 dict 就是 settings["map"] 本身（同一個物件），MapPanel 會在使用者
    平移地圖、切換圖磚時就地更新它，關閉視窗時隨 save_settings() 一起寫回，
    不需要另外再收集一次。
    """
    raw = settings.get("map")
    result = dict(DEFAULT_MAP_SETTINGS)
    if isinstance(raw, dict):
        for key, default in DEFAULT_MAP_SETTINGS.items():
            value = raw.get(key, default)
            if isinstance(default, bool):
                result[key] = bool(value)
            elif isinstance(default, str):
                result[key] = str(value)
            elif key == "center":
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    try:
                        result[key] = [float(value[0]), float(value[1])]
                    except (TypeError, ValueError):
                        pass
            else:
                # 其餘是數值欄位（zoom 為 int、simplify_m 為 float），
                # 型別跟著預設值走，新增欄位時不必再回來改這裡。
                try:
                    result[key] = type(default)(value)
                except (TypeError, ValueError):
                    pass
    settings["map"] = result
    return result


def _kml_tag(elem):
    """去掉 XML namespace，取得元素的原始標籤名稱"""
    return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag


def parse_kml_route(path):
    """解析 KML 檔案，取出第一條 LineString 路線座標，
    並用最接近起訖點的 Point 名稱標記備註。
    回傳 (route, doc_name)，route 為 [[緯度, 經度, 備註], ...]，找不到路線時 route 為 None。"""
    tree = ET.parse(path)
    root = tree.getroot()

    doc_name = ""
    for elem in root.iter():
        if _kml_tag(elem) == "name":
            doc_name = (elem.text or "").strip()
            break

    line_points = []
    marker_points = []
    for placemark in root.iter():
        if _kml_tag(placemark) != "Placemark":
            continue
        pname = ""
        for child in placemark.iter():
            if _kml_tag(child) == "name":
                pname = (child.text or "").strip()
                break
        line_string = point_el = None
        for child in placemark.iter():
            ctag = _kml_tag(child)
            if ctag == "LineString" and line_string is None:
                line_string = child
            elif ctag == "Point" and point_el is None:
                point_el = child

        if line_string is not None and not line_points:
            coords_text = ""
            for child in line_string.iter():
                if _kml_tag(child) == "coordinates":
                    coords_text = child.text or ""
                    break
            for token in coords_text.split():
                parts = token.split(",")
                if len(parts) >= 2:
                    lon, lat = float(parts[0]), float(parts[1])
                    line_points.append([lat, lon, ""])
        elif point_el is not None:
            coords_text = ""
            for child in point_el.iter():
                if _kml_tag(child) == "coordinates":
                    coords_text = child.text or ""
                    break
            tokens = coords_text.split()
            if tokens:
                parts = tokens[0].split(",")
                if len(parts) >= 2:
                    lon, lat = float(parts[0]), float(parts[1])
                    marker_points.append((lat, lon, pname))

    if not line_points:
        return None, doc_name

    def nearest_marker_name(lat, lon):
        # 用實際距離而不是經緯度的「度」比較：經度 1 度的長度隨緯度縮短
        # （緯度 60 度時只剩一半），直接拿度數當距離會讓門檻隨地點忽大忽小。
        best_name, best_d = None, KML_MARKER_MATCH_M
        for mlat, mlon, mname in marker_points:
            if not mname:
                continue
            d = haversine(lat, lon, mlat, mlon)
            if d < best_d:
                best_d, best_name = d, mname
        return best_name

    start_name = nearest_marker_name(*line_points[0][:2])
    end_name = nearest_marker_name(*line_points[-1][:2])
    if start_name:
        line_points[0][2] = start_name
    if end_name:
        line_points[-1][2] = end_name

    return line_points, doc_name
