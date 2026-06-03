import asyncio
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from desktop.controller import DesktopController
from desktop.ui.main_window import MainWindow


def run_desktop_app() -> int:
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    controller = DesktopController(window)
    controller.bind()

    window.show()
    with loop:
        loop.run_forever()

    return 0
