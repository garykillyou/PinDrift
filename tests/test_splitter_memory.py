"""SplitterMemory 的測試：拖曳後記下大小、下次套回去，程式自己 setSizes() 不算拖曳。"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QWidget

from gps_qt.splitter_memory import SplitterMemory

SPLITTER_LENGTH = 1000


@pytest.fixture
def splitter(qapp):
    widget = QSplitter(Qt.Horizontal)
    widget.addWidget(QWidget())
    widget.addWidget(QWidget())
    widget.resize(SPLITTER_LENGTH, 300)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


class Counter:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def test_restore_without_saved_sizes_uses_default(splitter):
    # Arrange
    memory = SplitterMemory({}, Counter())

    # Act
    memory.restore(splitter, "left", default=[1, 3])

    # Assert
    first, second = splitter.sizes()
    assert second == pytest.approx(first * 3, abs=2)


def test_restore_scales_saved_sizes_proportionally(splitter):
    # Arrange
    memory = SplitterMemory({"left": [300, 100]}, Counter())

    # Act
    memory.restore(splitter, "left")

    # Assert
    first, second = splitter.sizes()
    assert first == pytest.approx(second * 3, abs=2)
    assert first + second > 400


def test_restore_does_not_count_as_user_drag(splitter):
    # Arrange
    changed = Counter()
    memory = SplitterMemory({"left": [300, 100]}, changed)
    memory.watch(splitter, lambda: "left")

    # Act
    memory.restore(splitter, "left")

    # Assert
    assert changed.calls == 0
    assert memory.sizes == {"left": [300, 100]}


def test_user_drag_records_sizes_under_current_key(splitter):
    # Arrange
    changed = Counter()
    memory = SplitterMemory({"other": [1, 2]}, changed)
    keys = iter(["first", "second"])
    memory.watch(splitter, lambda: next(keys))

    # Act
    splitter.splitterMoved.emit(400, 1)
    splitter.splitterMoved.emit(600, 1)

    # Assert
    assert changed.calls == 2
    assert set(memory.sizes) == {"other", "first", "second"}
    assert memory.sizes["second"] == splitter.sizes()


def test_sizes_are_copies():
    # Arrange
    original = {"left": [1, 2]}
    memory = SplitterMemory(original, Counter())

    # Act
    memory.sizes["left"] = [9, 9]
    memory.sizes["left"].append(3)

    # Assert
    assert memory.sizes == {"left": [1, 2]}
    assert original == {"left": [1, 2]}
