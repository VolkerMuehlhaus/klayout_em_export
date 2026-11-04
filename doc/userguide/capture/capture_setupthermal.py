# Screenshots of setupThermal with the thermal export of the cascode, for the user's guide's thermal chapter: the
# heat sources after Load powers..., with the region outline's boundary on BACKSIDEGND. Run in the Python environment
# with setupEM (e.g. d:\venv\palace), after capture_thermal.py has exported the cascode:
#   python doc/userguide/capture/capture_setupthermal.py <exported .tsimcfg> [output folder]
# The powers are example values for the screenshot, not the cascode's bias point.
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from setupEM import setupThermal

tsimcfg = os.path.abspath(sys.argv[1])
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images")
os.makedirs(out, exist_ok=True)
powers = os.path.join(os.path.dirname(tsimcfg), "powers.csv")
with open(powers, "w") as f:
    f.write("instance, power\nXcore.Q1, 10m\nXcore.Q2, 10m\nR1, 0.15m\nR2, 0.05m\nR3, 0.5m\n")

app = QApplication(sys.argv)
win = setupThermal.MainWindow()
win.resize(1100, 700)
win.show()


def close_boxes():
    """Close setupThermal's message boxes (config loaded, Load powers report)."""
    box = app.activeModalWidget()
    if isinstance(box, QMessageBox):
        box.accept()


closer = QTimer()
closer.timeout.connect(close_boxes)
closer.start(300)
win.load_configuration_from_file(tsimcfg)


def capture():
    tab = win.thermal_tab
    win.tabs_widget.setCurrentWidget(tab)
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (powers, ""))
    tab.load_powers()
    for row in range(tab.thermalobjectslist.rowCount()):
        kind = tab.thermalobjectslist.item(row, 2)
        if kind is not None and "SOURCE" not in kind.text().upper():
            tab.thermalobjectslist.selectRow(row)
            tab.target_box.setCurrentIndex(tab.target_box.findText("BACKSIDEGND"))
            tab.apply_port_values_to_table()
    tab.thermalobjectslist.selectRow(3)
    for _ in range(20):
        app.processEvents()
    win.grab().save(os.path.join(out, "15_setupthermal_sources.png"))
    print("shot 15_setupthermal_sources")
    win._script_dirty = False
    app.quit()


QTimer.singleShot(1500, capture)
app.exec()
