"""主題套用：改用 qt-material 套件產生樣式表，取代自寫的 QSS。

qt-material 最新版本身沒有版本限制問題（純 Python，任何 Qt binding 皆可）。
色票（含 danger/success 等語意色）全部使用 qt-material 內建主題的預設值，
不覆寫成自訂品牌色。
"""

import qt_material
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QComboBox

THEME_FILES = {"dark": "dark_red.xml", "light": "light_red.xml"}

FS_TITLE = 22  # App 標題字級（pt），qt-material 本身不管這個，維持原本大小
FS_SECTION_TITLE = 18  # 區塊標題（「移動速度」「我的最愛」這類），比內文大 3 階


# qt-material 的樣式表最上層有一條 `* { font-size: ...px; ... }` 規則，套用在
# QApplication 層級時，會蓋掉個別 widget 用 setFont() 設定的字級（Qt 的樣式表
# 屬性一旦命中該 widget，優先權高於程式設定的 QFont）。所以字級大小的例外一律
# 要用「更明確的 QSS 選擇器」蓋回去，不能只靠 setFont()——這裡沿用 mark_class()
# 同一套「動態屬性 class + 對應 QSS 規則」機制。
EXTRA_QSS_TEMPLATE = """
.app-title {{ font-size: {app_title}pt; font-weight: bold; }}
.section-title {{ font-size: {section_title}pt; font-weight: bold; }}
.no-uppercase {{ text-transform: none; }}
.bold {{ font-weight: bold; }}
"""


# qt-material 的控制項高度其實對不齊：樣式表裡雖然都寫 `height: 28px`，但那是
# 內容區高度，各類 widget 的 padding 與邊框不同，實測 sizeHint 分別是
# QPushButton 40 / QComboBox 32 / QLineEdit 30 / QDoubleSpinBox 33 px，並排在
# 同一排工具列時高低不一。另外 qt-material 把輸入類 widget 當成 Material 的
# 「填色輸入框」（只有底線 border-width: 0 0 2px 0、只有上緣圓角），與 QPushButton
# 的「四邊 2px 框線 + 4px 圓角」也不同調。
#
# 下面這段把「按鈕 + 下拉選單 + 單行輸入 + 數值輸入」統一成同一組外框與同一個
# 高度，並讓展開後的清單（QComboBox QAbstractItemView）與 QMenu 跟著對齊。
# 內容區高度（不含 padding 與邊框）。這個值必須和 widget 實際畫出來的高度對得上：
# QSS 的 max-height 會變成 widget 的 maximumHeight（= 本值 + 上下邊框 4px），比實際
# 需要的高度小的話，版面配置會把控制項往下推幾個 px 並讓下緣的框線被父 widget 裁掉
# （實測 24 時 RoutePlanner 的按鈕被排到 y=2、底部 2px 框線消失，文字也跟著偏上）。
# 28 + 邊框 4 = 32px，與 qt-material 在 density_scale=-1 下的實際渲染高度一致。
CONTROL_HEIGHT = 28

# 形狀（高度、圓角、框線粗細）全部統一，但顏色刻意分層：強調色只留給「可按的
# 動作」（QPushButton），輸入類 widget 平時是中性框線，滑過或取得焦點才轉成強調
# 色，這樣一眼就看得出目前游標在哪一格，面板也不會整片都是紅的。
# 文字色同理維持 primaryTextColor 而不是按鈕的 primaryColor：輸入框顯示的是
# 「目前的值」（內容），不是一個動作。
# 四個角要分開寫：qt-material 原規則用 `border-radius: 0` 之後再補上緣兩角，
# 只寫 border-radius 簡寫在某些 Qt 版本不保證覆蓋得乾淨。
# :hover/:focus 與 :disabled 選擇器權重相同，靠「後面的規則勝出」決定優先順序，
# 所以 :disabled 一定要寫在 :hover/:focus 之後。
CONTROL_QSS_TEMPLATE = """
QPushButton,
QComboBox,
QLineEdit,
QAbstractSpinBox {{
  min-height: {height}px;
  max-height: {height}px;
  padding-top: 0px;
  padding-bottom: 0px;
  border: 2px solid {primary};
  border-width: 2px;
  border-top-left-radius: 4px;
  border-top-right-radius: 4px;
  border-bottom-left-radius: 4px;
  border-bottom-right-radius: 4px;
}}
QComboBox,
QLineEdit,
QAbstractSpinBox {{
  background-color: {surface};
  border: 2px solid {muted};
  border-width: 2px;
}}
QComboBox:hover,
QComboBox:focus,
QLineEdit:hover,
QLineEdit:focus,
QAbstractSpinBox:hover,
QAbstractSpinBox:focus {{
  border: 2px solid {primary};
  border-width: 2px;
}}
QPushButton:disabled {{
  border: 2px solid {muted};
  border-width: 2px;
}}
QComboBox:disabled,
QLineEdit:disabled,
QAbstractSpinBox:disabled {{
  border: 2px solid {faint};
  border-width: 2px;
}}
QComboBox QAbstractItemView,
QMenu {{
  background-color: {surface};
  border: 2px solid {muted};
  border-radius: 4px;
}}
/* 以下兩處的 QLineEdit 是「別的 widget 內部的編輯器」，不是獨立的輸入框，
   套上外框與固定高度會擠壞外層，所以把這些屬性放回預設。 */
/* 表格的儲存格編輯器：鎖死高度會讓它撐破所在的列。 */
QTableView QLineEdit {{
  min-height: 0px;
  max-height: 16777215px;
}}
/* QDoubleSpinBox 內部的編輯器（pin_panel 還會換成自訂子類別 _CoordinatePasteLineEdit）：
   會多畫一層框線、多縮排一次 padding-left，數值也會被往下擠而看起來沒有垂直置中。 */
QAbstractSpinBox QLineEdit {{
  border: none;
  min-height: 0px;
  max-height: 16777215px;
  padding-left: 0px;
  background-color: transparent;
}}
"""


