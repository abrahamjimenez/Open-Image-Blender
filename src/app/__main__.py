import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Open Image Blender")
    app.setOrganizationName("openimageblender")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
