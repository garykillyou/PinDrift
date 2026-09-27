"""路線表格的 Qt model/delegate：用 QTableView 取代手刻的虛擬化清單。

QTableView + QAbstractTableModel 原生只 render 可見列，不論路線有幾個點
都不需要自己管理列 widget 的重複利用。
"""

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QStyledItemDelegate

from .geo import is_valid_latitude, is_valid_longitude

COL_INDEX, COL_LAT, COL_LON, COL_NOTE, COL_DELETE = range(5)
HEADERS = ["#", "緯度", "經度", "備註", ""]


class RouteTableModel(QAbstractTableModel):
    def __init__(self, route, on_changed=None, parent=None):
        super().__init__(parent)
        self._route = route  # list of [lat, lon, note]，與呼叫端共用同一個 list 參照
        self._on_changed = on_changed

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._route)

    def columnCount(self, parent=QModelIndex()):
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return HEADERS[section]

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() in (COL_LAT, COL_LON, COL_NOTE):
            base |= Qt.ItemIsEditable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        point = self._route[row]
        if role == Qt.DisplayRole:
            if col == COL_INDEX:
                return str(row + 1)
            if col == COL_LAT:
                return f"{point[0]:.6f}"
            if col == COL_LON:
                return f"{point[1]:.6f}"
            if col == COL_NOTE:
                return point[2]
        elif role == Qt.EditRole:
            if col == COL_LAT:
                return point[0]
            if col == COL_LON:
                return point[1]
            if col == COL_NOTE:
                return point[2]
        elif role == Qt.TextAlignmentRole and col in (COL_INDEX, COL_DELETE):
            return Qt.AlignCenter
        return None

    @property
    def route(self):
        return self._route

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        row, col = index.row(), index.column()
        try:
            # 超出範圍的經緯度直接拒收：寫進去的值會原封不動送進 sim.set()。
            if col == COL_LAT:
                lat = float(value)
                if not is_valid_latitude(lat):
                    return False
                self._route[row][0] = lat
            elif col == COL_LON:
                lon = float(value)
                if not is_valid_longitude(lon):
                    return False
                self._route[row][1] = lon
            elif col == COL_NOTE:
                self._route[row][2] = str(value)
            else:
                return False
        except (TypeError, ValueError):
            return False
        self.dataChanged.emit(index, index)
        if self._on_changed:
            self._on_changed()
        return True

    def set_coordinates(self, row, lat, lon):
        """一次更新一列的經緯度（地圖拖曳節點用）。

        只發一次 dataChanged（涵蓋緯度到經度兩欄），而不是分兩次 setData()，
        避免拖曳一個點就觸發兩輪「回推路線給地圖」。
        """
        if not (0 <= row < len(self._route)):
            return
        self._route[row][0] = lat
        self._route[row][1] = lon
        self.dataChanged.emit(self.index(row, COL_LAT), self.index(row, COL_LON))
        if self._on_changed:
            self._on_changed()

    def set_route(self, route):
        self.beginResetModel()
        self._route = route
        self.endResetModel()

    def insert_point(self, point):
        row = len(self._route)
        self.beginInsertRows(QModelIndex(), row, row)
        self._route.append(point)
        self.endInsertRows()
        if self._on_changed:
            self._on_changed()

    def remove_point(self, row):
        if not (0 <= row < len(self._route)):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        self._route.pop(row)
        self.endRemoveRows()
        # 後面所有列的「#」欄位顯示需要重新整理
        if row < len(self._route):
            self.dataChanged.emit(self.index(row, COL_INDEX), self.index(len(self._route) - 1, COL_INDEX))
        if self._on_changed:
            self._on_changed()

    def clear(self):
        self.beginResetModel()
        self._route.clear()
        self.endResetModel()
        if self._on_changed:
            self._on_changed()


class DeleteButtonDelegate(QStyledItemDelegate):
    """在最後一欄畫「刪除」文字，點擊時發出 delete_requested(row)。

    刻意不用 setIndexWidget()：那會替每一列建立一個真正的 QWidget 並常駐，
    等於又要自己管理 widget 生命週期，違背用 QTableView 換掉手刻虛擬化的初衷。
    """

    delete_requested = Signal(int)

    def paint(self, painter, option, index):
        painter.save()
        painter.setPen(option.palette.text().color())
        painter.drawText(option.rect, Qt.AlignCenter, "刪除")
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and option.rect.contains(event.pos()):
            self.delete_requested.emit(index.row())
            return True
        return False

    def createEditor(self, parent, option, index):
        return None
