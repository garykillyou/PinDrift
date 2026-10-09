"""SettingsDialog：網址檢查決定按鈕狀態，測試傳送用的是輸入框裡的網址。"""

import pytest

from gps_qt import notifier
from gps_qt.widgets.settings_dialog import TEST_MESSAGE, SettingsDialog

VALID_URL = "https://discord.com/api/webhooks/1/token"


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def send(self, url, message, on_done):
        self.calls.append((url, message, on_done))
        return True


@pytest.fixture
def fake_notifier():
    return FakeNotifier()


@pytest.fixture
def dialog(qapp, fake_notifier):
    return SettingsDialog("", fake_notifier)


def test_empty_url_allows_ok_but_not_test(dialog):
    assert dialog._ok_btn.isEnabled()
    assert not dialog.test_btn.isEnabled()
    assert dialog.webhook_url() == ""


def test_invalid_url_blocks_ok_and_shows_reason(dialog):
    # Act
    dialog.url_edit.setText("https://example.com/hook")

    # Assert
    assert not dialog._ok_btn.isEnabled()
    assert not dialog.test_btn.isEnabled()
    assert dialog.status_label.text() == notifier.INVALID_URL_MESSAGE


def test_valid_url_is_stripped_and_enables_both_buttons(dialog):
    # Act
    dialog.url_edit.setText("  " + VALID_URL + "\n")

    # Assert
    assert dialog.webhook_url() == VALID_URL
    assert dialog._ok_btn.isEnabled()
    assert dialog.test_btn.isEnabled()


def test_test_button_sends_current_text_and_disables_until_done(dialog, fake_notifier):
    # Arrange
    dialog.url_edit.setText(VALID_URL)

    # Act
    dialog.test_btn.click()

    # Assert：傳送中不能連按
    url, message, on_done = fake_notifier.calls[0]
    assert (url, message) == (VALID_URL, TEST_MESSAGE)
    assert not dialog.test_btn.isEnabled()
    assert dialog.url_edit.isReadOnly()

    # Act：回應回來
    on_done(False, "連線逾時")

    # Assert
    assert dialog.test_btn.isEnabled()
    assert not dialog.url_edit.isReadOnly()
    assert dialog.status_label.text() == "測試失敗：連線逾時"
