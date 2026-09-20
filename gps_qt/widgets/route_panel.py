"""路線模式面板：速度設定 + 路線座標點表格（QTableView 虛擬化）。

表格為什麼用 QTableView 取代手刻的虛擬化清單，見 gps_qt/models.py 的說明。
"""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableView, QVBoxLayout,
)

from .. import theme
from ..geo import haversine
from ..models import COL_DELETE, COL_INDEX, COL_LAT, COL_LON, COL_NOTE, DeleteButtonDelegate, RouteTableModel

SPEED_PRESETS = [("步行 5 km/h", 5), ("慢跑 10 km/h", 10), ("騎車 20 km/h", 20), ("開車 40 km/h", 40)]

# 循環模式的兩種走法：來回（bounce，抵達端點折返）／迴圈（circuit，抵達端點瞬移回另一端，方向不變）。
LOOP_STYLE_BOUNCE = "bounce"
LOOP_STYLE_CIRCUIT = "circuit"
LOOP_STYLE_LABELS = [("來回（原路折返）", LOOP_STYLE_BOUNCE), ("迴圈（回到起點）", LOOP_STYLE_CIRCUIT)]


DEFAULT_SPEED_KMH = 20.0


class RoutePanel(QFrame):
    def __init__(self, route, parent=None, initial_speed=DEFAULT_SPEED_KMH):
        super().__init__(parent)
        layout = QVBoxLayout(self)

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
        self.speed_spin.setRange(0.1, 300.0)
        self.speed_spin.setValue(initial_speed)
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
        add_btn = QPushButton("新增點")
        theme.mark_class(add_btn, "success")
        add_btn.clicked.connect(self._add_point)
        header_row.addWidget(add_btn)
        clear_btn = QPushButton("清空座標點")
        clear_btn.clicked.connect(self._clear_points)
        header_row.addWidget(clear_btn)
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
        layout.addWidget(self.table)

        self._update_info()

    @property
    def route(self):
        return self.model._route

    def speed_ms(self):
        return self.speed_spin.value() * 1000 / 3600

    def loop_enabled(self):
        return self.loop_check.isChecked()

    def loop_style(self):
        return LOOP_STYLE_LABELS[self.loop_style_combo.currentIndex()][1]

    def set_route(self, route):
        self.model.set_route(route)
        self._update_info()

    def _add_point(self):
        route = self.model._route
        last = route[-1] if route else [24.0, 121.0, "新增點"]
        self.model.insert_point([last[0] + 0.001, last[1] + 0.001, "新增點"])

    def add_point_at(self, lat, lon, note=""):
        """在路線尾端加一個點（地圖點擊用）。"""
        self.model.insert_point([lat, lon, note])

    def move_point(self, row, lat, lon):
        """更新某個點的座標（地圖拖曳節點用）。"""
        self.model.set_coordinates(row, lat, lon)

    def delete_point(self, row):
        """刪除某個點。剩 2 個點時直接忽略：路線至少要兩點才能內插，UI 層先擋掉。

        表格的刪除欄與地圖節點的彈出視窗都走這裡，兩邊共用同一道下限檢查。
        """
        if len(self.model._route) <= 2:
            return
        self.model.remove_point(row)

    def _clear_points(self):
        self.model.clear()
        self.info_label.setText("")

    def _update_info(self):
        route = self.model._route
        if len(route) < 2:
            self.info_label.setText("")
            return
        dist = sum(
            haversine(route[i][0], route[i][1], route[i + 1][0], route[i + 1][1])
            for i in range(len(route) - 1)
        )
        speed = self.speed_ms()
        secs = dist / speed if speed > 0 else 0
        mins, sec2 = int(secs // 60), int(secs % 60)
        self.info_label.setText(
            f"總距離：{dist/1000:.2f} 公里  ·  預計時間：{mins} 分 {sec2} 秒  ·  共 {len(route)} 個節點"
        )
