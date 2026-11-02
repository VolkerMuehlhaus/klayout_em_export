# Frames for the demo video: KLayout with the plug-in (autorun), driven through the user's guide steps on the cascode
# example, then dummy fill and density holes on the FMD 60 GHz PA. Run (not with -z, not with -rx):
#   klayout_app.exe -rm doc/video/capture_video.py
# then doc/video/make_video.sh does the setupEM frames and the composition (compose_video.py).
# Environment (optional): VIDEO (output folder), CASCODE, FMD, STACKUP, TESTS_DIR, PYTHON, SNP (a cascode _dc.s15p).
# Writes VIDEO/frames/*.png and VIDEO/manifest.json: per shot its caption and the real KLayout grabs it is made of (main
# window, the EM panel floating at full height, dialogs), with pointer targets in the frame's coordinates. The plug-in
# settings (~/.klayout_em_export.json) are backed up and restored; errors go to VIDEO/capture.log. KLayout always quits
# at the end (and after 15 minutes at the latest).
import json
import os
import shutil
import sys
import traceback

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "..")
VIDEO = os.environ.get("VIDEO", r"D:\Palace_testcases\klayout_export\video")
FRAMES = os.path.join(VIDEO, "frames")
WORK = os.path.join(VIDEO, "work")
CASCODE = os.environ.get("CASCODE", r"D:\Palace_testcases\klayout_export\1_St_Core_v1_forEM.gds")
FMD = os.environ.get("FMD", r"D:\Palace_testcases\klayout_export\FMD_QNC_60_ghz_mpa_filled.gds")
STACKUP = os.environ.get("STACKUP", r"D:\github-claude\gds2palace_ihp_sg13g2\XML_stackup\latest\IHP\SG13G2_FEM_200um.xml")
TESTS_DIR = os.environ.get("TESTS_DIR", r"D:\github-claude\klayout_em_export_tests")
PYTHON = os.environ.get("PYTHON", r"D:\venv\palace\Scripts\python.exe")
SNP = os.environ.get("SNP", r"D:\Palace_testcases\klayout_export\guide\cascode_em_dc.s15p")
SETTINGS = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")
# The video frame: main window | EM panel, 1100 | 820 px of 1920x1080, with KLayout shown at ZOOM (the grabs have the
# screen's device pixels, 2x here, so they stay sharp); sizes below are KLayout's logical pixels.
ZOOM = 1.2
LAYOUT_W, PANEL_W, HEIGHT = round(1100 / ZOOM), round(820 / ZOOM), round(1080 / ZOOM)
for folder in (FRAMES, WORK):
    os.makedirs(folder, exist_ok=True)
log = open(os.path.join(VIDEO, "capture.log"), "w")
app = pya.Application.instance()
mw = app.main_window()
shots = []


def say(text):
    log.write(text + "\n")
    log.flush()


def settle(n=20):
    for _ in range(n):
        app.process_events()


def get(value):
    return value() if callable(value) else value


def save(widget, name):
    """Grab widget to frames/name.png; returns {file, w, h} with the widget's logical size (the grab has the
    screen's device pixels)."""
    settle()
    get(widget.grab).save(os.path.join(FRAMES, name + ".png"))
    say(f"frame {name}")
    return {"file": f"frames/{name}.png", "w": get(widget.width), "h": get(widget.height)}


def shot(caption, chapter=None, **parts):
    """One shot of the video: layout (main window grab or a list of them, played as a move), panel, dialog (over the
    layout, at pos or centered), pointer [targets], image/text/card for full-frame shots, hold (extra seconds)."""
    entry = {"caption": caption}
    if chapter:
        entry["chapter"] = chapter
    entry.update(parts)
    shots.append(entry)


def find(parent, kind, text=None):
    """The first child widget of type kind (e.g. 'QPushButton') with this text (& stripped)."""
    for w in parent.findChildren():
        if type(w).__name__.startswith(kind) and (text is None or get(w.text).replace("&", "") == text):
            return w
    return None


