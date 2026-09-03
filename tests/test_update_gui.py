from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.gui.about_page import AboutPage


def test_update_card_state_and_action() -> None:
    app = QApplication.instance() or QApplication([])
    invoked: list[bool] = []
    page = AboutPage(QIcon(), lambda: invoked.append(True))

    page.set_update_state("available", "1.2.3")
    assert "1.2.3" in page.update_card.button.text()
    assert page.update_card.button.isEnabled()

    page.update_card.clicked.emit()
    assert invoked == [True]

    page.set_update_state("downloading", "1.2.3")
    page.set_update_progress(50, 100)
    assert "50%" in page.update_card.contentLabel.text()
    assert not page.update_card.button.isEnabled()

    page.deleteLater()
    app.processEvents()
