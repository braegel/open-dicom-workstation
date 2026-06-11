"""Application entry point: Qt application, translator and main window."""

import sys
from pathlib import Path

from PySide6.QtCore import QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from odw.core.config import load_config
from odw.ui.main_window import MainWindow

_I18N_DIR = Path(__file__).resolve().parent / "ui" / "i18n"


def install_translator(app: QApplication, locale: QLocale | None = None) -> bool:
    """Install the German translation if *locale* is German and a .qm file ships.

    Returns False (without raising) when no compiled .qm exists — the MVP
    ships only the .ts source.
    """
    if locale is None:
        locale = QLocale()
    if locale.language() != QLocale.Language.German:
        return False
    translator = QTranslator(app)
    if not translator.load("odw_de", str(_I18N_DIR)):
        return False
    return app.installTranslator(translator)


def main() -> int:
    app = QApplication(sys.argv)
    install_translator(app)
    config = load_config()
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