def at(widget, top, where, rect=None):
    """Pointer target: the center of widget (or of rect in widget) in top's coordinates, in frame part where."""
    if rect is None:
        p = widget.mapTo(top, pya.QPoint(get(widget.width) // 2, get(widget.height) // 2))
    else:
        p = widget.mapTo(top, rect.center())
    return {"in": where, "x": p.x, "y": p.y}


def canvas():
    return next(w for w in mw.findChildren() if get(w.objectName) == "canvas" and get(w.isVisible))


def layout_at(x, y):
    """Pointer target: layout point (um) in the main window."""
    view = mw.current_view()
    c = canvas()
    p = view.viewport_trans() * pya.DPoint(x, y)
    scale = view.viewport_width() / get(c.width)            # device pixels per logical pixel
    o = c.mapTo(mw, pya.QPoint(0, 0))
    return {"in": "layout", "x": round(o.x + p.x / scale), "y": round(o.y + (view.viewport_height() - p.y) / scale)}


def layout_frame(name):
    return save(mw, name)


def panel_frame(name):
    """The EM panel, floating, as tall as its content needs (at least the frame height)."""
    content = get(panel().sizeHint)
    dock.resize(PANEL_W, max(HEIGHT, get(content.height) + 80))
    settle(40)
    return save(dock, name)


def move(name, start, end, frames=24):
    """Zoom from box start to box end (um), one main window grab per step: the layout re-renders as it zooms."""
    view = mw.current_view()
    result = []
    for i in range(frames + 1):
        t = i / frames
        t = t * t * (3 - 2 * t)                             # ease in and out
        box = pya.DBox(*(a + (b - a) * t for a, b in zip((start.left, start.bottom, start.right, start.top),
                                                            (end.left, end.bottom, end.right, end.top))))
        view.zoom_box(box)
        result.append(layout_frame(f"{name}_{i:02d}"))
    return result


def fit_box():
    view = mw.current_view()
    view.zoom_fit()
    settle()
    return view.box()


def modal(function, name, button):
    """Run function, which opens a modal dialog; a timer waits for it (the function may compute a while first), grabs
    it, notes where its button is, and presses that button. Returns (grab, pointer target) - the target in the
    dialog's coordinates."""
    found = {}
    timer = pya.QTimer()
    tries = [0]

    def press():
        # the plug-in's message boxes (pya.MessageBox) are no active modal widget: the visible top-level dialog
        dialog = next((w for w in get(pya.QApplication.topLevelWidgets) if get(w.isVisible) and
                       type(w).__name__.startswith(("QMessageBox", "QDialog", "ExportDialog"))), None)
        tries[0] += 1
        if dialog is None:
            if tries[0] > 600:
                say(f"no modal dialog for {name}")
                timer.stop()
            return
        timer.stop()
        found["grab"] = save(dialog, name)
        b = find(dialog, "QPushButton", button)
        found["at"] = at(b, dialog, "dialog") if b is not None else None
        if b is not None:
            b.click()
        else:
            dialog.accept()
    timer.timeout = press
    timer.start(200)
    function()
    timer.stop()
    settle()
    return found.get("grab"), found.get("at")


PORT_COLOR, REF_COLOR = 0x00ffff, 0xff8c00
markers = []


def mark_shapes(layers, color, labels=False):
    """Markers (and P# labels) on the shapes of the given layers in the current cell, so ports stand out."""
    view = mw.current_view()
    cv = view.active_cellview()
    layout, cell = cv.layout(), cv.cell
    for layer in layers:
        li = layout.find_layer(layer, 0)
        if li is None:
            continue
        for s in cell.shapes(li).each():
            box = s.dbbox()
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
                view.insert_annotation(ant)


def unmark():
    mw.current_view().clear_annotations()
    for marker in markers:
        marker._destroy()
    markers.clear()


def mark_ports():
    unmark()
    mark_shapes(range(201, 300), PORT_COLOR, labels=True)
    mark_shapes([300], REF_COLOR)


def step(name, function):
    try:
        function()
    except Exception:
        say(f"FAILED {name}:\n{traceback.format_exc()}")


# ---------- plug-in, settings ----------
sys.path.insert(0, TESTS_DIR)
from pdk_env import load_pdk
load_pdk()
from klayout_em_export import gui, __version__
from klayout_em_export.devices import unreplace
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports, check_ports
from klayout_em_export.locate import metals_at

backup = SETTINGS + ".video_backup"
if os.path.isfile(SETTINGS):
    shutil.copyfile(SETTINGS, backup)
with open(SETTINGS, "w") as f:
    json.dump({}, f)
dock = None


def panel():
    return gui._panel


def expand(*steps):
    for s in (panel().stackup_step, panel().region_step, panel().ground_step, panel().devices_step):
        s.arrow.setChecked(s in steps)
    settle()


def view_cv():
    view = mw.current_view()
    return view, view.active_cellview()


class NoUndo:
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass


# ---------- the cascode, as in the user's guide ----------
def make_clean():
    """Work copies: the cascode without ports, devices replaced or plug-in data; the FMD layout as it is. No .bak
    left from an earlier run, so the plug-in makes a fresh one."""
    ly = pya.Layout()
    ly.technology_name = "sg13g2"
    ly.read(CASCODE)
    cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))
    unreplace(NoUndo(), cell)
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        if 201 <= info.layer <= 299 or info.layer == 800:
            ly.clear_layer(li)
    for name in ("klayout_em_export.ground", "klayout_em_export.output", "klayout_em_export.stackup"):
        ly.remove_meta_info(name)
    ly.write(os.path.join(WORK, "cascode.gds"))
    shutil.copyfile(FMD, os.path.join(WORK, "fmd_60ghz_pa.gds"))
    for name in os.listdir(WORK):
        if name.endswith(".bak") or name.startswith("cascode_em"):
            os.remove(os.path.join(WORK, name))


