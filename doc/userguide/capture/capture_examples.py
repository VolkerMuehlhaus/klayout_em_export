# Screenshots for examples/README.md, split region example: the layout with its pieces, ground and ports, the cut, the
# EM panel and the export. KLayout with its window and the plug-in (autorun). Run (not with -z, not with -rx):
#   klayout_app.exe -r doc/userguide/capture/capture_examples.py
# Environment (optional): SHOTS (output folder, default examples/split_region/images), WORK (scratch folder; the
# export goes there), STACKUP. The example layout is copied to WORK first, so the plug-in's changes (stackup, backup)
# don't touch it. The plug-in settings (~/.klayout_em_export.json) are backed up and restored. Errors go to
# capture_examples.log in WORK; KLayout always quits at the end (and after 5 minutes at the latest).
# Then capture_setupem_set.py takes setupEM's model list of the export.
import json
import os
import shutil
import sys
import tempfile
import traceback

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
EXAMPLE = os.path.join(REPO, "examples", "split_region")
OUT = os.environ.get("SHOTS", os.path.join(EXAMPLE, "images"))
WORK = os.environ.get("WORK", os.path.join(tempfile.gettempdir(), "klayout_em_export_examples"))
STACKUP = os.environ.get("STACKUP", os.path.join(os.environ.get("GDS2PALACE") or os.path.join(REPO, "..", "gds2palace_ihp_sg13g2"),
                                                  "XML_stackup", "latest", "IHP", "SG13G2_FEM_200um.xml"))
SETTINGS = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")
os.makedirs(OUT, exist_ok=True)
os.makedirs(WORK, exist_ok=True)
log = open(os.path.join(WORK, "capture_examples.log"), "w")
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
    widget.grab().save(os.path.join(OUT, name + ".png"))
    say(f"shot {name}")


PORT_COLOR = 0x00ffff


def mark_ports(view, layout, cell):
    """Markers and P<n> labels on the port shapes (layers 201..299)."""
    markers = []
    for layer in range(201, 300):
        li = layout.find_layer(layer, 0)
        if li is None:
            continue
        for shape in cell.shapes(li).each():
            box = shape.dbbox()
            marker = pya.Marker(view)
            marker.set(box if box.width() and box.height() else box.enlarged(0.6, 0.6))
            marker.color = marker.frame_color = PORT_COLOR
            marker.line_width = 3
            markers.append(marker)
            ant = pya.Annotation()
            # ports 2 and 3 share the cut: label them left and right of it
            dx = -14 if layer == 202 else (4 if layer == 203 else 2)
            ant.p1 = ant.p2 = pya.DPoint(box.left + dx, box.top + 4)
            ant.fmt = f"P{layer - 200}"
            ant.style = pya.Annotation.StyleLine
            ant.outline = pya.Annotation.OutlineDiag
            view.insert_annotation(ant)
    return markers


def view_image(name, box=None, width=1400, height=700):
    view = mw.current_view()
    cv = view.active_cellview()
    markers = mark_ports(view, cv.layout(), cv.cell)
    if box is not None:
        view.zoom_box(box)
    else:
        view.zoom_fit()
    settle()
    view.save_image(os.path.join(OUT, name + ".png"), width, height)
    view.clear_annotations()
    for marker in markers:
        marker._destroy()
    say(f"image {name}")


def panel():
    return gui._panel


def grab_panel(name, width=760):
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


from klayout_em_export import gui  # noqa: E402

backup = SETTINGS + ".examples_backup"
if os.path.isfile(SETTINGS):
    shutil.copyfile(SETTINGS, backup)
with open(SETTINGS, "w") as f:
    json.dump({}, f)
LAYOUT = os.path.join(WORK, "two_inductors_split.gds")


def open_example():
    for name in os.listdir(WORK):
        if name.startswith("two_inductors"):
            path = os.path.join(WORK, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    shutil.copyfile(os.path.join(EXAMPLE, "two_inductors_split.gds"), LAYOUT)
    mw.resize(1700, 1050)
    mw.load_layout(LAYOUT, 0)
    view = mw.current_view()
    view.max_hier()
    gui.show_panel()
    cv = view.active_cellview()
    gui.set_stackup(cv.layout(), STACKUP)
    it = view.begin_layers()                 # the region boxes as outlines, not a fill over the layout
    while not it.at_end():
        properties = it.current()
        if properties.source_layer == 800:
            outline = properties.dup()
            outline.dither_pattern = 1
            outline.width = 2
            view.set_layer_properties(it, outline)
        it.next()
    view.zoom_fit()
    panel().refresh(run_checks=True)
    settle(40)


def layout_images():
    view_image("split_layout")
    panel()._show_ground(True)
    view_image("split_ground")
    panel()._show_ground(False)
    view_image("split_cut", pya.DBox(344, -45, 424, 35), 1000, 700)


def panel_images():
    for s in (panel().stackup_step, panel().region_step, panel().ground_step, panel().devices_step):
        s.arrow.setChecked(s is panel().region_step)
    settle()
    grab_panel("split_panel")


def export():
    settings = gui._load_settings()
    settings["open_setupem"] = False
    gui._save_settings(settings)
    view = mw.current_view()
    cv = view.active_cellview()
    gds = os.path.join(WORK, "two_inductors_em.gds")
    gui.set_layout_value(cv.layout(), gui.META_OUTPUT, gds, "EM export output file")
    timer = pya.QTimer()
    timer.singleShot = True

    def press_export():
        dialog = get(app.activeModalWidget)
        if dialog is None:
            say("no modal export dialog")
            return
        grab(dialog, "split_export_dialog")
        dialog.accept()
    timer.timeout = press_export
    timer.start(1500)
    gui.export_region()
    say("exported: " + ", ".join(sorted(os.listdir(WORK))))


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
for name, function in (("open", open_example), ("layout", layout_images), ("panel", panel_images),
                       ("export", export)):
    say(f"-- {name}")
    step(name, function)
finish()
