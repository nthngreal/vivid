"""Window: one card per monitor with a slider, Save and Reset."""
import os
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)

from . import core, desktop
from .i18n import LANGS, STRINGS


class MonitorCard(QFrame):
    def __init__(self, win, out):
        super().__init__()
        self.win, self.out = win, out
        self.setFrameShape(QFrame.StyledPanel)
        lay = QGridLayout(self)

        self.title = QLabel(f"<b>{out.label}</b>")
        self.hint = QLabel(out.name)        # connector, small, to tell identical monitors apart
        self.hint.setEnabled(False)
        self.hint.setVisible(out.label != out.name)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, core.MAX_PCT)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(10)
        self.slider.setPageStep(5)
        self.slider.setValue(out.pct)
        self.value = QLabel()
        self.value.setMinimumWidth(48)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.state = QLabel()
        self.save_btn = QPushButton(QIcon.fromTheme("document-save"), "")
        self.reset_btn = QPushButton(QIcon.fromTheme("edit-undo"), "")

        lay.addWidget(self.title, 0, 0)
        lay.addWidget(self.hint, 0, 1, 1, 2, Qt.AlignRight)
        lay.addWidget(self.slider, 1, 0, 1, 2)
        lay.addWidget(self.value, 1, 2)
        btns = QHBoxLayout()
        btns.addWidget(self.state)
        btns.addStretch()
        btns.addWidget(self.reset_btn)
        btns.addWidget(self.save_btn)
        lay.addLayout(btns, 2, 0, 1, 3)
        lay.setColumnStretch(0, 1)

        self.slider.valueChanged.connect(self.refresh)
        self.save_btn.clicked.connect(self.save)
        self.reset_btn.clicked.connect(self.reset)

    def tr_(self, key, **kw):
        return self.win.tr_(key, **kw)

    def refresh(self):
        v = self.slider.value()
        self.value.setText(f"{v}%")
        self.save_btn.setText(self.tr_("save"))
        self.reset_btn.setText(self.tr_("reset"))
        dirty = v != self.out.pct
        self.save_btn.setEnabled(dirty)
        self.reset_btn.setEnabled(self.out.pct > 0 or v > 0)
        self.state.setText(self.tr_("unsaved") if dirty else self.tr_("saved", pct=self.out.pct))

    def _apply(self, pct, msg_key):
        try:
            core.apply(self.out.name, pct)
        except core.VibranceError as e:
            self.win.show_error(e)
            return
        self.out.pct = pct
        self.refresh()
        self.win.status.setText(self.tr_(msg_key, label=self.out.label, pct=pct))

    def save(self):
        self._apply(self.slider.value(), "applied")

    def reset(self):
        self.slider.setValue(0)
        self._apply(0, "reset_done")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("vivid", "vivid")
        self.lang = self.settings.value("lang") or "en"
        if self.lang not in LANGS:
            self.lang = "en"
        self.setWindowIcon(QIcon(desktop.ICON))
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.heading = QLabel()
        self.lang_label = QLabel()
        self.lang_box = QComboBox()
        for code, name in LANGS.items():
            self.lang_box.addItem(name, code)
        self.lang_box.setCurrentIndex(list(LANGS).index(self.lang))
        self.lang_box.currentIndexChanged.connect(self.set_lang)
        top.addWidget(self.heading)
        top.addStretch()
        top.addWidget(self.lang_label)
        top.addWidget(self.lang_box)
        lay.addLayout(top)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.cards_box = QVBoxLayout()
        lay.addLayout(self.cards_box)
        self.empty = QLabel()
        lay.addWidget(self.empty)

        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.refresh_btn = QPushButton(QIcon.fromTheme("view-refresh"), "")
        self.refresh_btn.clicked.connect(self.load)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.refresh_btn)
        lay.addLayout(bottom)
        self.about = QLabel()
        self.about.setEnabled(False)
        lay.addWidget(self.about)

        self.cards = []
        self.retranslate()
        self.load()

    def tr_(self, key, **kw):
        return STRINGS[self.lang][key].format(**kw)

    def set_lang(self, i):
        self.lang = self.lang_box.itemData(i)
        self.settings.setValue("lang", self.lang)
        self.retranslate()

    def retranslate(self):
        self.setWindowTitle("Vivid")
        self.heading.setText(f"<h3>{self.tr_('title')}</h3>")
        self.lang_label.setText(self.tr_("language"))
        self.hint.setText(self.tr_("hint"))
        self.empty.setText(self.tr_("no_outputs"))
        self.refresh_btn.setText(self.tr_("refresh"))
        self.about.setText(f"<small>{self.tr_('about')}</small>")
        self.status.clear()
        for c in self.cards:
            c.refresh()

    def load(self):
        for c in self.cards:
            c.setParent(None)
        self.cards = []
        try:
            core.check_session()
            outputs = core.list_outputs()
        except core.VibranceError as e:
            self.show_error(e)
            outputs = []
        for out in outputs:
            card = MonitorCard(self, out)
            card.refresh()
            self.cards_box.addWidget(card)
            self.cards.append(card)
        self.empty.setVisible(not self.cards)
        self.adjustSize()

    def show_error(self, e):
        text = self.tr_(e.key) if e.key in STRINGS[self.lang] else str(e)
        if e.detail:
            text += f"\n\n{e.detail}"
        QMessageBox.warning(self, self.tr_("error"), text)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("vivid")
    app.setDesktopFileName("vivid")
    # A bundled Qt (AppImage) does not know the Plasma icon theme on its own.
    if not QIcon.themeName() or QIcon.themeName() == "hicolor":
        for theme in ("breeze", "breeze-dark", "Adwaita"):
            if os.path.isdir(f"/usr/share/icons/{theme}"):
                QIcon.setThemeName(theme)
                break
    desktop.install_menu_entry()
    w = MainWindow()
    w.show()
    return app.exec()
