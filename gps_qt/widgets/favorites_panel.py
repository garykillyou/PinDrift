"""最愛清單面板：顯示、載入、重新命名與刪除已儲存的地點／路線。

QListWidget + 自訂 item widget：最愛清單項目數通常不多，不像路線表格要
處理數千筆，這裡不需要虛擬化。
"""

from PySide6.QtCore import QCollator, QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import persistence, theme
from .route_panel import SPEED_MAX_KMH, SPEED_MIN_KMH

RENAME_DIALOG_MIN_WIDTH = 400
RENAME_DIALOG_PADDING = 120  # 容納對話框邊距與輸入框內距，避免文字貼齊邊緣


def _dialog_width(dialog, text):
    """依名稱長度決定編輯對話框的寬度，長名稱不會被輸入框截掉。"""
    text_width = dialog.fontMetrics().horizontalAdvance(text)
    return max(RENAME_DIALOG_MIN_WIDTH, text_width + RENAME_DIALOG_PADDING)


def sorted_by_name(favorites, fav_type):
    """取出指定類型的最愛並依名稱排序，回傳 (在完整清單裡的原始位置, 最愛) 串列。

    只排顯示順序，不改動 favorites 本身：編輯／刪除／地圖圓點都靠原始位置對回
    同一筆資料，存檔順序也維持不變。用 QCollator 依繁體中文（zh_TW）規則比對
    （不分大小寫、數字依數值大小，「路線2」排在「路線10」前面）；固定語系而不跟
    系統走，換到非繁中的 Windows 上順序才不會改變。同名時維持原本的先後。
    """
    collator = QCollator(QLocale(QLocale.Chinese, QLocale.Taiwan))
    collator.setCaseSensitivity(Qt.CaseInsensitive)
    collator.setNumericMode(True)
    filtered = [(i, fav) for i, fav in enumerate(favorites) if fav["type"] == fav_type]
    return sorted(filtered, key=lambda item: collator.sortKey(item[1]["name"]))


def _fix_to_hint(widget, extra=0):
    """把 widget 固定在它自己 sizeHint() 所需的寬度（可另外加一點邊界）。

    不用猜測的像素常數：按鈕/label 的實際所需寬度取決於目前套用的 QSS
    （padding、字型），寫死的數字換主題或調字級後很容易變成太窄而裁切文字。
    呼叫時機必須在 QApplication 已經套用樣式表「之後」，sizeHint() 才會反映
    正確的 padding。
    """
    widget.setFixedWidth(widget.sizeHint().width() + extra)
    return widget


class _ElidingLabel(QLabel):
    """名稱欄：寬度不夠時自動截斷加省略號。

    欄位寬度會隨視窗寬度改變，所以不能只在建立時算一次，而是每次 resize 都
    重新算可容納的文字長度。這樣名稱再長也只會在自己的欄位內被截斷，不會把
    整列往右撐出視窗、逼使用者橫向捲動。
    """

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, self.width())
        self.setText(elided)


class _RouteEditDialog(QDialog):
    """路線最愛的編輯對話框：名稱 + 儲存的速度。

    速度是選填的（KML 匯入、舊版存的路線沒有），所以用核取方塊表示「載入時要不要
    還原速度」；取消勾選就把這個欄位拿掉，載入時不改動目前的速度。
    """

    def __init__(self, fav, default_speed, parent=None):
        super().__init__(parent)
        self.setWindowTitle("編輯路線")
        form = QFormLayout(self)

        self.name_edit = QLineEdit(fav["name"])
        form.addRow("名稱：", self.name_edit)

        speed_row = QHBoxLayout()
        self.speed_check = QCheckBox("載入時套用速度")
        self.speed_check.setChecked("speed_kmh" in fav)
        speed_row.addWidget(self.speed_check)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(SPEED_MIN_KMH, SPEED_MAX_KMH)
        self.speed_spin.setSuffix(" km/h")
        # 沒存過速度時預設帶目前的速度，勾選後不必再從頭輸入。
        self.speed_spin.setValue(fav.get("speed_kmh", default_speed))
        self.speed_spin.setEnabled(self.speed_check.isChecked())
        self.speed_check.toggled.connect(self.speed_spin.setEnabled)
        speed_row.addWidget(self.speed_spin, 1)
        form.addRow("速度：", speed_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.Ok)
        self.name_edit.textChanged.connect(lambda text: self._ok_btn.setEnabled(bool(text.strip())))
        form.addRow(buttons)

        self.resize(_dialog_width(self, fav["name"]), self.sizeHint().height())

    def edited(self, fav):
        """依對話框內容產生新的最愛（不改動傳入的 fav）。"""
        result = {k: v for k, v in fav.items() if k != "speed_kmh"}
        result["name"] = self.name_edit.text().strip()
        if self.speed_check.isChecked():
            result["speed_kmh"] = self.speed_spin.value()
        return result


