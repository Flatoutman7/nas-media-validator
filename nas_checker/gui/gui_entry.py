import sys

from PySide6.QtWidgets import QApplication

from nas_checker.gui.gui import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
