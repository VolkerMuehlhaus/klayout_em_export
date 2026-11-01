# Screenshots for the user's guide: KLayout with its window and the plug-in (autorun), driven through the guide's
# steps on the cascode example. Run (not with -z, not with -rx):
#   klayout_app.exe -r doc/userguide/capture/capture.py
# Environment (optional): SHOTS (output folder, default doc/userguide/images), WORK (scratch folder), SOURCE (the
# cascode layout), STACKUP, TESTS_DIR (klayout_em_export_tests, with pdk_env.py), PYTHON (a Python with snp2le).
# Defaults are the Windows development machine's paths.
# The plug-in settings (~/.klayout_em_export.json) are backed up and restored. Errors go to capture.log; KLayout
# always quits at the end (and after 10 minutes at the latest).
import json
import os
import shutil
import sys
import traceback

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("SHOTS", os.path.join(HERE, "..", "images"))
WORK = os.environ.get("WORK", r"D:\Palace_testcases\klayout_export\guide")
SOURCE = os.environ.get("SOURCE", r"D:\Palace_testcases\klayout_export\1_St_Core_v1_forEM.gds")
STACKUP = os.environ.get("STACKUP", r"D:\github-claude\gds2palace_ihp_sg13g2\XML_stackup\latest\IHP\SG13G2_FEM_200um.xml")
TESTS_DIR = os.environ.get("TESTS_DIR", r"D:\github-claude\klayout_em_export_tests")
PYTHON = os.environ.get("PYTHON", r"D:\venv\palace\Scripts\python.exe")
PORTMAP = os.environ.get("PORTMAP", "")
SNP = os.environ.get("SNP", "")
SETTINGS = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")
os.makedirs(OUT, exist_ok=True)
os.makedirs(WORK, exist_ok=True)
log = open(os.path.join(WORK, "capture.log"), "w")
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
    get(widget.grab).save(os.path.join(OUT, name + ".png")) if not callable(widget.grab) else widget.grab().save(
        os.path.join(OUT, name + ".png"))
    say(f"shot {name}")


PORT_COLOR, REF_COLOR = 0x00ffff, 0xff8c00


def mark_shapes(view, layout, cell, layers, color, labels=False):
    """Markers (and number labels) on the shapes of the given layers, so ports and REF patches stand out."""
    markers = []
    for layer in layers:
        li = layout.find_layer(layer, 0)
        if li is None:
            continue
        for shape in cell.shapes(li).each():
            box = shape.dbbox()
            marker = pya.Marker(view)
            marker.set(box if box.width() and box.height() else box.enlarged(0.04, 0.04))
            marker.color = color
            marker.frame_color = color
            marker.line_width = 3
            marker.dither_pattern = 1 if box.width() and box.height() else 0
            markers.append(marker)
            if labels:
                ant = pya.Annotation()
                ant.p1 = ant.p2 = pya.DPoint(box.left, box.top)
                ant.fmt = f"P{layer - 200}"
                ant.style = pya.Annotation.StyleLine
                ant.outline = pya.Annotation.OutlineDiag
                markers.append(view.insert_annotation(ant) or ant)
    return markers


def view_image(name, box=None, width=1400, height=900, ports=True, refs=True):
    view = mw.current_view()
    cv = view.active_cellview()
    layout, cell = cv.layout(), cv.cell
    markers = []
    if ports:
        markers += mark_shapes(view, layout, cell, range(201, 300), PORT_COLOR, labels=True)
    if refs:
        markers += mark_shapes(view, layout, cell, [300], REF_COLOR)
    if box is not None:
        view.zoom_box(box)
    else:
        view.zoom_fit()
    settle()
    view.save_image(os.path.join(OUT, name + ".png"), width, height)
    view.clear_annotations()
    for marker in markers:
        if isinstance(marker, pya.Marker):
            marker._destroy()
    say(f"image {name}")


def dock_below_layers():
    """The EM panel docked below KLayout's Layers panel, as on a fresh install. KLayout restores the dock layout of
    the user's last session (the panel may be tabbed with Layers or floating), and floating it for grab_panel()
    and back can tab it too; so place it explicitly before a main window shot."""
    dock = gui._dock
    dock.setFloating(False)
    # KLayout's own docks may come as QDockWidget_Native, which is no pya.QDockWidget instance (0.30 on Linux)
    docks = {get(w.windowTitle): w for w in mw.findChildren()
             if type(w).__name__.startswith("QDockWidget") and w is not dock}
    if "Layers" in docks:
        mw.splitDockWidget(docks["Layers"], dock, pya.Qt.Vertical)
    if "Layer Toolbox" in docks:             # shown by default on Linux; it would squeeze the panel
        docks["Layer Toolbox"].hide()
    dock.show()
    settle(40)


