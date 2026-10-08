"""載入 Qt 內建的繁體中文翻譯，讓標準對話框的按鈕（OK／Cancel／Yes／No…）顯示中文。

App 自己的文字本來就是中文，這裡只翻 Qt 內建的字串：QMessageBox、QInputDialog、
QDialogButtonBox 的標準按鈕，以及 QLineEdit 右鍵選單這類。翻譯檔用的是 PySide6
隨附的 qtbase_zh_TW.qm，打包時 PinDrift.spec 的 KEEP_QT_TRANSLATION_SUFFIXES
有保留 `_zh_TW`，兩邊要一起改。
"""

import logging

from PySide6.QtCore import QLibraryInfo, QTranslator

logger = logging.getLogger(__name__)

QT_TRANSLATION = "qtbase_zh_TW"


def install_qt_translation(app):
    """安裝 Qt 內建翻譯；回傳 QTranslator（呼叫端要保留參照），找不到時回傳 None。

    找不到翻譯檔不影響使用，按鈕維持英文，只寫進記錄檔。
    """
    translator = QTranslator(app)
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load(QT_TRANSLATION, directory):
        logger.warning("找不到 Qt 翻譯檔 %s（%s），對話框按鈕會維持英文", QT_TRANSLATION, directory)
        return None
    app.installTranslator(translator)
    return translator
