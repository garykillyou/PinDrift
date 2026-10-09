"""記住使用者拖曳過的 QSplitter 大小，下次開啟時套回去。

從 MainWindow 抽出來的原因跟 CloseGuard 一樣：MainWindow 需要 QtWebEngine 而沒有自動化測試，
這裡只相依 QSplitter，可以用 offscreen 平台單獨測。
"""

# 兩個相同的大數字：QSplitter.setSizes() 會依可用空間等比例換算，等於對半分。
EQUAL_SIZES = [10**6, 10**6]


class SplitterMemory:
    """sizes：persistence.load_splitter_sizes() 檢查過的 {key: [a, b]}，會複製一份不改動原物件。
    on_changed：使用者拖曳後呼叫（不帶參數），MainWindow 用來排程自動存檔。"""

    def __init__(self, sizes, on_changed):
        self._sizes = _copy_sizes(sizes)
        self._on_changed = on_changed

    @property
    def sizes(self):
        """目前記下的大小（新的 dict），寫回設定檔用。"""
        return _copy_sizes(self._sizes)

    def restore(self, splitter, key, default=EQUAL_SIZES):
        """套用 key 記下的大小；沒記過就用 default。存的是像素值，Qt 會依目前空間等比例換算。"""
        splitter.setSizes(self._sizes.get(key, default))

    def watch(self, splitter, key_provider):
        """使用者拖曳 splitter 後記下大小。key_provider 在拖曳當下才呼叫：
        主分隔線會依視窗寬度換方向，兩個方向要記在不同的 key。

        只接 splitterMoved：它只在使用者拖曳時發出，restore() 的 setSizes() 不會觸發，
        套用存檔的值時不會反過來蓋掉存檔。"""
        splitter.splitterMoved.connect(lambda *_: self._record(splitter, key_provider()))

    def _record(self, splitter, key):
        self._sizes = {**self._sizes, key: splitter.sizes()}
        self._on_changed()


def _copy_sizes(sizes):
    return {key: list(value) for key, value in sizes.items()}
