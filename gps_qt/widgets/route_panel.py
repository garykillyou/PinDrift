"""路線模式面板：速度設定 + 路線座標點表格（QTableView 虛擬化）。

表格為什麼用 QTableView 取代手刻的虛擬化清單，見 gps_qt/models.py 的說明。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMenu, QMessageBox, QPushButton, QTableView, QVBoxLayout,
)

from .. import theme
from ..geo import adjacent_point, route_length
from ..models import COL_DELETE, COL_INDEX, COL_LAT, COL_LON, COL_NOTE, DeleteButtonDelegate, RouteTableModel

SPEED_PRESETS = [("步行 5 km/h", 5), ("慢跑 10 km/h", 10), ("騎車 20 km/h", 20), ("開車 40 km/h", 40)]

# 循環模式的兩種走法：來回（bounce，抵達端點折返）／迴圈（circuit，抵達端點瞬移回另一端，方向不變）。
LOOP_STYLE_BOUNCE = "bounce"
LOOP_STYLE_CIRCUIT = "circuit"
LOOP_STYLE_LABELS = [("來回（原路折返）", LOOP_STYLE_BOUNCE), ("迴圈（回到起點）", LOOP_STYLE_CIRCUIT)]


DEFAULT_SPEED_KMH = 20.0
# 速度欄位的範圍；最愛清單編輯路線速度時共用同一組，兩邊才不會一邊存得進去、另一邊被夾掉。
SPEED_MIN_KMH = 0.1
SPEED_MAX_KMH = 300.0


class RoutePanel(QFrame):
    def __init__(self, route, parent=None, initial_speed=DEFAULT_SPEED_KMH):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._locked = False

        # ── 速度設定卡 ──
        speed_card = QFrame(self)
        speed_card.setObjectName("card")
        speed_card.setFrameShape(QFrame.StyledPanel)
        speed_layout = QVBoxLayout(speed_card)
        speed_layout.addWidget(theme.style_section_title(QLabel("移動速度")))

        presets_row = QHBoxLayout()
        for label, kmh in SPEED_PRESETS:
            btn = QPushButton(label)
            theme.mark_class(btn, "no-uppercase")
            btn.clicked.connect(lambda checked=False, v=kmh: self.speed_spin.setValue(v))
            presets_row.addWidget(btn)
        presets_row.addStretch(1)
        speed_layout.addLayout(presets_row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("自訂 km/h："))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(SPEED_MIN_KMH, SPEED_MAX_KMH)
        self.speed_spin.setValue(initial_speed)
        # 預設按鈕也是走 setValue()，同一條 signal 就涵蓋兩種改速度的入口
        self.speed_spin.valueChanged.connect(lambda _value: self._update_info())
        custom_row.addWidget(self.speed_spin)
        self.loop_check = QCheckBox("循環模式")
        custom_row.addWidget(self.loop_check)
        self.loop_style_combo = QComboBox()
        for label, _value in LOOP_STYLE_LABELS:
            self.loop_style_combo.addItem(label)
        self.loop_style_combo.setEnabled(False)
        theme.fit_combo_width(self.loop_style_combo)
        self.loop_check.toggled.connect(self.loop_style_combo.setEnabled)
        custom_row.addWidget(self.loop_style_combo)
        custom_row.addStretch(1)
        speed_layout.addLayout(custom_row)
        layout.addWidget(speed_card)

        # ── 路線座標點 ──
        header_row = QHBoxLayout()
        header_row.addWidget(theme.style_section_title(QLabel("路線座標點")))
        self.info_label = QLabel("")
        header_row.addWidget(self.info_label)
        header_row.addStretch(1)
        self.add_btn = QPushButton("新增點")
        theme.mark_class(self.add_btn, "success")
        self.add_btn.clicked.connect(self._add_point)
        header_row.addWidget(self.add_btn)
        self.clear_btn = QPushButton("清空座標點")
        self.clear_btn.clicked.connect(self._clear_points)
        header_row.addWidget(self.clear_btn)
        layout.addLayout(header_row)

        self.model = RouteTableModel(route, on_changed=self._update_info)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(COL_NOTE, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_INDEX, 36)
        self.table.setColumnWidth(COL_LAT, 100)
        self.table.setColumnWidth(COL_LON, 100)
        self.table.setColumnWidth(COL_DELETE, 56)
        self.table.verticalHeader().setVisible(False)
        self.delete_delegate = DeleteButtonDelegate(self.table)
        self.delete_delegate.delete_requested.connect(self.delete_point)
        self.table.setItemDelegateForColumn(COL_DELETE, self.delete_delegate)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        layout.addWidget(self.table)

        self._update_info()

    @property
    def route(self):
        return self.model.route

    def speed_ms(self):
        return self.speed_spin.value() * 1000 / 3600

    def loop_enabled(self):
        return self.loop_check.isChecked()

    def loop_style(self):
        return LOOP_STYLE_LABELS[self.loop_style_combo.currentIndex()][1]

    def set_route(self, route):
        # model.set_route() 會經由 on_changed 觸發 _update_info()，不必自己再算一次。
        self.model.set_route(route)

    def set_locked(self, locked):
        """模擬移動中鎖住所有會改路線的入口（與地圖的編輯鎖同步）。

        只鎖地圖不夠：移動中改表格的話，地圖畫的是新路線、實際走的仍是舊路線；
        循環模式下清空路線，下一圈還會直接讓模擬中斷（修過的 bug）。表格本身不停用，
        移動中仍可捲動查看。整條替換的 set_route() 由 MainWindow 在入口擋掉。
        """
        self._locked = locked
        self.model.set_locked(locked)
        self.add_btn.setEnabled(not locked)
        self.clear_btn.setEnabled(not locked)

    def _add_point(self):
        if self._locked:
            return
        route = self.model.route
        last = route[-1] if route else [24.0, 121.0, "新增點"]
        self.model.insert_point([last[0] + 0.001, last[1] + 0.001, "新增點"])

    def add_point_at(self, lat, lon, note=""):
        """在路線尾端加一個點（地圖點擊用）。"""
        if self._locked:
            return
        self.model.insert_point([lat, lon, note])

    def move_point(self, row, lat, lon):
        """更新某個點的座標（地圖拖曳節點用）。"""
        if self._locked:
            return
        self.model.set_coordinates(row, lat, lon)

    def insert_adjacent(self, row, after):
        """在第 row 個點的前面（after=False）或後面（after=True）新增一個點。

        表格的右鍵選單與地圖節點的彈出視窗都走這裡，兩邊共用同一道鎖定檢查。
        新點的位置見 geo.adjacent_point()。
        """
        route = self.model.route
        if self._locked or not (0 <= row < len(route)):
            return
        point = adjacent_point(route, row, after)
        insert_row = row + 1 if after else row
        self.model.insert_point_at(insert_row, [point[0], point[1], "新增點"])
        self.table.selectRow(insert_row)

    def _show_row_menu(self, pos):
        index = self.table.indexAt(pos)
        if self._locked or not index.isValid():
            return
        row = index.row()
        menu = QMenu(self.table)
        menu.addAction("在前面新增點", lambda: self.insert_adjacent(row, False))
        menu.addAction("在後面新增點", lambda: self.insert_adjacent(row, True))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def delete_point(self, row):
        """刪除某個點。剩 2 個點時直接忽略：路線至少要兩點才能內插，UI 層先擋掉。

        表格的刪除欄與地圖節點的彈出視窗都走這裡，兩邊共用同一道下限檢查。
        """
        if self._locked or len(self.model.route) <= 2:
            return
        self.model.remove_point(row)

    def _clear_points(self):
        """清空前先確認：自動存檔會在兩秒內把空路線寫進設定，誤按就救不回來。"""
        count = len(self.model.route)
        if self._locked or count == 0:
            return
        reply = QMessageBox.question(
            self, "確認清空", f"確定要清空全部 {count} 個座標點嗎？此動作無法復原。"
        )
        if reply != QMessageBox.Yes:
            return
        # 清空後不到兩點，on_changed 觸發的 _update_info() 會一併清掉路線資訊。
        self.model.clear()

    def _update_info(self):
        route = self.model.route
        if len(route) < 2:
            self.info_label.setText("")
            return
        dist = route_length(route)
        speed = self.speed_ms()
        secs = dist / speed if speed > 0 else 0
        mins, sec2 = int(secs // 60), int(secs % 60)
        self.info_label.setText(
            f"總距離：{dist/1000:.2f} 公里  ·  預計時間：{mins} 分 {sec2} 秒  ·  共 {len(route)} 個節點"
        )
