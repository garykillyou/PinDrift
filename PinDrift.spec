# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包設定：產生 dist/PinDrift/ 這一個可以整包搬走的資料夾。

刻意用 onedir（資料夾）而不是 onefile（單一檔案）：QtWebEngine 的
`QtWebEngineProcess.exe` 是獨立的子行程，還要找得到 ICU 資料與 locales，
onefile 每次啟動都解壓到暫存目錄，既慢又常出現子行程找不到資源的問題。

資料夾裡會有兩個執行檔，共用同一個 `_internal`：
- `PinDrift.exe`         主程式（視窗模式，一般權限）
- `PinDrift-tunneld.exe` tunneld（主控台模式，由主程式提權啟動）
"""

import os
import shutil

from PyInstaller.utils.hooks import collect_all

APP_NAME = "PinDrift"
TUNNELD_NAME = "PinDrift-tunneld"

# pymobiledevice3 大量使用動態 import（各個 service 模組、construct 型別），
# 靜態分析抓不全，用 collect_all 整包收進來。
pmd3_datas, pmd3_binaries, pmd3_hiddenimports = collect_all("pymobiledevice3")
# wintun.dll 放在 pytun_pmd3 的套件目錄裡（建立 tunnel 介面用），而 pytun_pmd3 是
# 另一個發行套件，不會被上面那行一起收進來；少了它 tunneld 一啟動就 FileNotFoundError。
pytun_datas, pytun_binaries, pytun_hiddenimports = collect_all("pytun_pmd3")
# qt-material 的主題色票是套件目錄裡的 .xml 與 .css.template，屬於資料檔。
qtm_datas, qtm_binaries, qtm_hiddenimports = collect_all("qt_material")

# Qt 的 OpenSSL backend 在 Windows 上只認 libssl-3-x64.dll／libcrypto-3-x64.dll 這組檔名，
# PySide6 本身不附；_internal 裡 Python 的 libssl-3.dll 檔名不同，Qt 不會用它。
# 找不到時 Qt 會默默退回 Windows 的 SChannel，而 SChannel 在部分電腦上連
# Valhalla／Nominatim 會握手失敗（"Unexpected or badly-formatted message received"）；
# 開發機通常剛好因為 PATH 上有 Git for Windows 的那份而走 OpenSSL，所以只有別台電腦會壞。
# 來源優先用 PINDRIFT_OPENSSL_DIR，沒設才從 PATH 找，再找不到就用 Git for Windows
# 附的那份；都沒有就讓打包失敗，
# 不要產出一份會退回 SChannel 的版本。
OPENSSL_DLLS = ("libssl-3-x64.dll", "libcrypto-3-x64.dll")
OPENSSL_DIR_ENV = "PINDRIFT_OPENSSL_DIR"


def _find_openssl_dll(name):
    """回傳要打包的 OpenSSL DLL 路徑，找不到就中止打包。"""
    custom_dir = os.environ.get(OPENSSL_DIR_ENV)
    if custom_dir:
        path = os.path.join(custom_dir, name)
        if not os.path.isfile(path):
            raise SystemExit(f"{OPENSSL_DIR_ENV}={custom_dir} 裡找不到 {name}")
        return path

    path = shutil.which(name)
    git = shutil.which("git")
    if path is None and git is not None:
        # Git for Windows 預設只把 <Git>\cmd 加進 PATH，DLL 在旁邊的 mingw64\bin；
        # 在 Git Bash 裡找到的則是 <Git>\mingw64\bin\git.exe 本身，兩種位置都要看。
        git_dir = os.path.dirname(git)
        candidates = (
            os.path.join(git_dir, name),
            os.path.join(os.path.dirname(git_dir), "mingw64", "bin", name),
        )
        path = next((c for c in candidates if os.path.isfile(c)), None)
    if path is None:
        raise SystemExit(
            f"找不到 {name}：請把 OpenSSL 3 (x64) 的 DLL 所在資料夾設成環境變數 "
            f"{OPENSSL_DIR_ENV}，或加進 PATH（Git for Windows 的 mingw64\\bin 也有這組檔案）"
        )
    return path


# 放在 _internal 根目錄：bootloader 會把它設成 DLL 搜尋路徑，Qt 的 LoadLibrary 找得到。
OPENSSL_BINARIES = [(_find_openssl_dll(name), ".") for name in OPENSSL_DLLS]
for src, _ in OPENSSL_BINARIES:
    print(f"[PinDrift] bundling OpenSSL for Qt: {src}")

# 地圖頁面與 vendored 的 Leaflet：非 .py 檔，PyInstaller 不會自己帶。
# 目的地要與 gps_qt/paths.py 的 resource_path() 對應（_internal/gps_qt/web/...）。
WEB_DATA = [("gps_qt/web", "gps_qt/web")]

# 用不到的 Qt 模組與標準函式庫，排掉可省下可觀的體積。
# 注意：QtQml / QtQuick / QtPositioning / QtWebChannel / QtNetwork / QtOpenGL
# 是 QtWebEngine 的相依，排掉地圖會壞；QtUiTools 則是 qt_material 匯入的
# （實測排掉會在 import qt_material 時直接 ModuleNotFoundError）。都不要加進這份清單。
# pymobiledevice3 的 CLI 子命令是用 importlib 依名稱延遲載入的（見其 __main__.py 的
# Pmd3TyperGroup.import_and_get_command），而我們只會用到 `remote tunneld` 與
# DVT 的 LocationSimulation，所以螢幕錄影／截圖／互動式 shell 那幾條路上的重量級
# 相依可以整包排掉（av + numpy + PIL + IPython/jedi 合計約 125 MB）。
# 排不得的兩個：pygments（remotexpc.py／service_connection.py 會用到）與
# prompt_toolkit（cli_common.py 匯入的 questionary 依賴它，實測排掉會直接無法啟動）。
EXCLUDED_MODULES = [
    "tkinter",
    "pydoc_data",
    "av",
    "numpy",
    "PIL",
    "IPython",
    "jedi",
    "parso",
    "matplotlib",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtQuick3D",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
]

app_analysis = Analysis(
    ["app_entry.py"],
    pathex=[],
    binaries=pmd3_binaries + pytun_binaries + qtm_binaries + OPENSSL_BINARIES,
    datas=WEB_DATA + pmd3_datas + pytun_datas + qtm_datas,
    hiddenimports=pmd3_hiddenimports + pytun_hiddenimports + qtm_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
)

# tunneld 完全不碰 Qt，額外把 PySide6 排掉，避免分析時又拉進一份。
tunneld_analysis = Analysis(
    ["tunneld_entry.py"],
    pathex=[],
    binaries=pmd3_binaries + pytun_binaries,
    datas=pmd3_datas + pytun_datas,
    hiddenimports=pmd3_hiddenimports + pytun_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES + ["PySide6", "shiboken6", "qasync", "qt_material"],
    noarchive=False,
)

# Qt 隨附的翻譯與 WebEngine 資源佔掉超過 130 MB，其中大部分用不到：
# .debug.pak 是除錯用的副本，53 種 WebEngine 語系與 157 個 Qt .qm 也只需要
# 介面實際會用到的那幾個。
KEEP_WEBENGINE_LOCALES = {"en-US", "zh-TW"}
KEEP_QT_TRANSLATION_SUFFIXES = ("_zh_TW", "_en")


def _is_unused_qt_data(dest):
    """判斷這個資料檔是不是用不到的 Qt 翻譯／除錯資源。"""
    path = dest.replace("\\", "/")
    name = os.path.basename(path)

    if name.endswith(".debug.pak"):
        return True
    if "/translations/qtwebengine_locales/" in path:
        return os.path.splitext(name)[0] not in KEEP_WEBENGINE_LOCALES
    if "/translations/" in path and name.endswith(".qm"):
        stem = os.path.splitext(name)[0]
        return not stem.endswith(KEEP_QT_TRANSLATION_SUFFIXES)
    return False


app_analysis.datas = [entry for entry in app_analysis.datas if not _is_unused_qt_data(entry[0])]

app_pyz = PYZ(app_analysis.pure)
tunneld_pyz = PYZ(tunneld_analysis.pure)

app_exe = EXE(
    app_pyz,
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 壓縮過的 Qt DLL 常常載入失敗，一律關掉。
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

tunneld_exe = EXE(
    tunneld_pyz,
    tunneld_analysis.scripts,
    [],
    exclude_binaries=True,
    name=TUNNELD_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    app_exe,
    app_analysis.binaries,
    app_analysis.datas,
    tunneld_exe,
    tunneld_analysis.binaries,
    tunneld_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