def title():
    shot("", card={"title": f"KLayout EM Export {__version__}",
                   "lines": ["EM models of RFIC layouts, prepared inside KLayout",
                             "IHP SG13G2 open-source PDK  -  gds2palace / setupEM / Palace"]}, chapter="Intro", hold=3)
    shot("From your layout to an EM model, and back to your circuit simulator with the PDK transistors.",
         image={"file": os.path.join(REPO, "doc", "userguide", "images", "01_flow.png")})


def open_start():
    global dock
    mw.resize(LAYOUT_W, HEIGHT)
    mw.load_layout(os.path.join(WORK, "cascode.gds"), 0)
    view = mw.current_view()
    view.max_hier()
    view.zoom_fit()
    gui.show_panel()
    dock = gui._dock
    for w in mw.findChildren():              # more room for the layout: KLayout's own docks hidden
        if type(w).__name__.startswith("QDockWidget") and w is not dock:
            w.hide()
    dock.setFloating(True)
    dock.move(mw.mapToGlobal(pya.QPoint(LAYOUT_W, 0)))
    expand(panel().stackup_step)
    settle(40)
    em = next(a for a in get(get(mw.menuBar).actions) if get(a.text).replace("&", "") == "EM")
    bar = get(mw.menuBar)
    geometry = bar.actionGeometry(em)
    corner = bar.mapTo(mw, pya.QPoint(geometry.left, geometry.bottom))
    title_at = at(bar, mw, "layout", geometry)
    shot("A cascode core from the IHP SG13G2 PDK. The plug-in adds the EM menu and the EM panel.", chapter="Start and stackup",
         layout=layout_frame("start"), panel=panel_frame("panel_start"), pointer=[title_at])
    menu = get(em.menu)
    menu.popup(mw.mapToGlobal(corner))
    settle()
    entry = next(a for a in get(menu.actions) if a.text.startswith("Remove Dummy"))
    shot("Everything is in the EM menu; the panel walks you through the steps.",
         layout=layout_frame("start"), panel=panel_frame("panel_start"),
         dialog=dict(save(menu, "em_menu"), x=corner.x, y=corner.y),
         pointer=[title_at, dict(at(menu, menu, "dialog", menu.actionGeometry(entry)))])
    menu.close()


def choose_stackup():
    view, cv = view_cv()
    change = find(panel().stackup_step, "QPushButton", "Change...")
    before = at(change, dock, "panel")
    gui.set_stackup(cv.layout(), STACKUP)
    panel().refresh()
    expand(panel().stackup_step)
    shot("Step 1: choose the gds2palace stackup. It knows every metal, via and dielectric of the process.",
         layout=layout_frame("start"), panel=panel_frame("panel_stackup"), pointer=[before])


