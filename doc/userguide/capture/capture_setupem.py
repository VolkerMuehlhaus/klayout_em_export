# Screenshots of setupEM with the exported cascode model, for the user's guide. Run in the Python environment with
# setupEM (a venv), after capture.py has exported the cascode:
#   python doc/userguide/capture/capture_setupem.py <exported .simcfg> [output folder]
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from setupEM import setupEM

simcfg = os.path.abspath(sys.argv[1])
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images")
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
win = setupEM.MainWindow()
win.resize(1100, 900)
win.show()
# loading may show a modal "Config loaded" message box, which would block the script: close it
closer = QTimer()
closer.timeout.connect(lambda: isinstance(app.activeModalWidget(), QMessageBox) and app.activeModalWidget().accept())
closer.start(500)
win.load_configuration_from_file(simcfg)
win.setPalaceMode()
# the cascode's sweep: from 0 Hz (gds2palace then simulates 10 and 20 MHz and adds a 0 Hz point), 1 GHz steps
win.frequencies_tab.start_edit.setText("0")
win.frequencies_tab.stop_edit.setText("200")
win.frequencies_tab.step_edit.setText("1")


def capture():
    for index in range(win.tabs_widget.count()):
        name = win.tabs_widget.tabText(index)
        print("tab", index, name, flush=True)
        if True:
            win.tabs_widget.setCurrentIndex(index)
            for _ in range(20):
                app.processEvents()
            slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
            win.grab().save(os.path.join(out, f"12_setupem_{slug}.png"))
            print("shot", name)
    app.quit()


QTimer.singleShot(1500, capture)
app.exec()
