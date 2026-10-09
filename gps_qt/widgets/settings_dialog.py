"""設定對話框：目前只有 Discord 通知的 webhook 網址。"""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)
from shiboken6 import isValid

from .. import notifier

DIALOG_MIN_WIDTH = 520
TEST_MESSAGE = "測試通知，看到這則訊息代表設定成功"
HELP_TEXT = (
    "抵達端點（沒開循環模式）時，除了系統匣通知，也會把訊息送到 Discord 頻道，"
    "手機上的 Discord App 就會推播。\n"
    "取得網址：Discord 頻道 →「編輯頻道」→「整合」→「Webhook」→「新 Webhook」→"
    "「複製 Webhook 網址」。留空代表不通知。\n"
    "網址等同密碼，拿到的人都能往該頻道發訊息，請不要分享。"
)


class SettingsDialog(QDialog):
    def __init__(self, webhook_url, discord_notifier, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self._notifier = discord_notifier
        form = QFormLayout(self)

        help_label = QLabel(HELP_TEXT)
        help_label.setWordWrap(True)
        form.addRow(help_label)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit(webhook_url)
        # 平時遮住（網址是憑證，不該在畫面上被旁人看到），編輯時才顯示原文方便確認貼上的內容。
        self.url_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.url_edit.setPlaceholderText("https://discord.com/api/webhooks/...")
        url_row.addWidget(self.url_edit, 1)
        self.test_btn = QPushButton("測試傳送")
        self.test_btn.clicked.connect(self._send_test)
        url_row.addWidget(self.test_btn)
        form.addRow("Discord Webhook：", url_row)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        form.addRow(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.Ok)
        form.addRow(buttons)

        self._testing = False
        self.url_edit.textChanged.connect(self._sync_state)
        self._sync_state()

    def webhook_url(self):
        """目前輸入的網址（去掉前後空白）；空字串代表不通知。"""
        return self.url_edit.text().strip()

    def _sync_state(self, *_args):
        url = self.webhook_url()
        valid = notifier.is_valid_webhook_url(url)
        self._ok_btn.setEnabled(not url or valid)
        self.test_btn.setEnabled(valid and not self._testing)
        if url and not valid:
            self.status_label.setText(notifier.INVALID_URL_MESSAGE)
        elif not self._testing:
            self.status_label.clear()

    def _send_test(self):
        # 用輸入框裡的網址測，不必先按確定存檔；測試期間停用按鈕，連按也不會被 Discord 限流。
        # 輸入框同時設成唯讀：否則回應回來時畫面上可能已經換成另一個網址，結果就對不上了。
        self._testing = True
        self.url_edit.setReadOnly(True)
        self.status_label.setText("傳送中...")
        self._sync_state()
        self._notifier.send(self.webhook_url(), TEST_MESSAGE, self._on_test_done)

    def _on_test_done(self, ok, detail):
        # 回應到的時候對話框可能已經關閉並被刪除。
        if not isValid(self):
            return
        self._testing = False
        self.url_edit.setReadOnly(False)
        self._sync_state()
        self.status_label.setText("測試成功，請到 Discord 確認" if ok else "測試失敗：" + detail)