TOP_PAD, BOTTOM_PAD = pya.DBox(-10, 12, 9, 22.5), pya.DBox(-11, -16, 10, -6)


def pad_ports():
    view, cv = view_cv()
    layout, cell = cv.layout(), cv.cell
    whole = fit_box()
    tool = find(panel(), "QPushButton", "EM Port tool")
    tool_at = at(tool, dock, "panel")
    frames = move("zoom_top_pad", whole, TOP_PAD)
    shot("Step 2: ports. Zoom to the output pad and pick the EM Port tool.", chapter="Ports", layout=frames,
         panel=panel_frame("panel_stackup"), pointer=[tool_at])
    edge = layout_at(-0.7, 20.63)
    gui.backup_original(layout)
    settings = PortSettings("Z", "TopMetal2", "Metal5")
    cell.shapes(layout.layer(201, 0)).insert(pya.DBox(-3.215, 20.63, 1.785, 20.63).to_itype(layout.dbu))
    view.add_missing_layers()
    mark_ports()
    shot("Click the metal edge: a via port, from TopMetal2 down to the ground below.",
         layout=layout_frame("port1_placed"), panel=panel_frame("panel_stackup"), pointer=[tool_at, edge])
    shape = next(iter(cell.shapes(layout.find_layer(201, 0)).each()))
    dialog = gui.PortDialog(layout, lambda st: metals_at(layout, cell, st, shape.bbox()), settings, 1)
    dialog.show()
    settle()
    ok = find(dialog, "QPushButton", "OK")
    shot("The port dialog offers only the layers found at the port. From, to, direction and Z0 are set here.",
         layout=layout_frame("port1_placed"), panel=panel_frame("panel_stackup"), dialog=save(dialog, "port_dialog"),
         pointer=[edge, at(ok, dialog, "dialog") if ok else edge])
    dialog.close()
    cell.shapes(layout.layer(202, 0)).insert(pya.DBox(-4.215, -11.275, 2.785, -11.275).to_itype(layout.dbu))
    for layer in (201, 202):
        li = layout.find_layer(layer, 0)
        for s in list(cell.shapes(li).each()):
            box = s.bbox()
            s.delete()
            cell.shapes(li).insert(box, layout.properties_id([[PROP_KEY, settings.encode()]]))
    view.add_missing_layers()
    panel().refresh()
    expand()
    mark_ports()
    frames = move("zoom_bottom_pad", TOP_PAD, BOTTOM_PAD, 16)
    shot("The input pad gets port 2 the same way. The panel lists every port with its settings.",
         layout=frames, panel=panel_frame("panel_two_ports"))
    ports = collect_ports(layout, cell, stackup=gui.read_stackup(STACKUP)[0])
    lines = [f"Ports in cell {cell.name}:"]
    for layer in sorted(ports):
        port = ports[layer]
        lines.append(f"  port {port.number:2d} (layer {layer}, {port.shapes} shape(s)): " +
                     (str(port.settings) if port.settings else "no settings"))
    lines += ["", f"Checked against {os.path.basename(STACKUP)}:"] + \
             (check_ports(ports, gui.read_stackup(STACKUP)[0]) or ["all complete"])
    box = pya.QMessageBox(mw)
    box.setWindowTitle("EM Export")
    box.setText("\n".join(lines))
    box.setIcon(pya.QMessageBox.Information)
    box.show()
    frames = move("zoom_out_ports", BOTTOM_PAD, whole, 16)
    shot("EM > Port Overview checks all ports against the stackup.", layout=frames[-1],
         panel=panel_frame("panel_two_ports"), dialog=save(box, "port_overview"))
    box.close()


