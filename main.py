import sys


def main() -> None:
    """
    Compatibility entrypoint.

    The project refactor moved the real implementation to `nas_checker/scan/main.py`.
    This wrapper keeps `python main.py --gui` working for local runs.
    """

    from nas_checker.scan.main import run_scan

    if "--gui" in sys.argv:
        from PySide6.QtWidgets import QApplication
        from nas_checker.gui.gui import MainWindow

        app = QApplication(sys.argv)
        window = MainWindow()
        window.resize(800, 600)
        window.show()
        sys.exit(app.exec())

    run_scan()


if __name__ == "__main__":
    main()