def grab_panel(name, width=760):
    """The EM panel, floating and as tall as its content needs (docked, Qt squeezes open details)."""
    dock = gui._dock
    dock.setFloating(True)
    settle()
    content = get(panel().sizeHint)
    dock.resize(width, max(600, get(content.height) + 80))
    settle(40)
    grab(dock, name)


def step(name, function):
    try:
        function()
    except Exception:
        say(f"FAILED {name}:\n{traceback.format_exc()}")


# ---------- clean copy of the example ----------
sys.path.insert(0, TESTS_DIR)
from pdk_env import load_pdk
load_pdk()
from klayout_em_export import gui
from klayout_em_export.devices import unreplace
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports, check_ports
from klayout_em_export.locate import metals_at

backup = SETTINGS + ".guide_backup"
if os.path.isfile(SETTINGS):
    shutil.copyfile(SETTINGS, backup)
with open(SETTINGS, "w") as f:
    json.dump({}, f)


class NoUndo:
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass


def make_clean():
    ly = pya.Layout()
    ly.technology_name = "sg13g2"
    ly.read(SOURCE)
    cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))
    unreplace(NoUndo(), cell)
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        if 201 <= info.layer <= 299 or info.layer == 800:
            ly.clear_layer(li)
    for name in ("klayout_em_export.ground", "klayout_em_export.output", "klayout_em_export.stackup"):
        ly.remove_meta_info(name)
    ly.write(os.path.join(WORK, "cascode.gds"))


def view_cv():
    view = mw.current_view()
    return view, view.active_cellview()


def panel():
    return gui._panel


def expand(*steps):
    for s in (panel().stackup_step, panel().region_step, panel().ground_step, panel().devices_step):
        s.arrow.setChecked(s in steps)
    settle()


def open_start():
    mw.resize(1700, 1050)
    mw.load_layout(os.path.join(WORK, "cascode.gds"), 0)
    view = mw.current_view()
    view.max_hier()
    view.zoom_fit()
    gui.show_panel()
    dock_below_layers()
    expand(panel().stackup_step)
    grab(mw, "02_main_window_start")
    grab_panel("05_panel_no_stackup")


def em_menu():
    for action in get(get(mw.menuBar).actions):
        if action.text.replace("&", "") == "EM":
            menu = get(action.menu)
            menu.popup(mw.mapToGlobal(pya.QPoint(450, 25)))
            settle()
            grab(menu, "04_em_menu")
            menu.close()


def choose_stackup():
    view, cv = view_cv()
    gui.set_stackup(cv.layout(), STACKUP)
    panel().refresh()
    expand(panel().stackup_step)
    grab_panel("05_panel_stackup")


def pad_ports():
    view, cv = view_cv()
    layout, cell = cv.layout(), cv.cell
    stackup = gui.read_stackup(STACKUP)[0]
    settings = PortSettings("Z", "TopMetal2", "Metal5")
    for layer, box in ((201, pya.DBox(-3.215, 20.63, 1.785, 20.63)), (202, pya.DBox(-4.215, -11.275, 2.785, -11.275))):
        cell.shapes(layout.layer(layer, 0)).insert(box.to_itype(layout.dbu))
    view.add_missing_layers()
    view_image("07_pad_port_top", pya.DBox(-10, 12, 9, 22.5))
    li = layout.find_layer(201, 0)
    shape = next(iter(cell.shapes(li).each()))
    available = lambda st: metals_at(layout, cell, st, shape.bbox())
    dialog = gui.PortDialog(layout, available, settings, 1)
    dialog.show()
    grab(dialog, "07_port_dialog")
    dialog.close()
    for layer in (201, 202):
        li = layout.find_layer(layer, 0)
        for shape in list(cell.shapes(li).each()):
            box = shape.bbox()
            shape.delete()
            cell.shapes(li).insert(box, layout.properties_id([[PROP_KEY, settings.encode()]]))
    panel().refresh()
    expand()
    grab_panel("07_panel_two_ports")


def port_overview():
    view, cv = view_cv()
    stackup = gui.read_stackup(STACKUP)[0]
    ports = collect_ports(cv.layout(), cv.cell, stackup=stackup)
    lines = [f"Ports in cell {cv.cell.name}:"]
    for layer in sorted(ports):
        port = ports[layer]
        lines.append(f"  port {port.number:2d} (layer {layer}, {port.shapes} shape(s)): " +
                     (str(port.settings) if port.settings else "no settings"))
    lines += ["", f"Checked against {os.path.basename(STACKUP)}:"] + (check_ports(ports, stackup) or ["all complete"])
    box = pya.QMessageBox(mw)
    box.setWindowTitle("EM Export")
    box.setText("\n".join(lines))
    box.setIcon(pya.QMessageBox.Information)
    box.show()
    grab(box, "07_port_overview")
    box.close()