def ground():
    panel().refresh(run_checks=True)
    expand(panel().ground_step)
    show = panel().show_ground
    show_at = at(show, dock, "panel")
    shot("Step 3: ground. The plug-in finds the ground net that the via ports reach, and checks for shorts.",
         chapter="Ground check", layout=layout_frame("ground_before"), panel=panel_frame("panel_ground"),
         pointer=[show_at])
    show.setChecked(True)
    panel()._show_ground(True)
    shot("Show in Layout outlines the ground net in green.", layout=layout_frame("ground_shown"),
         panel=panel_frame("panel_ground_shown"), pointer=[show_at])
    show.setChecked(False)
    panel()._show_ground(False)


Q1, RESISTORS = pya.DBox(-12, -4, 11, 6), pya.DBox(-30, -1, -22, 10)


def devices():
    panel().refresh()
    expand(panel().devices_step)
    unmark()
    table = panel().devices_table
    row = at(get(table.viewport), dock, "panel", table.visualItemRect(table.item(0, 1)))
    shot("Step 4: devices. The table lists the PDK transistors and resistors in the layout.", chapter="Devices",
         layout=layout_frame("devices_whole"), panel=panel_frame("panel_devices_before"), pointer=[row])
    frames = move("zoom_q1", mw.current_view().box(), Q1, 20)
    shot("Double-click a row to zoom to it: Q1, an npn13G2 with eight emitters.", layout=frames,
         panel=panel_frame("panel_devices_before"), pointer=[row])
    replace = find(panel().devices_step, "QPushButton", "Replace All")
    replace_at = at(replace, dock, "panel")
    panel().include_resistors.setChecked(True)
    panel()._replace_devices()
    expand(panel().devices_step)
    mark_ports()
    shot("Replace All: each device becomes a ground patch and one via port per terminal. The EM model sees only "
         "the wiring.", layout=layout_frame("q1_after"), panel=panel_frame("panel_devices_after"),
         pointer=[replace_at])
    frames = move("zoom_resistors", Q1, RESISTORS, 16)
    shot("Resistors too: the circuit simulator then uses the PDK resistor, with the right value.", layout=frames,
         panel=panel_frame("panel_devices_after"))


REGION, CUT = pya.DBox(-28.9, -11.275, 21.595, 20.63), pya.DBox(-31, 5, -20, 14)


def boundary():
    view, cv = view_cv()
    layout, cell = cv.layout(), cv.cell
    unmark()
    gui.backup_original(layout)
    cell.shapes(layout.layer(800, 0)).insert(REGION.to_itype(layout.dbu))
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
    whole = fit_box()
    mark_ports()
    shot("Step 5: the EM region. A box on layer 800 (or the selection) sets what goes into the EM model.",
         chapter="EM region", layout=layout_frame("region_whole"), panel=panel_frame("panel_region_proposed"))
    frames = move("zoom_cut", whole, CUT, 20)
    create = panel().create_button
    create_at = at(create, dock, "panel")
    shot("Where the box cuts a wire, the panel proposes a port at the cut.", layout=frames,
         panel=panel_frame("panel_region_proposed"), pointer=[create_at])
    panel()._create_proposed()
    expand()
    mark_ports()
    shot("Create Proposed Ports: the bias wire gets its port at the region edge.",
         layout=layout_frame("cut_created"), panel=panel_frame("panel_region_created"), pointer=[create_at])
    frames = move("zoom_out_region", CUT, whole, 16)
    shot("All ports: pads, device terminals and boundary ports, numbered for the EM model.", layout=frames,
         panel=panel_frame("panel_region_created"))


def export():
    gds = os.path.join(WORK, "cascode_em.gds")
    settings = gui._load_settings()
    settings["open_setupem"] = False
    gui._save_settings(settings)
    view, cv = view_cv()
    gui.set_layout_value(cv.layout(), gui.META_OUTPUT, gds, "EM export output file")
    unmark()
    button = find(panel(), "QPushButton", "Export for EM...")
    button_at = at(button, dock, "panel")
    dialog, export_at = modal(gui.export_region, "export_dialog", "Export")
    panel().refresh()
    expand()
    if dialog:
        shot("Step 6: export. A flat GDS with only the stackup layers and the ports, plus the setupEM settings.",
             chapter="Export", layout=layout_frame("export_ready"), panel=panel_frame("panel_exported"), dialog=dialog,
             pointer=[button_at] + ([export_at] if export_at else []))
    files = sorted(f for f in os.listdir(WORK) if f.startswith("cascode_em"))
    lines = [f"{name:32s} {os.path.getsize(os.path.join(WORK, name)):>10,d} bytes" for name in files]
    shot("The export: the EM layout, the .simcfg for setupEM and the port map for the circuit.",
         text={"title": "Exported files", "lines": lines, "mono": True})
    for tab, caption in (("ports", "setupEM opens the .simcfg: ports and stackup are already filled in."),
                         ("frequencies", "Set the sweep (from 0 Hz for a bias circuit), mesh, and run Palace.")):
        shot(caption, image={"file": f"frames/setupem/12_setupem_{tab}.png"})


