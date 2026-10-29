"""KLayout menu: Tools > EM Export."""
import json
import os
import shutil
import subprocess

import pya

from .export import export_flat, marker_box
from .simcfg import write_simcfg
from .stackup import Stackup

EM_REGION = (800, 0)      # marker layer: a box on it keeps the export region in the layout
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")


def _load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def _current():
    view = pya.Application.instance().main_window().current_view()
    if view is None or view.active_cellview().layout() is None:
        pya.MessageBox.critical("EM Export", "No layout is loaded.", pya.MessageBox.Ok)
        return None, None
    return view, view.active_cellview()


def _selection_box(view, cellview):
    """Bounding box (DBox, um) of the selected shapes, in the current cell, or None."""
    box = pya.DBox()
    for obj in view.each_object_selected():
        if obj.cv_index != view.active_cellview_index or obj.is_cell_inst():
            continue
        box += obj.shape.bbox().transformed(obj.trans()).to_dtype(cellview.layout().dbu)
    return box if not box.empty() else None


def mark_region():
    """Draw the bounding box of the selected shapes on the EM_REGION layer, to keep the region for re-export."""
    view, cv = _current()
    if view is None:
        return
    box = _selection_box(view, cv)
    if box is None:
        pya.MessageBox.warning("EM Export", "Select one or more shapes first: their bounding box becomes the EM "
                               f"region (layer {EM_REGION[0]}/{EM_REGION[1]}).", pya.MessageBox.Ok)
        return
    layout = cv.layout()
    view.transaction("Mark EM region")
    try:
        li = layout.layer(*EM_REGION)
        cv.cell.shapes(li).clear()
        cv.cell.shapes(li).insert(box.to_itype(layout.dbu))
    finally:
        view.commit()
    view.add_missing_layers()


def _ask_stackup(settings):
    path = pya.FileDialog.ask_open_file_name("gds2palace stackup (XML)", settings.get("stackup", ""),
                                             "Stackup XML (*.xml);;All files (*)")
    if path:
        settings["stackup"] = path
    return path


def _setupem_command(settings):
    exe = settings.get("setupEM") or shutil.which("setupEM") or shutil.which("setupEM.bat")
    if exe and os.path.isfile(exe):
        return exe
    exe = pya.FileDialog.ask_open_file_name("Where is setupEM? (e.g. <venv>\\Scripts\\setupEM.exe)", "",
                                            "Programs (*.exe *.bat);;All files (*)")
    if exe:
        settings["setupEM"] = exe
    return exe


def open_in_setupem(simcfg_path, settings):
    exe = _setupem_command(settings)
    if not exe:
        return
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)      # KLayout's own Python must not leak into setupEM's
    env.pop("PYTHONPATH", None)
    try:
        subprocess.Popen([exe, "-simcfg", simcfg_path], env=env)
    except OSError as e:
        pya.MessageBox.critical("EM Export", f"Failed to start setupEM:\n{e}", pya.MessageBox.Ok)


def export_region():
    view, cv = _current()
    if view is None:
        return
    layout, cell = cv.layout(), cv.cell
    box = _selection_box(view, cv)
    source = "the selected shapes"
    if box is None:
        box = marker_box(layout, cell, EM_REGION)
        source = f"the EM region box (layer {EM_REGION[0]}/{EM_REGION[1]})"
    if box is None:
        answer = pya.MessageBox.question(
            "EM Export", f"Nothing is selected and cell {cell.name} has no EM region box on layer "
            f"{EM_REGION[0]}/{EM_REGION[1]}.\n\nExport the whole cell?", pya.MessageBox.Yes | pya.MessageBox.No)
        if answer != pya.MessageBox.Yes:
            return
        source = "the whole cell"

    settings = _load_settings()
    stackup_path = _ask_stackup(settings)
    if not stackup_path:
        return
    try:
        stackup = Stackup(stackup_path)
    except Exception as e:      # StackupError, missing file, XML syntax error
        pya.MessageBox.critical("EM Export", f"Cannot read the stackup:\n{e}", pya.MessageBox.Ok)
        return

    base = os.path.splitext(cv.filename())[0] if cv.filename() else os.path.join(os.path.expanduser("~"), cell.name)
    gds_path = pya.FileDialog.ask_save_file_name("Export EM layout", base + "_em.gds", "GDSII (*.gds)")
    if not gds_path:
        return
    _save_settings(settings)

    result = export_flat(layout, cell, stackup, gds_path, box=box)
    simcfg_path = os.path.splitext(gds_path)[0] + ".simcfg"
    write_simcfg(simcfg_path, gds_path, stackup_path, result.cellname)
    answer = pya.MessageBox.question(
        "EM Export", f"Region: {source}\n\n{result.report()}\nwrote {simcfg_path}\n\nOpen in setupEM?",
        pya.MessageBox.Yes | pya.MessageBox.No)
    if answer == pya.MessageBox.Yes:
        open_in_setupem(simcfg_path, settings)
        _save_settings(settings)


_actions = []    # keep references, or the menu entries lose their handlers


def install_menu():
    menu = pya.Application.instance().main_window().menu()
    if not menu.is_valid("tools_menu.em_export"):
        menu.insert_menu("tools_menu.end", "em_export", "EM Export")
    for name, title, handler in (("export_region", "Export Region for EM...", export_region),
                                 ("mark_region", "Mark EM Region from Selection", mark_region)):
        action = pya.Action()
        action.title = title
        action.on_triggered = handler
        _actions.append(action)
        menu.insert_item("tools_menu.em_export.end", name, action)
