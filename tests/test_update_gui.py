import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.gui.about_page import AboutPage
from app.gui.main_window import MainWindow


def test_update_card_state_and_action() -> None:
    app = QApplication.instance() or QApplication([])
    invoked: list[bool] = []
    page = AboutPage(QIcon(), lambda: invoked.append(True))
    assert page.update_progress_bar.isHidden()
    assert page.release_notes_card.isHidden()

    page.set_update_state("available", "1.2.3", "## Highlights\n\n- Faster updates")
    assert "1.2.3" in page.update_card.button.text()
    assert page.update_card.button.isEnabled()
    assert not page.release_notes_card.isHidden()
    assert "1.2.3" in page.release_notes_title.text()
    assert "Highlights" in page.release_notes_browser.toPlainText()
    assert "Faster updates" in page.release_notes_browser.toPlainText()

    page.update_card.clicked.emit()
    assert invoked == [True]

    page.set_update_state("downloading", "1.2.3", "## Highlights\n\n- Faster updates")
    assert not page.update_progress_bar.isHidden()
    assert page.update_progress_bar.value() == 0
    page.set_update_progress(50, 100)
    assert "50%" in page.update_card.contentLabel.text()
    assert page.update_progress_bar.value() == 50
    assert not page.update_card.button.isEnabled()

    page.set_update_state("ready", "1.2.3", "## Highlights\n\n- Faster updates")
    assert page.update_progress_bar.isHidden()
    assert not page.release_notes_card.isHidden()

    page.set_update_state("current")
    assert page.release_notes_card.isHidden()

    page.deleteLater()
    app.processEvents()


# qfluentwidgets/components/navigation/navigation_widget.py:366 `.contains(e.pos())`
# DeprecationWarning: Function: 'QMouseEvent.pos() const' is marked as deprecated
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_about_page_initializes_with_latest_update_state() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        QIcon(),
        on_start=lambda: None,
        on_stop=lambda: None,
        on_save=lambda: None,
        on_update=lambda: None,
        on_exit=lambda: None,
    )
    try:
        assert window._about_content is None
        window.set_update_state("downloading", "1.2.3", "## Changes")
        window.set_update_progress(25, 100)
        window.show_main_window()
        app.processEvents()
        navigation_item = window.navigationInterface.widget("AboutPage")
        assert navigation_item is not None
        QTest.mouseClick(navigation_item.itemWidget, Qt.MouseButton.LeftButton)
        app.processEvents()
        page = window._about_content
        assert page is not None
        assert window.stackedWidget.currentWidget() is window.about_page
        assert page.update_progress_bar.value() == 25
        assert "25%" in page.update_card.contentLabel.text()

        window.set_update_state("ready", "1.2.3", "## Changes")
        assert page.update_progress_bar.isHidden()
        assert "Changes" in page.release_notes_browser.toPlainText()
        window.goto_config_page()
        window.switchTo(window.about_page)
        assert window._about_content is page
    finally:
        window.deleteLater()
        app.processEvents()
