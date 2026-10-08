"""Qt 內建翻譯：標準按鈕要顯示中文。"""

from PySide6.QtWidgets import QDialogButtonBox

from gps_qt import i18n


def test_standard_buttons_are_translated(qapp):
    translator = i18n.install_qt_translation(qapp)
    try:
        assert translator is not None
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        texts = {buttons.button(b).text() for b in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel)}
        assert texts.isdisjoint({"OK", "&OK", "Cancel", "&Cancel"})
    finally:
        if translator is not None:
            qapp.removeTranslator(translator)
