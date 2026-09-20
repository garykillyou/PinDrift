/* 地圖頁面邏輯：Leaflet 繪圖 + QWebChannel 與 Python 端雙向同步。
 *
 * 與 Python 的契約見 gps_qt/map_bridge.py 的 MapBridge：
 *   Python -> JS 是 bridge 上的 signal（這裡用 .connect() 接收）
 *   JS -> Python 是 bridge 上的 slot（這裡直接呼叫 bridge.on_xxx()）
 *
 * 回授迴圈防護：renderRoute() 收到的 JSON 與上次完全相同就直接 return。
 * 拖曳節點時只在 dragend 通知 Python（drag 過程僅在本地更新折線），
 * 因此 Python 回推的那一次重繪一定發生在拖曳結束之後，不會打斷拖曳。
 */

"use strict";

var TRAIL_MAX_POINTS = 3000;
var DEFAULT_CENTER = [24.1368, 120.6862];
var DEFAULT_ZOOM = 15;
var FOLLOW_PAN_SECONDS = 0.8;
var SINGLE_POINT_ZOOM = 16;
var FIT_PADDING = [40, 40];

var bridge = null;
var map = null;
var tileLayer = null;

var state = {
  mode: "route",
  locked: false,
  follow: true,
  routeJson: "",
  tileError: false
};

var routeLayer = null;
var routeMarkerLayer = null;
var routeMarkers = [];
var routeLine = null;
var pinLayer = null;
var pinMarker = null;
var currentMarker = null;
var trailLine = null;
var trailPoints = [];
var favoriteLayer = null;
var pickLayer = null;

/* ── 標記圖示 ─────────────────── */

function routeIcon(index, total) {
  var cls = "route-pin";
  if (index === 0) {
    cls += " route-pin-start";
  } else if (index === total - 1) {
    cls += " route-pin-end";
  }
  return L.divIcon({
    className: "",
    html: '<div class="' + cls + '">' + (index + 1) + "</div>",
    iconSize: [26, 26],
    iconAnchor: [13, 13]
  });
}

function pinIcon() {
  return L.divIcon({
    className: "",
    html: '<div class="pin-marker"></div>',
    iconSize: [30, 30],
    iconAnchor: [15, 30]
  });
}

function currentIcon() {
  return L.divIcon({
    className: "",
    html: '<div class="current-marker"></div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9]
  });
}

/* ── 初始化 ─────────────────── */