def ground():
    panel().refresh(run_checks=True)
    expand(panel().ground_step)
    grab_panel("08_panel_ground")
    panel()._show_ground(True)
    view_image("08_ground_in_layout")
    panel()._show_ground(False)


def devices():
    panel().refresh()
    expand(panel().devices_step)
    grab_panel("10_panel_devices_before")
    view_image("10_q1_before", pya.DBox(-12, -4, 11, 6))
    panel().include_resistors.setChecked(True)
    panel()._replace_devices()
    expand(panel().devices_step)
    grab_panel("10_panel_devices_after")
    view_image("10_q1_after", pya.DBox(-12, -4, 11, 6))
    view_image("10_resistors_after", pya.DBox(-30, -1, -22, 10))


def boundary():
    view, cv = view_cv()
    layout, cell = cv.layout(), cv.cell
    # an EM region that cuts the Cas_Bias wire at the left
    cell.shapes(layout.layer(800, 0)).insert(pya.DBox(-28.9, -11.275, 21.595, 20.63).to_itype(layout.dbu))
    view.add_missing_layers()
    it = view.begin_layers()                 # the region box as an outline, not a fill over the layout
    while not it.at_end():
        properties = it.current()
        if properties.source_layer == 800:
            outline = properties.dup()
            outline.dither_pattern = 1
            outline.width = 2
            view.set_layer_properties(it, outline)
        it.next()
    panel().refresh(run_checks=True)
    expand(panel().region_step)
    grab_panel("09_panel_proposed")
    view_image("09_region_cut", pya.DBox(-31, 5, -20, 14))
    panel()._create_proposed()
    expand()
    grab_panel("09_panel_created")
    view_image("09_boundary_port", pya.DBox(-31, 5, -20, 14))
    view_image("09_region_whole")


def export_dialog():
    """The real export: a timer grabs the (modal) export dialog and presses Export."""
    gds = os.path.join(WORK, "cascode_em.gds")
    for ext in (".gds", ".simcfg", "_portmap.json"):
        path = gds[:-4] + ext
        if os.path.isfile(path):
            os.remove(path)
    settings = gui._load_settings()
    settings["open_setupem"] = False
    gui._save_settings(settings)
    view, cv = view_cv()
    gui.set_layout_value(cv.layout(), gui.META_OUTPUT, gds, "EM export output file")
    timer = pya.QTimer()
    timer.singleShot = True

    def press_export():
        dialog = get(app.activeModalWidget)
        if dialog is None:
            say("no modal export dialog")
            return
        grab(dialog, "11_export_dialog")
        dialog.accept()
    timer.timeout = press_export
    timer.start(1500)
    gui.export_region()
    say("exported: " + ", ".join(f for f in os.listdir(WORK) if f.startswith("cascode_em")))
    panel().refresh()
    expand()
    dock_below_layers()
    grab(mw, "11_main_window_ready")


def circuit_dialog():
    from klayout_em_export.circuit import CircuitDialog, run_wrapper
    portmap, snp = os.path.join(WORK, "cascode_em_portmap.json"), os.path.join(WORK, "cascode_em_dc.s15p")
    if SNP:
        shutil.copyfile(SNP, snp)
    dialog = CircuitDialog(portmap)
    dialog.snp.setText(snp)
    dialog.python.setText(PYTHON)
    dialog._update_output()
    dialog.show()
    grab(dialog, "13_circuit_dialog")
    dialog.simulator.showPopup()
    settle()
    popup = get(dialog.simulator.view)
    grab(get(popup.window), "13_simulator_choice")
    dialog.simulator.hidePopup()
    ok, report = run_wrapper(dialog.python.text, portmap, snp, dialog.output.text, "ngspice", "fit", "")
    dialog.close()
    box = pya.QMessageBox(mw)
    box.setWindowTitle("Create Circuit")
    box.setText(f"Wrote {dialog.output.text} (ngspice, EM model by snp2le).\n\n{report}" if ok else report)
    box.setIcon(pya.QMessageBox.Information if ok else pya.QMessageBox.Critical)
    box.show()
    grab(box, "13_circuit_done")
    box.close()


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
watchdog.start(600000)
for name, function in (("clean copy", make_clean), ("start", open_start), ("menu", em_menu),
                       ("stackup", choose_stackup), ("pad ports", pad_ports), ("port overview", port_overview),
                       ("ground", ground), ("devices", devices), ("boundary", boundary),
                       ("export dialog", export_dialog), ("circuit dialog", circuit_dialog)):
    say(f"-- {name}")
    step(name, function)
finish()