class FavoritesPanel(QFrame):
    load_requested = Signal(dict)
    # 清單內容或篩選模式變動（新增/改名/刪除/切換模式），讓地圖重畫最愛圖層。
    favorites_changed = Signal()

    def __init__(self, pin_provider, route_provider, mode_provider, speed_provider, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self._pin_provider = pin_provider
        self._route_provider = route_provider
        self._speed_provider = speed_provider
        self._mode_provider = mode_provider
        # 讀檔有狀況（檔案壞掉已備份、略過了格式不對的項目）時的說明，建構期間
        # 還沒有地方可以顯示，由 MainWindow 在版面建好後寫進執行日誌。
        self.favorites, self.load_message = persistence.load_favorites()

        layout = QVBoxLayout(self)
        title_row = QHBoxLayout()
        title_row.addWidget(theme.style_section_title(QLabel("我的最愛")))
        title_row.addStretch(1)
        self._save_pin_btn = QPushButton("儲存目前座標")
        theme.mark_class(self._save_pin_btn, "success")
        self._save_pin_btn.clicked.connect(self._save_pin)
        title_row.addWidget(self._save_pin_btn)
        self._save_route_btn = QPushButton("儲存目前路線")
        theme.mark_class(self._save_route_btn, "success")
        self._save_route_btn.clicked.connect(self._save_route)
        title_row.addWidget(self._save_route_btn)
        self._import_btn = QPushButton("匯入 KML 路線")
        theme.mark_class(self._import_btn, "success")
        self._import_btn.clicked.connect(self._import_kml)
        title_row.addWidget(self._import_btn)
        layout.addLayout(title_row)

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.list_widget)
        self.refresh()

    def refresh(self):
        self._rebuild_list()
        self.favorites_changed.emit()

    def _rebuild_list(self):
        self.list_widget.clear()
        current_type = "pin" if self._mode_provider() == "pin" else "route"
        self._save_pin_btn.setVisible(current_type == "pin")
        self._save_route_btn.setVisible(current_type == "route")
        self._import_btn.setVisible(current_type == "route")
        filtered = sorted_by_name(self.favorites, current_type)
        if not filtered:
            empty_text = "尚無儲存的最愛地點" if current_type == "pin" else "尚無儲存的最愛路線"
            item = QListWidgetItem(empty_text)
            item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item)
            return
        for i, fav in filtered:
            item = QListWidgetItem()
            self.list_widget.addItem(item)
            row_widget = self._build_row(i, fav)
            theme.fit_list_item(item, row_widget)
            self.list_widget.setItemWidget(item, row_widget)

    def _build_row(self, i, fav):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)
        name_label = theme.mark_class(_ElidingLabel(fav["name"]), "bold")
        row_layout.addWidget(name_label, 1)
        if fav["type"] == "pin":
            preview = f"{fav['lat']:.4f}, {fav['lon']:.4f}"
        else:
            preview = f"{len(fav['route'])} 個節點"
            if "speed_kmh" in fav:
                preview += f"・{fav['speed_kmh']:g} km/h"
        preview_label = _fix_to_hint(QLabel(preview), extra=4)
        row_layout.addWidget(preview_label)
        load_btn = _fix_to_hint(QPushButton("載入"))
        load_btn.clicked.connect(lambda checked=False, f=fav: self.load_requested.emit(f))
        row_layout.addWidget(load_btn)
        rename_btn = _fix_to_hint(QPushButton("編輯"))
        rename_btn.clicked.connect(lambda checked=False, idx=i: self._edit(idx))
        row_layout.addWidget(rename_btn)
        delete_btn = QPushButton("刪除")
        theme.mark_class(delete_btn, "danger")
        _fix_to_hint(delete_btn)
        delete_btn.clicked.connect(lambda checked=False, idx=i: self._delete(idx))
        row_layout.addWidget(delete_btn)
        return row

    def _save(self):
        error = persistence.save_favorites(self.favorites)
        if error:
            # 存最愛是使用者主動按下去的動作，失敗要當場講，不能只寫進日誌。
            QMessageBox.warning(self, "儲存失敗", error)
        self.refresh()

    def _save_pin(self):
        lat, lon = self._pin_provider()
        name, ok = QInputDialog.getText(self, "儲存最愛", "請輸入地點名稱：", text="我的地點")
        if not ok or not name:
            return
        self.favorites.append({"type": "pin", "name": name, "lat": lat, "lon": lon})
        self._save()

    def _save_route(self):
        route = self._route_provider()
        if len(route) < 2:
            QMessageBox.critical(self, "錯誤", "請至少設定 2 個路線點")
            return
        name, ok = QInputDialog.getText(self, "儲存最愛", "請輸入路線名稱：", text="我的路線")
        if not ok or not name:
            return
        # 同名的路線最愛直接覆蓋（保留在清單裡的原位置），方便反覆更新同一條路線。
        self.favorites = persistence.upsert_favorite(self.favorites, {
            "type": "route", "name": name, "route": [list(r) for r in route],
            "speed_kmh": self._speed_provider(),
        })
        self._save()

    def _import_kml(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇 KML 檔案", "", "KML 檔案 (*.kml);;所有檔案 (*.*)")
        if not path:
            return
        try:
            route, doc_name = persistence.parse_kml_route(path)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"KML 檔案解析失敗：\n{e}")
            return
        if not route or len(route) < 2:
            QMessageBox.critical(self, "錯誤", "此 KML 檔案內找不到有效的路線（LineString 座標）")
            return
        default_name = doc_name or path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        name, ok = QInputDialog.getText(self, "儲存最愛", "請輸入路線名稱：", text=default_name)
        if not ok or not name:
            return
        self.favorites.append({"type": "route", "name": name, "route": route})
        self._save()

    def _edit(self, i):
        if self.favorites[i]["type"] == "route":
            self._edit_route(i)
        else:
            self._rename(i)

    def _edit_route(self, i):
        fav = self.favorites[i]
        dialog = _RouteEditDialog(fav, self._speed_provider(), self)
        if not dialog.exec():
            return
        self.favorites[i] = dialog.edited(fav)
        self._save()

    def _rename(self, i):
        fav = self.favorites[i]
        dialog = QInputDialog(self)
        dialog.setWindowTitle("重新命名")
        dialog.setLabelText("請輸入新名稱：")
        dialog.setTextValue(fav["name"])
        dialog.resize(_dialog_width(dialog, fav["name"]), dialog.sizeHint().height())
        ok = dialog.exec()
        name = dialog.textValue()
        if not ok or not name:
            return
        fav["name"] = name
        self._save()

    def _delete(self, i):
        fav = self.favorites[i]
        reply = QMessageBox.question(self, "確認刪除", f"確定要刪除「{fav['name']}」嗎？")
        if reply != QMessageBox.Yes:
            return
        self.favorites.pop(i)
        self._save()
