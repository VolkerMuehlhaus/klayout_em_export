# Screenshots for the user's guide's thermal chapter: KLayout with its window and the plug-in (autorun), the EM panel
# in Thermal mode and the thermal export of the cascode example, with instance names from its LVS database. Run (not
# with -z, not with -rx):
#   klayout_app.exe -r doc/userguide/capture/capture_thermal.py
# then the setupThermal shot with capture_setupthermal.py on the export (WORK/cascode_thermal.tsimcfg).
# Environment (optional): SHOTS (output folder, default doc/userguide/images), WORK (scratch folder), SOURCE (the
# cascode layout), STACKUP. The PDK: IHP_PDK_ROOT or tests/pdk (see tests/testpaths.py).
# The plug-in settings (~/.klayout_em_export.json) are backed up and restored. Errors go to capture_thermal.log;
# KLayout always quits at the end (and after 5 minutes at the latest).
import json
import os
import shutil
import sys
import tempfile
import traceback

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("SHOTS", os.path.join(HERE, "..", "images"))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
WORK = os.environ.get("WORK", os.path.join(tempfile.gettempdir(), "klayout_em_export_guide"))
SOURCE = os.environ.get("SOURCE", os.path.join(REPO, "tests", "data", "1_St_Core_v1_forEM.gds"))
STACKUP = os.environ.get("STACKUP", os.path.join(os.environ.get("GDS2PALACE") or os.path.join(REPO, "..", "gds2palace_ihp_sg13g2"),
                                                  "XML_stackup", "latest", "IHP", "SG13G2_FEM_200um.xml"))
TESTS_DIR = os.path.join(REPO, "tests")
LVSDB = os.path.join(TESTS_DIR, "data", "lvs_cascode", "cascode_hier.lvsdb")
SETTINGS = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")
os.makedirs(OUT, exist_ok=True)
os.makedirs(WORK, exist_ok=True)
log = open(os.path.join(WORK, "capture_thermal.log"), "w")
app = pya.Application.instance()
mw = app.main_window()


def say(text):
    log.write(text + "\n")
    log.flush()


def settle(n=20):
    for _ in range(n):
        app.process_events()


def get(value):
    return value() if callable(value) else value


def grab(widget, name):
    settle()
    get(widget.grab).save(os.path.join(OUT, name + ".png"))
    say(f"shot {name}")


def step(name, function):
    try:
        function()
    except Exception:
        say(f"FAILED {name}:\n{traceback.format_exc()}")


sys.path.insert(0, TESTS_DIR)
from pdk_env import load_pdk
load_pdk()
from klayout_em_export import gui

backup = SETTINGS + ".guide_backup"
if os.path.isfile(SETTINGS):
    shutil.copyfile(SETTINGS, backup)
with open(SETTINGS, "w") as f:
    json.dump({"open_setupthermal": False}, f)


def panel():
    return gui._panel


def view_cv():
    view = mw.current_view()
    return view, view.active_cellview()


def make_copy():
    """The cascode as it comes (devices as drawn, no ports needed), without the plug-in's earlier settings."""
    ly = pya.Layout()
    ly.technology_name = "sg13g2"
    ly.read(SOURCE)
    for name in ("klayout_em_export.ground", "klayout_em_export.output", "klayout_em_export.stackup",
                 "klayout_em_export.thermal_output", "klayout_em_export.lvsdb"):
        ly.remove_meta_info(name)
    ly.write(os.path.join(WORK, "cascode_t.gds"))
    for ext in (".gds", ".tsimcfg", "_thermalmap.json"):
        path = os.path.join(WORK, "cascode_thermal" + ext)
        if os.path.isfile(path):
            os.remove(path)


def open_layout():
    mw.resize(1700, 1050)
    mw.load_layout(os.path.join(WORK, "cascode_t.gds"), 0)
    view, cv = view_cv()
    view.max_hier()
    view.zoom_fit()
    gui.show_panel()
    layout = cv.layout()
    gui.set_stackup(layout, STACKUP)
    gui.set_layout_value(layout, gui.META_LVSDB, LVSDB, "LVS database for the thermal export's instance names")
    gui.set_layout_value(layout, gui.META_THERMAL_OUTPUT, os.path.join(WORK, "cascode_thermal.gds"),
                         "thermal export output file")


def thermal_panel():
    p = panel()
    p.mode_bar.setCurrentIndex(1)
    p.refresh()
    for s in (p.stackup_step, p.region_step, p.names_step, p.boundary_step):
        s.arrow.setChecked(False)
    settle()
    dock = gui._dock
    dock.setFloating(True)
    settle()
    content = get(p.sizeHint)
    dock.resize(900, max(600, get(content.height) + 80))
    settle(40)
    grab(dock, "15_panel_thermal")


def export_dialog():
    """The real export: a timer grabs the (modal) export dialog and presses Export."""
    timer = pya.QTimer()
    timer.singleShot = True

    def press_export():
        dialog = get(app.activeModalWidget)
        if dialog is None:
            say("no modal export dialog")
            return
        grab(dialog, "15_export_thermal")
        dialog.accept()
    timer.timeout = press_export
    timer.start(1500)
    gui.export_thermal_region()
    say("exported: " + ", ".join(f for f in os.listdir(WORK) if f.startswith("cascode_thermal")))


def finish():
    say("done")
    log.close()
    if os.path.isfile(backup):
        shutil.move(backup, SETTINGS)
    elif os.path.isfile(SETTINGS):
        os.remove(SETTINGS)
    app.exit(0)


watchdog = pya.QTimer()
watchdog.singleShot = True
watchdog.timeout = finish
watchdog.start(300000)
for name, function in (("copy", make_copy), ("open", open_layout), ("thermal panel", thermal_panel),
                       ("export dialog", export_dialog)):
    say(f"-- {name}")
    step(name, function)
finish()
