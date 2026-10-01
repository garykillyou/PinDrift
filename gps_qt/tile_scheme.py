"""`pdtile:` scheme 的處理器：地圖頁面要圖磚時，先查本機快取，沒有才連線下載。

快取的檔案格式、路徑與新鮮度規則都在 tile_cache.py（純函式）；這裡只負責跟
QtWebEngine 與 QNetworkAccessManager 打交道。

由 Python 代為下載還有一個好處：請求帶的是 netclient.USER_AGENT，符合 OSM 圖磚
政策「要能識別應用程式」的要求（QtWebEngine 裡的請求帶的是瀏覽器 UA）。
"""

import logging
import threading
import time

import shiboken6
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWebEngineCore import (
    QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler,
)

from . import tile_cache
from .netclient import USER_AGENT

logger = logging.getLogger(__name__)

HTTP_OK = 200
DOWNLOAD_TIMEOUT_MS = 10_000


def register_scheme():
    """登記 `pdtile:` scheme。**必須在建立 QApplication 之前呼叫**，晚了 Qt 會忽略。

    Syntax.Path：整串 `https://...` 都當成路徑，不另外解析主機名稱。
    SecureScheme：當成安全來源，頁面載入它不會被當成混合內容擋下。
    """
    scheme = QWebEngineUrlScheme(tile_cache.TILE_SCHEME.encode("ascii"))
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Path)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.CorsEnabled
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def install(profile, parent):
    """在 profile 上裝好處理器，並在背景執行緒清掉超過容量上限的舊快取。

    處理器以 parent 為父物件；它被銷毀時 Qt 會自動從 profile 上移除。
    """
    handler = TileSchemeHandler(tile_cache.TILE_CACHE_DIR, parent)
    profile.installUrlSchemeHandler(tile_cache.TILE_SCHEME.encode("ascii"), handler)
    # 快取有十幾萬個檔案時走訪一次要一兩秒，不能卡在 UI 執行緒上。
    threading.Thread(target=tile_cache.prune_cache_logged, daemon=True).start()
    return handler


class _PendingFetch:
    """同一個上游網址正在進行的下載，以及等著這張圖磚的所有 job。"""

    def __init__(self, reply, cached):
        self.reply = reply
        self.cached = cached
        self.waiters = []  # 每個 waiter 是 {"job": job, "alive": bool}

    def has_live_waiter(self):
        return any(waiter["alive"] for waiter in self.waiters)


class TileSchemeHandler(QWebEngineUrlSchemeHandler):
    """快取優先：新鮮的快取直接回；過期或沒有才下載，下載失敗時退回過期的快取。"""

    def __init__(self, cache_dir, parent=None):
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._manager = QNetworkAccessManager(self)
        self._pending = {}  # 上游網址 -> _PendingFetch
        self._write_error_logged = False

    def requestStarted(self, job):
        upstream = tile_cache.upstream_url(job.requestUrl().toString())
        if upstream is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
            return
        path = tile_cache.cache_file_path(self._cache_dir, upstream)
        cached = tile_cache.read_cached(path)
        if cached is not None and tile_cache.is_fresh(cached[1], time.time()):
            _reply(job, cached[0])
            return
        self._fetch(job, upstream, path, cached)

    def _fetch(self, job, upstream, path, cached):
        # 縮放動畫等情況會讓同一張圖磚被同時要多次：合併成一次下載，
        # 否則各自下載、各自寫同一個 .tmp 檔，彼此的 os.replace() 會打架。
        pending = self._pending.get(upstream)
        if pending is None:
            pending = self._start_download(upstream, path, cached)
        waiter = {"job": job, "alive": True}
        pending.waiters.append(waiter)
        # 使用者快速平移時 Leaflet 會取消還沒載完的圖磚，job 隨之被銷毀；
        # 所有等待者都不在了才中止下載，不為看不到的圖磚繼續佔用連線。
        # abort() 會同步觸發 finished，那時 waiter 已標成不在，不會碰到已銷毀的 job。
        job.destroyed.connect(lambda: self._on_job_destroyed(pending, waiter))

    def _start_download(self, upstream, path, cached):
        request = QNetworkRequest(QUrl(upstream))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        # 網路半斷時不要讓圖磚一直轉圈，逾時後會退回過期的快取。
        request.setTransferTimeout(DOWNLOAD_TIMEOUT_MS)
        reply = self._manager.get(request)
        pending = _PendingFetch(reply, cached)
        self._pending[upstream] = pending
        reply.finished.connect(lambda: self._on_fetched(upstream, path, pending))
        return pending

    @staticmethod
    def _on_job_destroyed(pending, waiter):
        waiter["alive"] = False
        if not pending.has_live_waiter():
            _abort_if_alive(pending.reply)

    def _on_fetched(self, upstream, path, pending):
        self._pending.pop(upstream, None)
        reply = pending.reply
        data = bytes(reply.readAll().data())
        ok = (
            reply.error() == QNetworkReply.NetworkError.NoError
            and reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) == HTTP_OK
            and tile_cache.is_image(data)
        )
        reply.deleteLater()
        if ok:
            self._store(path, data)
        for waiter in pending.waiters:
            job = waiter["job"]
            if waiter["alive"] and shiboken6.isValid(job):
                self._finish_job(job, ok, data, pending.cached)

    @staticmethod
    def _finish_job(job, ok, data, cached):
        if ok:
            _reply(job, data)
        elif cached is not None:
            _reply(job, cached[0])  # 離線或伺服器出錯時，過期的圖磚總比空白好
        else:
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)

    def _store(self, path, data):
        error = tile_cache.write_cached(path, data)
        # 放在唯讀位置時每張圖磚都會失敗，只記一次，不洗版記錄檔。
        if error and not self._write_error_logged:
            self._write_error_logged = True
            logger.warning(error)


def _reply(job, data):
    # QBuffer 以 job 為父物件：Qt 在 job 結束前都會從它讀資料，結束時一起釋放。
    buffer = QBuffer(job)
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    job.reply(QByteArray(tile_cache.content_type_of(data).encode("ascii")), buffer)


def _abort_if_alive(reply):
    if shiboken6.isValid(reply) and reply.isRunning():
        reply.abort()
