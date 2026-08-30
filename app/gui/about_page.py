from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ElevatedCardWidget,
    FluentIcon,
    HyperlinkCard,
    SettingCard,
    SettingCardGroup,
    SmoothScrollArea,
    TitleLabel,
)

from app.const import APP_NAME, REPOSITORY_ACTIONS_URL, REPOSITORY_URL
from app.version import get_app_version, get_commit_hash

from .i18n import tr


class AboutPage(SmoothScrollArea):
    def __init__(self, icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AboutPage")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea#AboutPage { border: none; background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

        content = QWidget(self)
        content.setObjectName("AboutPageContent")
        content.setStyleSheet("QWidget#AboutPageContent { background: transparent; }")
        self.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 32, 36, 36)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._build_header(icon))
        layout.addWidget(self._build_application_group())
        layout.addStretch()

    @staticmethod
    def _fixed_font() -> QFont:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(10)
        return font

    def _build_header(self, icon: QIcon) -> QWidget:
        card = ElevatedCardWidget(self)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(20)

        icon_label = QLabel(card)
        icon_label.setFixedSize(72, 72)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(icon.pixmap(64, 64))
        layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)
        text_layout.addWidget(TitleLabel(APP_NAME, card))
        text_layout.addWidget(BodyLabel(tr("about.description"), card))

        build_label = CaptionLabel(tr("about.build", version=get_app_version()), card)
        build_label.setFont(self._fixed_font())
        text_layout.addWidget(build_label)
        text_layout.addStretch()

        layout.addLayout(text_layout, stretch=1)
        return card

    def _build_application_group(self) -> SettingCardGroup:
        group = SettingCardGroup(tr("about.section.application"), self)
        commit_hash = get_commit_hash()

        if commit_hash:
            commit_card = HyperlinkCard(
                f"{REPOSITORY_URL}/commit/{commit_hash}",
                tr("about.open"),
                FluentIcon.CODE,
                tr("about.commit"),
                commit_hash,
                group,
            )
            commit_card.contentLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            commit_card.contentLabel.setToolTip(commit_hash)
            commit_card.contentLabel.setFont(self._fixed_font())
        else:
            commit_card = SettingCard(
                FluentIcon.CODE,
                tr("about.commit"),
                tr("about.commit.unknown"),
                group,
            )

        repository_card = HyperlinkCard(
            REPOSITORY_URL,
            tr("about.open"),
            FluentIcon.GITHUB,
            tr("about.repository"),
            tr("about.repository.description"),
            group,
        )
        actions_card = HyperlinkCard(
            REPOSITORY_ACTIONS_URL,
            tr("about.open"),
            FluentIcon.CLOUD_DOWNLOAD,
            tr("about.actions"),
            tr("about.actions.description"),
            group,
        )
        license_card = SettingCard(
            FluentIcon.CERTIFICATE,
            tr("about.license"),
            tr("about.license.description"),
            group,
        )

        group.addSettingCards([commit_card, repository_card, actions_card, license_card])
        return group