def circuit():
    from klayout_em_export.circuit import CircuitDialog, run_wrapper
    portmap, snp = os.path.join(WORK, "cascode_em_portmap.json"), os.path.join(WORK, "cascode_em_dc.s15p")
    shutil.copyfile(SNP, snp)
    dialog = CircuitDialog(portmap)
    dialog.snp.setText(snp)
    dialog.python.setText(PYTHON)
    dialog._update_output()
    dialog.show()
    settle()
    simulator_at = at(dialog.simulator, dialog, "dialog")
    shot("After the Palace run: EM > Create Circuit takes the S-parameters and the port map.",
         chapter="Back to the circuit", layout=layout_frame("export_ready"), panel=panel_frame("panel_exported"),
         dialog=save(dialog, "circuit_dialog"), pointer=[simulator_at])
    dialog.simulator.showPopup()
    settle()
    popup = get(get(dialog.simulator.view).window)
    shot("Pick your simulator: ngspice, VACASK, Xyce or Spectre.", layout=layout_frame("export_ready"),
         panel=panel_frame("panel_exported"), dialog=save(dialog, "circuit_dialog"),
         popup=dict(save(popup, "simulator_choice"), below=simulator_at), pointer=[simulator_at])
    dialog.simulator.hidePopup()
    ok, report = run_wrapper(dialog.python.text, portmap, snp, dialog.output.text, "ngspice", "fit", "")
    output = dialog.output.text
    dialog.close()
    say(f"circuit: {ok} {output}")
    with open(output) as f:
        netlist = f.read().splitlines()
    shot("The result is one netlist: the EM model of the wiring as an equivalent circuit (snp2le), with the PDK "
         "transistors and resistors wired to its ports.", chapter="One netlist for co-simulation",
         text={"title": os.path.basename(output), "lines": netlist, "mono": True}, hold=4)
    images = os.path.join(REPO, "doc", "userguide", "images")
    shot("In your testbench it is one subcircuit: bias, signal, and every parasitic of the layout in one simulation.",
         image={"file": os.path.join(images, "13_full_circuit.png")}, hold=2)
    shot("ngspice with the cascode netlist: gain and match up to 200 GHz, with the PDK HBT models.",
         image={"file": os.path.join(images, "14_amplifier.png")}, hold=1)
    shot("", card={"title": "Outlook", "lines": OUTLOOK}, hold=4)


OUTLOOK = ["One netlist that combines everything for co-simulation:",
           "EM models of all critical blocks, with every PDK device put back",
           "Bias, gain, stability and large signal in your usual simulator",
           "VACASK: direct Touchstone import is planned"]

FILL_VIEW, HOLES_VIEW = pya.DBox(-150, 450, 100, 700), pya.DBox(-80, 520, 30, 620)


