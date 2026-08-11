"""ClipClipper Studio — desktop GUI for finding viral YouTube clips.

Run with:  python -m studio_app   (or:  clipclipper-gui)
"""
import os
import sys


def _apply_env_from_settings() -> None:
    """Apply persisted .env values to the process env BEFORE shorts_generator is
    first imported (its config module reads env at import time)."""
    from studio_app.settings_panel import load_env_file

    try:
        for key, value in load_env_file().items():
            os.environ.setdefault(key, value)
    except Exception:  # noqa: BLE001 — a broken .env must not block the GUI
        pass


def main() -> int:
    _apply_env_from_settings()

    from PySide6.QtWidgets import QApplication, QMessageBox

    try:
        import shorts_generator  # noqa: F401  (fail fast with a friendly dialog)
    except Exception as e:  # noqa: BLE001
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "Missing dependencies",
            "ClipClipper could not start:\n\n"
            f"{e}\n\n"
            "Install the required packages first:\n"
            "  pip install -r requirements.txt\n"
            "  pip install PySide6",
        )
        return 1

    from studio_app.main_window import MainWindow
    from studio_app.theme import QSS

    app = QApplication(sys.argv)
    app.setApplicationName("ClipClipper Studio")
    app.setStyleSheet(QSS)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
