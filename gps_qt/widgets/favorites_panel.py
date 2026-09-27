"""最愛清單面板：顯示、載入、重新命名與刪除已儲存的地點／路線。

QListWidget + 自訂 item widget：最愛清單項目數通常不多，不像路線表格要
處理數千筆，這裡不需要虛擬化。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import persistence, theme

RENAME_DIALOG_MIN_WIDTH = 400
RENAME_DIALOG_PADDING = 120  # 容納對話框邊距與輸入框內距，避免文字貼齊邊緣


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


class FavoritesPanel(QFrame):
    load_requested = Signal(dict)
    # 清單內容或篩選模式變動（新增/改名/刪除/切換模式），讓地圖重畫最愛圖層。
    favorites_changed = Signal()

    def __init__(self, pin_provider, route_provider, mode_provider, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self._pin_provider = pin_provider
        self._route_provider = route_provider
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
        filtered = [(i, fav) for i, fav in enumerate(self.favorites) if fav["type"] == current_type]
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
        preview = f"{fav['lat']:.4f}, {fav['lon']:.4f}" if fav["type"] == "pin" else f"{len(fav['route'])} 個節點"
        preview_label = _fix_to_hint(QLabel(preview), extra=4)
        row_layout.addWidget(preview_label)
        load_btn = _fix_to_hint(QPushButton("載入"))
        load_btn.clicked.connect(lambda checked=False, f=fav: self.load_requested.emit(f))
        row_layout.addWidget(load_btn)
        rename_btn = _fix_to_hint(QPushButton("編輯"))
        rename_btn.clicked.connect(lambda checked=False, idx=i: self._rename(idx))
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
        self.favorites.append({"type": "route", "name": name, "route": [list(r) for r in route]})
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

    def _rename(self, i):
        fav = self.favorites[i]
        dialog = QInputDialog(self)
        dialog.setWindowTitle("重新命名")
        dialog.setLabelText("請輸入新名稱：")
        dialog.setTextValue(fav["name"])
        text_width = dialog.fontMetrics().horizontalAdvance(fav["name"])
        width = max(RENAME_DIALOG_MIN_WIDTH, text_width + RENAME_DIALOG_PADDING)
        dialog.resize(width, dialog.sizeHint().height())
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
