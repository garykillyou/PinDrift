"""固定定位模式面板：緯度／經度輸入、快速選擇與座標貼上攔截。"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

from .. import theme
from ..geo import is_valid_latitude, is_valid_longitude

PIN_PRESETS = [
    ("台中火車站", 24.1368, 120.6862),
    ("台北101", 25.0338, 121.5645),
    ("高雄85大樓", 22.6155, 120.3025),
    ("台南孔廟", 22.9969, 120.2008),
]


class _CoordinatePasteLineEdit(QLineEdit):
    """貼上「緯度, 經度」格式的文字時（快速鍵或右鍵選單皆適用），改為分別帶入兩個欄位而非插入文字本身。

    QLineEdit 沒有像 QTextEdit 那樣的 insertFromMimeData() 掛勾可覆寫，且右鍵選單的
    「Paste」動作是接到 C++ 端非 virtual 的 paste() slot，Python 覆寫也攔不到；因此改為
    分別攔截 Ctrl+V 快速鍵與右鍵選單的 Paste 動作這兩個實際入口。
    """

    def __init__(self, on_paste_coordinates, parent=None):
        super().__init__(parent)
        self._on_paste_coordinates = on_paste_coordinates

    def _try_intercept_clipboard(self) -> bool:
        text = QApplication.clipboard().text()
        return bool(text) and self._on_paste_coordinates(text)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste) and self._try_intercept_clipboard():
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        for action in menu.actions():
            if "Paste" in action.text():
                action.triggered.disconnect()
                action.triggered.connect(self._on_paste_action)
        menu.exec(event.globalPos())

    def _on_paste_action(self, checked=False):
        if not self._try_intercept_clipboard():
            self.paste()


class PinPanel(QFrame):
    # 使用者「確定」了一組座標：按快速選擇、貼上座標、打完字（Enter 或離開欄位）。
    # 打字過程的 valueChanged 不算，否則每按一鍵都會把人瞬移到打到一半的座標。
    coordinates_committed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)

        layout.addWidget(theme.style_section_title(QLabel("固定座標")))

        form = QFormLayout()
        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setDecimals(6)
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setValue(24.1368)
        self.lat_spin.setLineEdit(_CoordinatePasteLineEdit(self._try_apply_pasted_coordinates))
        form.addRow("緯度：", self.lat_spin)

        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setDecimals(6)
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setValue(120.6862)
        self.lon_spin.setLineEdit(_CoordinatePasteLineEdit(self._try_apply_pasted_coordinates))
        form.addRow("經度：", self.lon_spin)
        layout.addLayout(form)
        self.lat_spin.editingFinished.connect(self._commit)
        self.lon_spin.editingFinished.connect(self._commit)

        layout.addWidget(QLabel("快速選擇："))
        presets_row = QHBoxLayout()
        for name, lat, lon in PIN_PRESETS:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked=False, la=lat, lo=lon: self._apply_preset(la, lo))
            presets_row.addWidget(btn)
        presets_row.addStretch(1)
        layout.addLayout(presets_row)

        # 沒有這個 stretch 項目時，QVBoxLayout 會把面板多出來的垂直空間平均分給
        # 上面每一列（包含兩個標題 QLabel），導致文字被撐在一個過高的空白區塊
        # 正中央，看起來像「標題列高度太大」。加在最後把多餘空間全部吸收掉，
        # 其餘內容維持貼齊頂端的自然高度。
        layout.addStretch(1)

    def _apply_preset(self, lat, lon):
        self.lat_spin.setValue(lat)
        self.lon_spin.setValue(lon)
        self._commit()

    def _commit(self):
        self.coordinates_committed.emit(*self.coordinates())

    def _try_apply_pasted_coordinates(self, text: str) -> bool:
        parts = text.split(",")
        if len(parts) != 2:
            return False
        try:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
        except ValueError:
            return False
        if not (is_valid_latitude(lat) and is_valid_longitude(lon)):
            return False
        self.lat_spin.setValue(lat)
        self.lon_spin.setValue(lon)
        self._commit()
        return True

    def coordinates(self):
        return self.lat_spin.value(), self.lon_spin.value()
