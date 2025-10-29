from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PyQt6.QtWidgets import QLabel
from typing import Optional
import os


class ImageDropLabel(QLabel):
    """接受图片拖放并显示预览的 QLabel。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("拖放图片到此处或点击上传")
        self.setStyleSheet("border: 2px dashed #aaa; padding: 10px;")
        self.setAcceptDrops(True)
        self.filepath = None

    def dragEnterEvent(self,a0: Optional[QDragEnterEvent]) -> None:
        if a0 is None:
            return
        md = a0.mimeData()
        if md is not None and md.hasUrls():
            a0.acceptProposedAction()

    def dropEvent(self, a0: Optional[QDropEvent]) -> None:
        if a0 is None:
            return
        md = a0.mimeData()
        if md is None:
            return
        urls = md.urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if os.path.isfile(path):
            self.set_image(path)

    def set_image(self, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            self.setText("无法打开该图片")
            self.filepath = None
            return
        self.filepath = path
        self.setPixmap(pix.scaled(320, 240, Qt.AspectRatioMode.KeepAspectRatio))