def fmd():
    mw.load_layout(os.path.join(WORK, "fmd_60ghz_pa.gds"), 1)
    view, cv = view_cv()
    view.max_hier()
    whole = fit_box()
    gui.set_stackup(cv.layout(), STACKUP)
    panel().refresh()
    expand()
    shot("A taped-out layout: a 60 GHz power amplifier with full dummy fill on every metal.",
         chapter="Dummy fill", layout=layout_frame("fmd_whole"), panel=panel_frame("panel_fmd"))
    frames = move("fmd_zoom_fill", whole, FILL_VIEW, 20)
    shot("Thousands of fill squares: slow to mesh, and they hide the circuit.", layout=frames,
         panel=panel_frame("panel_fmd"))
    message, ok_at = modal(gui.remove_dummy_fill, "fmd_fill_message", "OK")
    shot("EM > Remove Dummy Fill: floating shapes that repeat, on the stackup metals. Vias and devices stay; "
         "fill on layers outside the stackup (here GatPoly) is not exported anyway.",
         layout=layout_frame("fmd_fill_removed"), panel=panel_frame("panel_fmd"), dialog=message,
         pointer=[ok_at] if ok_at else [], hold=2)
    frames = move("fmd_zoom_holes", FILL_VIEW, HOLES_VIEW, 20)
    shot("Density holes (cheesing) in the wide metal: many small polygons for the mesher.", chapter="Cheesing",
         layout=frames, panel=panel_frame("panel_fmd"))
    message, ok_at = modal(gui.fill_and_merge, "fmd_holes_message", "OK")
    shot("EM > Fill Density Holes and Merge Metal: the holes are filled, the metal merged into few polygons.",
         layout=layout_frame("fmd_holes_filled"), panel=panel_frame("panel_fmd"), dialog=message,
         pointer=[ok_at] if ok_at else [], hold=2)
    edit = next(a for a in get(get(mw.menuBar).actions) if a.text.replace("&", "") == "Edit")
    bar = get(mw.menuBar)
    geometry = bar.actionGeometry(edit)
    corner = bar.mapTo(mw, pya.QPoint(geometry.left, geometry.bottom))
    menu = get(edit.menu)
    menu.popup(mw.mapToGlobal(corner))
    settle()
    undo = next((a for a in get(menu.actions) if a.text.replace("&", "").startswith("Undo")), None)
    shot("Each conversion is one step: Edit > Undo takes it back.", chapter="Safe to try",
         layout=layout_frame("fmd_holes_filled"), panel=panel_frame("panel_fmd"),
         dialog=dict(save(menu, "edit_menu"), x=corner.x, y=corner.y),
         pointer=[at(bar, mw, "layout", geometry)] + ([at(menu, menu, "dialog", menu.actionGeometry(undo))]
                                                      if undo else []))
    menu.close()
    files = sorted(f for f in os.listdir(WORK) if f.endswith((".gds", ".bak")) and not f.startswith("cascode_em"))
    lines = [f"{name:28s} {os.path.getsize(os.path.join(WORK, name)):>12,d} bytes" for name in files]
    shot("And your original file is kept: at its first change the plug-in copies it to <name>.gds.bak.",
         text={"title": "Next to your layout", "lines": lines, "mono": True})


def ending():
    shot("", card={"title": f"KLayout EM Export {__version__}",
                   "lines": ["Stackup, ports, ground check, devices, EM region, export",
                             "Dummy fill and cheesing cleaned up in place",
                             "Back to one netlist with the PDK devices",
                             "User's guide: doc/userguide in the plug-in"]}, hold=3)


def finish():
    with open(os.path.join(VIDEO, "manifest.json"), "w") as f:
        json.dump({"zoom": ZOOM, "layout_w": LAYOUT_W, "panel_w": PANEL_W, "height": HEIGHT, "shots": shots}, f, indent=1)
    say(f"done: {len(shots)} shots")
    log.close()
    if os.path.isfile(backup):
        shutil.move(backup, SETTINGS)
    elif os.path.isfile(SETTINGS):
        os.remove(SETTINGS)
    app.exit(0)


watchdog = pya.QTimer()
watchdog.singleShot = True
watchdog.timeout = finish
watchdog.start(900000)


def run():
    for name, function in (("clean copies", make_clean), ("title", title), ("start", open_start),
                           ("stackup", choose_stackup), ("ports", pad_ports), ("ground", ground),
                           ("devices", devices), ("boundary", boundary), ("export", export), ("circuit", circuit),
                           ("fmd", fmd), ("ending", ending)):
        say(f"-- {name}")
        step(name, function)
    finish()


# started from the event loop: with -rm the script runs before KLayout has given the menu bar its titles
starter = pya.QTimer()
starter.singleShot = True
starter.timeout = run
starter.start(3000)
