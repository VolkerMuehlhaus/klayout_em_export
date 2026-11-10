# Screenshots of setupEM with the exported split region example (examples/README.md), after capture_examples.py has
# exported it. Run in the Python environment with setupEM (a venv):
#   python doc/userguide/capture/capture_setupem_set.py <exported .simcfg> [output folder]
# Writes setupem_set_<tab>.png for every tab; the README uses the ones that show the set's models.
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from setupEM import setupEM

simcfg = os.path.abspath(sys.argv[1])
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                                         "examples", "split_region", "images")
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
win = setupEM.MainWindow()
win.resize(1100, 900)
win.show()
# loading may show a modal message box, which would block the script: close it
closer = QTimer()
closer.timeout.connect(lambda: isinstance(app.activeModalWidget(), QMessageBox) and app.activeModalWidget().accept())
closer.start(500)
win.load_configuration_from_file(simcfg)
win.setPalaceMode()
# the settings of the reference results: 0 to 60 GHz in 1 GHz steps, refined cell size 5 um
win.frequencies_tab.start_edit.setText("0")
win.frequencies_tab.stop_edit.setText("60")
win.frequencies_tab.step_edit.setText("1")


def capture():
    for index in range(win.tabs_widget.count()):
        name = win.tabs_widget.tabText(index)
        win.tabs_widget.setCurrentIndex(index)
        for _ in range(20):
            app.processEvents()
        slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
        win.grab().save(os.path.join(out, f"setupem_set_{slug}.png"))
        print("shot", name, flush=True)
    app.quit()


QTimer.singleShot(1500, capture)
app.exec()