function initMap() {
  map = L.map("map", { zoomControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);

  routeLine = L.polyline([], { className: "route-line" });
  // 節點另外放一層：移動中只要把這層從 routeLayer 拿掉，路徑線就會單獨留著。
  routeMarkerLayer = L.layerGroup();
  routeLayer = L.layerGroup([routeLine, routeMarkerLayer]).addTo(map);
  pinLayer = L.layerGroup();
  favoriteLayer = L.layerGroup().addTo(map);
  pickLayer = L.layerGroup().addTo(map);
  // 軌跡與目前位置在兩種模式下都要看得到，所以直接掛在 map 上而非模式圖層。
  trailLine = L.polyline([], { className: "trail-line" }).addTo(map);

  map.on("click", onMapClick);
  map.on("dragstart", onUserDrag);
  map.on("moveend", onMoveEnd);
  map.on("popupopen", onPopupOpen);
}

function connectBridge() {
  if (typeof qt === "undefined" || !qt.webChannelTransport) {
    showBanner("無法建立與應用程式的連線（QWebChannel 未就緒）");
    return;
  }
  new QWebChannel(qt.webChannelTransport, function (channel) {
    bridge = channel.objects.bridge;
    bridge.route_changed.connect(renderRoute);
    bridge.pin_changed.connect(renderPin);
    bridge.mode_changed.connect(setMode);
    bridge.position_changed.connect(setPosition);
    bridge.trail_cleared.connect(clearTrail);
    bridge.edit_locked.connect(setLocked);
    bridge.tile_changed.connect(setTile);
    bridge.fit_bounds.connect(fitBounds);
    bridge.follow_changed.connect(setFollow);
    bridge.favorites_changed.connect(setFavorites);
    bridge.view_requested.connect(setView);
    bridge.pick_state_changed.connect(setPickState);
    bridge.on_map_ready();
  });
}

/* ── 地圖事件 ─────────────────── */

function onMapClick(e) {
  if (!bridge || state.locked) {
    return;
  }
  bridge.on_map_clicked(e.latlng.lat, e.latlng.lng);
}

function onUserDrag() {
  // 使用者自己拖動地圖時關閉跟隨，避免程式每秒把畫面拉回目前位置跟使用者搶地圖。
  // panTo() 不會觸發 dragstart，所以這裡只會被真正的手動拖曳叫到。
  if (state.follow && bridge) {
    state.follow = false;
    bridge.on_follow_disengaged();
  }
}

function onMoveEnd() {
  if (!bridge) {
    return;
  }
  var center = map.getCenter();
  bridge.on_view_changed(center.lat, center.lng, map.getZoom());
}

function onPopupOpen(e) {
  var element = e.popup.getElement();
  if (!element) {
    return;
  }
  var button = element.querySelector(".pt-delete");
  if (!button) {
    return;
  }
  button.disabled = state.locked;
  button.addEventListener("click", function () {
    if (bridge && !state.locked) {
      bridge.on_point_delete_requested(parseInt(button.getAttribute("data-idx"), 10));
    }
    map.closePopup();
  });
}

/* ── 路線 ─────────────────── */

function renderRoute(json) {
  // 內容完全相同就不重繪：Python 端在每次模型變動後都會回推，
  // 沒有這道比對的話，拖曳結束後的回推會把整批標記重建一次。
  if (json === state.routeJson) {
    return;
  }
  state.routeJson = json;
  var points = JSON.parse(json).points;
  syncRouteMarkers(points);
  routeLine.setLatLngs(points.map(function (p) { return [p[0], p[1]]; }));
}

function syncRouteMarkers(points) {
  while (routeMarkers.length > points.length) {
    routeMarkerLayer.removeLayer(routeMarkers.pop());
  }
  for (var i = 0; i < points.length; i++) {
    var latlng = [points[i][0], points[i][1]];
    var marker = routeMarkers[i];
    if (!marker) {
      // 一律用 draggable: true 建立再視情況 disable()：Leaflet 只有在建構時
      // options.draggable 為真才會建立 marker.dragging handler，用 false 建立
      // 之後就再也無法啟用拖曳。
      marker = L.marker(latlng, { icon: routeIcon(i, points.length), draggable: true });
      marker.addTo(routeMarkerLayer);
      bindRouteMarker(marker);
      routeMarkers[i] = marker;
    } else {
      marker.setLatLng(latlng);
      marker.setIcon(routeIcon(i, points.length));
    }
    marker.routeIndex = i;
    marker.bindPopup(pointPopupHtml(i, points[i]));
    setDraggable(marker, !state.locked);
  }
}

function bindRouteMarker(marker) {
  marker.on("drag", function () {
    // 拖曳過程只在本地更新折線，不通知 Python，避免每個 mousemove 都往回打一次。
    var latlngs = routeLine.getLatLngs();
    latlngs[marker.routeIndex] = marker.getLatLng();
    routeLine.setLatLngs(latlngs);
  });
  marker.on("dragend", function () {
    var latlng = marker.getLatLng();
    if (bridge) {
      bridge.on_point_dragged(marker.routeIndex, latlng.lat, latlng.lng);
    }
  });
}

function pointPopupHtml(index, point) {
  var note = point[2] ? escapeHtml(point[2]) : "（無備註）";
  return '<div class="pt-title">#' + (index + 1) + "　" + note + "</div>" +
    '<div class="pt-coord">' + point[0].toFixed(6) + ", " + point[1].toFixed(6) + "</div>" +
    '<button type="button" class="pt-delete" data-idx="' + index + '">刪除此點</button>';
}

/* ── 固定定位 ─────────────────── */

function renderPin(lat, lon) {
  if (!pinMarker) {
    pinMarker = L.marker([lat, lon], { icon: pinIcon(), draggable: true });
    pinMarker.addTo(pinLayer);
    pinMarker.on("dragend", function () {
      var latlng = pinMarker.getLatLng();
      if (bridge) {
        bridge.on_pin_dragged(latlng.lat, latlng.lng);
      }
    });
  } else {
    pinMarker.setLatLng([lat, lon]);
  }
  setDraggable(pinMarker, !state.locked);
}

/* ── 模式 / 鎖定 / 跟隨 ─────────────────── */

function setMode(mode) {
  state.mode = mode;
  toggleLayer(routeLayer, mode === "route");
  toggleLayer(pinLayer, mode === "pin");
}

function setLocked(locked) {
  state.locked = locked;
  if (pinMarker) {
    setDraggable(pinMarker, !locked);
  }
  // 移動中把整層節點藏起來，只留下路徑線；解鎖後原本的節點會直接回來。
  routeMarkers.forEach(function (marker) {
    setDraggable(marker, !locked);
  });
  toggleSubLayer(routeLayer, routeMarkerLayer, !locked);
  map.closePopup();
  updateBanner();
}

function setFollow(follow) {
  state.follow = follow;
}

/* ── 目前位置與軌跡 ─────────────────── */

function setPosition(lat, lon) {
  var latlng = [lat, lon];
  if (!currentMarker) {
    currentMarker = L.marker(latlng, {
      icon: currentIcon(),
      interactive: false,
      zIndexOffset: 1000
    }).addTo(map);
  } else {
    currentMarker.setLatLng(latlng);
  }
  trailPoints.push(latlng);
  if (trailPoints.length > TRAIL_MAX_POINTS) {
    decimateTrail();
  }
  trailLine.setLatLngs(trailPoints);
  if (state.follow) {
    map.panTo(latlng, { animate: true, duration: FOLLOW_PAN_SECONDS });
  }
}

function decimateTrail() {
  // 每兩點取一點。循環模式跑久了軌跡點會無上限成長，抽稀後線形幾乎不變，
  // 但點數回到一半，避免長時間執行累積出巨大的 polyline。
  var thinned = [];
  for (var i = 0; i < trailPoints.length; i += 2) {
    thinned.push(trailPoints[i]);
  }
  var last = trailPoints[trailPoints.length - 1];
  if (thinned[thinned.length - 1] !== last) {
    thinned.push(last);
  }
  trailPoints = thinned;
}

function clearTrail() {
  trailPoints = [];
  trailLine.setLatLngs([]);
  if (currentMarker) {
    map.removeLayer(currentMarker);
    currentMarker = null;
  }
}

/* ── 圖磚 ─────────────────── */

function setTile(url, attribution) {
  if (tileLayer) {
    map.removeLayer(tileLayer);
  }
  state.tileError = false;
  updateBanner();
  tileLayer = L.tileLayer(url, { maxZoom: 19, attribution: attribution });
  tileLayer.on("tileerror", function () {
    if (!state.tileError) {
      state.tileError = true;
      updateBanner();
    }
  });
  tileLayer.addTo(map);
}

/* ── 視野 ─────────────────── */

function fitBounds(json) {
  var points = JSON.parse(json);
  if (!points.length) {
    return;
  }
  if (points.length === 1) {
    map.setView(points[0], SINGLE_POINT_ZOOM);
    return;
  }
  map.fitBounds(L.latLngBounds(points), { padding: FIT_PADDING });
}

function setView(lat, lon, zoom) {
  map.setView([lat, lon], zoom);
}

/* ── 最愛 ─────────────────── */

function setFavorites(json) {
  // 只會收到地點最愛：路線最愛畫成線會跟編輯中的路線混在一起，Python 端已經濾掉。
  favoriteLayer.clearLayers();
  JSON.parse(json).forEach(function (fav) {
    var layer = L.circleMarker([fav.lat, fav.lon], { radius: 9, className: "fav-pin-marker" });
    layer.bindTooltip(fav.name);
    layer.on("click", function (e) {
      L.DomEvent.stop(e);
      if (bridge) {
        bridge.on_favorite_activated(fav.index);
      }
    });
    layer.addTo(favoriteLayer);
  });
}

/* ── 路徑規劃的點選狀態 ─────────────────── */

function setPickState(picking, json) {
  // 點選過程中每點一下都要把已選的點畫出來，否則使用者無從得知剛才
  // 那一下有沒有被收到；點的數量不固定（多點依序點選，按「完成規劃」才結束），
  // 所以標記文字用「起」與後續的點次序號，而不是固定的「起」「終」兩種。
  pickLayer.clearLayers();
  map.getContainer().classList.toggle("map-picking", picking);
  JSON.parse(json).forEach(function (point, index) {
    L.marker(point, {
      icon: L.divIcon({
        className: "",
        html: '<div class="pick-pin">' + (index === 0 ? "起" : String(index + 1)) + "</div>",
        iconSize: [28, 28],
        iconAnchor: [14, 14]
      }),
      interactive: false,
      zIndexOffset: 900
    }).addTo(pickLayer);
  });
}

/* ── 工具 ─────────────────── */

function setDraggable(marker, enabled) {
  if (!marker.dragging) {
    return;
  }
  if (enabled) {
    marker.dragging.enable();
  } else {
    marker.dragging.disable();
  }
}

function toggleSubLayer(parent, layer, visible) {
  if (visible && !parent.hasLayer(layer)) {
    parent.addLayer(layer);
  } else if (!visible && parent.hasLayer(layer)) {
    parent.removeLayer(layer);
  }
}

function toggleLayer(layer, visible) {
  if (visible && !map.hasLayer(layer)) {
    map.addLayer(layer);
  } else if (!visible && map.hasLayer(layer)) {
    map.removeLayer(layer);
  }
}

function escapeHtml(text) {
  var div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function updateBanner() {
  if (state.locked) {
    showBanner("模擬進行中，地圖編輯已鎖定");
  } else if (state.tileError) {
    showBanner("圖磚載入失敗，請確認網路連線或改用其他圖磚來源");
  } else {
    hideBanner();
  }
}

function showBanner(text) {
  var banner = document.getElementById("banner");
  banner.textContent = text;
  banner.classList.remove("banner-hidden");
}

function hideBanner() {
  document.getElementById("banner").classList.add("banner-hidden");
}

window.addEventListener("error", function (event) {
  if (bridge) {
    bridge.on_js_error(event.message + " @ " + event.filename + ":" + event.lineno);
  }
});

initMap();
connectBridge();
