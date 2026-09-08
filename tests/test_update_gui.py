import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.gui.about_page import AboutPage


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