def apply(app: QApplication, theme_name: str):
    """套用主題。切換主題時重新呼叫這個函式即可，不需要重建視窗。

    淺色主題要加 invert_secondary=True：qt-material 的 secondaryColor 系列
    預設是深色系（給深色主題的卡片/表面用），淺色主題不反轉的話文字對比
    在亮底上會不足。
    """
    qt_material.apply_stylesheet(
        app,
        theme=THEME_FILES[theme_name],
        invert_secondary=(theme_name == "light"),
        extra={
            "density_scale": "-1",
            "font_family": "Noto Sans TC",
        },
    )
    extra_qss = EXTRA_QSS_TEMPLATE.format(app_title=FS_TITLE, section_title=FS_SECTION_TITLE)
    app.setStyleSheet(app.styleSheet() + extra_qss + _control_qss(theme_name))


def _control_qss(theme_name: str) -> str:
    """產生控制項的外框與高度覆寫規則（見 CONTROL_QSS_TEMPLATE）。

    色票直接跟 qt_material.get_theme() 要目前主題的值，才不會在這裡寫死色碼而
    在切換主題時脫鉤；invert_secondary 要和 apply() 傳給 apply_stylesheet() 的
    值一致，否則淺色主題拿到的會是深色系的 secondary 色。
    """
    colors = qt_material.get_theme(
        THEME_FILES[theme_name], invert_secondary=(theme_name == "light")
    )
    return CONTROL_QSS_TEMPLATE.format(
        height=CONTROL_HEIGHT,
        surface=colors["secondaryDarkColor"],
        primary=colors["primaryColor"],
        muted=colors["secondaryLightColor"],
        faint=_rgba(colors["secondaryLightColor"], 0.4),
    )


def _rgba(hex_color: str, alpha: float) -> str:
    """把 #rrggbb 轉成 Qt QSS 的 rgba()，用來表示「更淡的同一個顏色」。

    停用狀態要比平常的框線更不顯眼，但又不能直接換一個色相，否則深/淺主題
    各要再挑一次顏色；用同色加透明度是 qt-material 自己也在用的做法。
    """
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return "rgba(%d, %d, %d, %.2f)" % (r, g, b, alpha)


# qt-material 的 QComboBox 規則把下拉箭頭畫在文字區右側：
#   QComboBox::drop-down { width: 20px; }
#   QComboBox::down-arrow { margin-right: 8px; }
# 而 QComboBox 本身只有 padding-left，沒有對應的右側 padding，sizeHint() 也沒有
# 把這塊完整計入，所以選項文字一長就會被箭頭壓掉一截。這個數字直接對應上面那
# 兩條 QSS 規則（20 + 8），改動主題樣式表時要一起確認。
COMBO_ARROW_ALLOWANCE = 28


def fit_combo_width(combo):
    """讓下拉選單寬到足以完整顯示最長的選項文字。

    處理兩件事：
    (a) QComboBox 預設的 AdjustToContentsOnFirstShow 只在「第一次顯示」時算一次
        寬度就鎖死，之後即使樣式表重新套用也不會更新——而 MainWindow 在
        _build_ui() 之後還會再呼叫一次 theme.apply()，路徑規劃列又是切到路線模式
        才顯示的，很容易在錯誤的時機把寬度定死。改成 AdjustToContents。
    (b) 補上 (a) 之後 sizeHint() 仍然少算的箭頭區域（見 COMBO_ARROW_ALLOWANCE）。

    和 favorites_panel 的 _fix_to_hint() 同一個道理：必須在 theme.apply() 套用
    樣式表「之後」呼叫，sizeHint() 才會反映正確的 padding。
    """
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    combo.setMinimumWidth(combo.sizeHint().width() + COMBO_ARROW_ALLOWANCE)
    return combo


# qt-material 的 `QListView::item { padding: 4px }` 會把 setItemWidget() 掛上去的
# 列 widget 上下各內縮 4px，實際可用高度比 QListWidgetItem 的 sizeHint 少 8px，
# 列裡的按鈕下緣就會被裁掉。這個數字直接對應那條 QSS 規則，改動主題樣式表時要
# 一起確認（與 COMBO_ARROW_ALLOWANCE 同一個道理）。
LIST_ITEM_PADDING = 4


def fit_list_item(item, row_widget):
    """把 QListWidgetItem 的 sizeHint 設成「列 widget 需要的高度 + item padding」。

    直接用 row_widget.sizeHint() 當 item 的 sizeHint 會少算 QListView::item 的
    padding，列 widget 拿到的高度不夠，裡面的按鈕下緣會被裁掉（實測列需要 36px
    時只拿到 28px）。寬度不用補：列會跟著清單寬度伸展。
    """
    hint = row_widget.sizeHint()
    item.setSizeHint(QSize(hint.width(), hint.height() + LIST_ITEM_PADDING * 2))
    return item


def style_section_title(label):
    """把一個 QLabel 標記成區塊標題外觀：比一般內文字級大、加粗。"""
    mark_class(label, "section-title")
    return label


def mark_class(widget, class_name):
    """把 widget 標記成 qt-material 的語意樣式類別（"danger"/"warning"/"success"）。

    對應 qt-material 的 QPushButton.danger / .success 這類 QSS 規則：靠 Qt 的
    動態屬性 "class" 選取，設定後要 unpolish()/polish() 讓樣式重新計算一次。
    """
    widget.setProperty("class", class_name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget
