"""KLayout menu: Tools > EM Export."""
import json
import os
import shutil
import subprocess

import pya

from .export import PORT_LAYERS, export_flat, marker_box
from .ports import DIRECTIONS, PROP_KEY, PortSettings, check_ports, collect_ports, settings_of, simcfg_ports
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
    ports = collect_ports(layout, cell, None if box is None else box.to_itype(layout.dbu))
    simcfg_path = os.path.splitext(gds_path)[0] + ".simcfg"
    write_simcfg(simcfg_path, gds_path, stackup_path, result.cellname, ports=simcfg_ports(ports))
    problems = check_ports(ports, stackup.metal_names())
    port_text = f"{len(ports)} port(s)" + (":\n" + "\n".join(problems) + "\n(complete them in setupEM)"
                                           if problems else ", all complete")
    answer = pya.MessageBox.question(
        "EM Export", f"Region: {source}\n\n{result.report()}\nwrote {simcfg_path}\n{port_text}\n\nOpen in setupEM?",
        pya.MessageBox.Yes | pya.MessageBox.No)
    if answer == pya.MessageBox.Yes:
        open_in_setupem(simcfg_path, settings)
        _save_settings(settings)


def _saved_stackup(settings):
    """The last stackup, or ask for one. None if the user cancels or it cannot be read."""
    path = settings.get("stackup", "")
    if not os.path.isfile(path):
        path = _ask_stackup(settings)
        if not path:
            return None
        _save_settings(settings)
    try:
        return Stackup(path)
    except Exception as e:      # StackupError, XML syntax error
        pya.MessageBox.critical("EM Export", f"Cannot read the stackup:\n{e}", pya.MessageBox.Ok)
        return None


class PortDialog(pya.QDialog):
    def __init__(self, metals, current, count):
        super().__init__(pya.Application.instance().main_window())
        self.setWindowTitle("Port Settings")
        form = pya.QFormLayout(self)
        form.addRow(pya.QLabel(f"{count} port shape(s) selected"))
        self.direction = pya.QComboBox()
        self.direction.addItems(list(DIRECTIONS))
        self.from_layer, self.to_layer, self.target = pya.QComboBox(), pya.QComboBox(), pya.QComboBox()
        for box in (self.from_layer, self.to_layer, self.target):
            box.addItems(metals)
        self.z0 = pya.QLineEdit(f"{current.z0:g}")
        self.excited = pya.QCheckBox("excited (voltage 1)")
        self.excited.setChecked(current.voltage != 0)
        form.addRow("Direction", self.direction)
        form.addRow("From layer (via port)", self.from_layer)
        form.addRow("To layer (via port)", self.to_layer)
        form.addRow("Target layer (in-plane port)", self.target)
        form.addRow("Z0 (Ohm)", self.z0)
        form.addRow("", self.excited)
        buttons = pya.QDialogButtonBox(self)
        buttons.addButton(pya.QDialogButtonBox.Ok)
        buttons.addButton(pya.QDialogButtonBox.Cancel)
        buttons.accepted += self.accept
        buttons.rejected += self.reject
        form.addRow(buttons)
        for box, value in ((self.direction, current.direction), (self.from_layer, current.from_layer),
                           (self.to_layer, current.to_layer), (self.target, current.target)):
            if value:
                box.setCurrentText(value)
        self.direction.currentIndexChanged += lambda index: self._update()
        self._update()

    def _update(self):
        via = "Z" in self.direction.currentText
        self.from_layer.setEnabled(via)
        self.to_layer.setEnabled(via)
        self.target.setEnabled(not via)

    def result_settings(self):
        try:
            z0 = float(self.z0.text)
        except ValueError:
            z0 = 50.0
        return PortSettings(self.direction.currentText, self.from_layer.currentText, self.to_layer.currentText,
                            self.target.currentText, z0, 1.0 if self.excited.isChecked() else 0.0)


def _selected_port_shapes(view, cv):
    layout = cv.layout()
    shapes = []
    for obj in view.each_object_selected():
        if obj.cv_index != view.active_cellview_index or obj.is_cell_inst():
            continue
        info = layout.get_info(obj.layer)
        if info.layer in PORT_LAYERS and info.datatype == 0:
            shapes.append(obj.shape)
    return shapes


def port_settings():
    view, cv = _current()
    if view is None:
        return
    shapes = _selected_port_shapes(view, cv)
    if not shapes:
        pya.MessageBox.warning("EM Export", "Select one or more port shapes first (layers 201..299, datatype 0). "
                               "A via port is a line (path of width 0) or a thin box; an in-plane port is a box "
                               "that bridges the gap.", pya.MessageBox.Ok)
        return
    settings = _load_settings()
    stackup = _saved_stackup(settings)
    if stackup is None:
        return
    current = settings_of(shapes[0]) or PortSettings.decode(settings.get("last_port")) or PortSettings()
    dialog = PortDialog(stackup.metal_names(), current, len(shapes))
    if not dialog.exec_():
        return
    new = dialog.result_settings()
    view.transaction("Port settings")
    try:
        for shape in shapes:
            shape.set_property(PROP_KEY, new.encode())
    finally:
        view.commit()
    settings["last_port"] = new.encode()
    _save_settings(settings)
    problems = new.problems(stackup.metal_names())
    if problems:
        pya.MessageBox.warning("EM Export", "\n".join(problems), pya.MessageBox.Ok)


def port_overview():
    view, cv = _current()
    if view is None:
        return
    ports = collect_ports(cv.layout(), cv.cell)
    if not ports:
        pya.MessageBox.info("EM Export", f"Cell {cv.cell.name} has no port shapes on layers 201..299.", pya.MessageBox.Ok)
        return
    settings = _load_settings()
    lines = [f"Ports in cell {cv.cell.name}:"]
    for layer in sorted(ports):
        port = ports[layer]
        lines.append(f"  port {port.number:2d} (layer {layer}, {port.shapes} shape(s)): "
                     + (str(port.settings) if port.settings else "no settings"))
    if os.path.isfile(settings.get("stackup", "")):
        problems = check_ports(ports, Stackup(settings["stackup"]).metal_names())
        lines += ["", f"Checked against {os.path.basename(settings['stackup'])}:"] + (problems or ["all complete"])
    pya.MessageBox.info("EM Export", "\n".join(lines), pya.MessageBox.Ok)


_actions = []    # keep references, or the menu entries lose their handlers


def install_menu():
    menu = pya.Application.instance().main_window().menu()
    if not menu.is_valid("tools_menu.em_export"):
        menu.insert_menu("tools_menu.end", "em_export", "EM Export")
    for name, title, handler in (("export_region", "Export Region for EM...", export_region),
                                 ("mark_region", "Mark EM Region from Selection", mark_region),
                                 ("port_settings", "Port Settings...", port_settings),
                                 ("port_overview", "Port Overview", port_overview)):
        action = pya.Action()
        action.title = title
        action.on_triggered = handler
        _actions.append(action)
        menu.insert_item("tools_menu.em_export.end", name, action)
