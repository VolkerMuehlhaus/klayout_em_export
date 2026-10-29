"""KLayout menu: Tools > EM Export.

One stackup per layout, chosen once (menu, port dialog or export dialog) and used by every step. It is stored in the
layout's meta info, so it is saved with the layout, and as the default for new layouts.
"""
import json
import os
import shutil
import subprocess

import pya

from .export import PORT_LAYERS, export_flat, layer_summary, marker_box
from .locate import drawn_metals, metals_at
from .ports import (DIRECTIONS, PROP_KEY, PortSettings, check_ports, collect_ports, is_complete, ports_of, settings_of,
                    simcfg_ports)
from .selection import Selection
from .simcfg import write_simcfg
from .stackup import Stackup

EM_REGION = (800, 0)      # marker layer: a box on it keeps the export region in the layout
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")
META_STACKUP = "klayout_em_export.stackup"
META_OUTPUT = "klayout_em_export.output"


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


def _status(text, seconds=5):
    pya.Application.instance().main_window().message(text, seconds * 1000)


def _current():
    view = pya.Application.instance().main_window().current_view()
    if view is None or view.active_cellview().layout() is None:
        pya.MessageBox.critical("EM Export", "No layout is loaded.", pya.MessageBox.Ok)
        return None, None
    return view, view.active_cellview()


# ---------- stackup, one per layout ----------

def stackup_path(layout):
    """The layout's stackup, else the last one used, or "" if there is none (or the file is gone)."""
    path = layout.meta_info_value(META_STACKUP) if layout is not None else None
    if path and os.path.isfile(path):
        return path
    path = _load_settings().get("stackup", "")
    return path if os.path.isfile(path) else ""


def set_stackup(layout, path):
    if layout is not None:
        layout.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, path, "gds2palace stackup for EM export", True))
    settings = _load_settings()
    settings["stackup"] = path
    _save_settings(settings)


def ask_stackup(layout):
    path = pya.FileDialog.ask_open_file_name("gds2palace stackup (XML)", stackup_path(layout),
                                             "Stackup XML (*.xml);;All files (*)")
    if path:
        set_stackup(layout, path)
    return path


def read_stackup(path):
    """(Stackup, None) or (None, error text)."""
    try:
        return Stackup(path), None
    except Exception as e:      # missing file, StackupError, XML syntax error
        return None, str(e)


def choose_stackup():
    view, cv = _current()
    if view is not None and ask_stackup(cv.layout()):
        _status(f"EM stackup: {stackup_path(cv.layout())}", 10)


# ---------- region ----------

def mark_region():
    """Draw the bounding box of the selected shapes on the EM_REGION layer, to keep the region for re-export."""
    view, cv = _current()
    if view is None:
        return
    selection = Selection.from_view(view, cv)
    box = None if selection.is_empty() else selection.bbox()
    if box is None:
        pya.MessageBox.warning("EM Export", "Select one or more shapes first: their bounding box becomes the EM "
                               f"region (layer {EM_REGION[0]}/{EM_REGION[1]}).", pya.MessageBox.Ok)
        return
    layout = cv.layout()
    view.transaction("Mark EM region")
    try:
        li = layout.layer(*EM_REGION)
        cv.cell.shapes(li).clear()
        cv.cell.shapes(li).insert(box)
    finally:
        view.commit()
    view.add_missing_layers()


# ---------- setupEM ----------

def _setupem_command(settings):
    exe = settings.get("setupEM") or shutil.which("setupEM") or shutil.which("setupEM.bat")
    if exe and os.path.isfile(exe):
        return exe
    exe = pya.FileDialog.ask_open_file_name("Where is setupEM? (e.g. <venv>\\Scripts\\setupEM.exe)", "",
                                            "Programs (*.exe *.bat);;All files (*)")
    if exe:
        settings["setupEM"] = exe
        _save_settings(settings)
    return exe


def open_in_setupem(simcfg_path):
    exe = _setupem_command(_load_settings())
    if not exe:
        return
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)      # KLayout's own Python must not leak into setupEM's
    env.pop("PYTHONPATH", None)
    try:
        subprocess.Popen([exe, "-simcfg", simcfg_path], env=env)
    except OSError as e:
        pya.MessageBox.critical("EM Export", f"Failed to start setupEM:\n{e}", pya.MessageBox.Ok)


# ---------- export ----------

def _layers_text(keys):
    return ", ".join(f"{l}/{d}" for l, d in keys) or "none"


def _stackup_row(dialog, form, on_change):
    """Stackup label + Change... button as a form row; returns the label."""
    label = pya.QLabel()
    change = pya.QPushButton("Change...")
    change.clicked += on_change
    row = pya.QHBoxLayout()
    row.addWidget(label, 1)
    row.addWidget(change)
    form.addRow("Stackup", row)
    return label


class ExportDialog(pya.QDialog):
    """Everything about one export in one window: region, stackup, output file, layers, ports, setupEM.
    With a selection, the region is either its bounding box (cut at the box) or the selected shapes only."""

    def __init__(self, cv, box, source, selection=None):
        super().__init__(pya.Application.instance().main_window())
        self.em_layout, self.cell, self.box, self.source = cv.layout(), cv.cell, box, source
        self.selection = selection if selection is not None and not selection.is_empty() else None
        self.completed = None       # the selection with vias and ports added, for the current stackup
        self.stackup = None
        self.setWindowTitle("Export for EM")
        self.resize(640, 0)
        form = pya.QFormLayout(self)
        self.mode_box = self.mode_shapes = None
        if self.selection is not None:
            # a selection means "these shapes": that is the default, the bounding box is the deliberate choice
            self.mode_shapes = pya.QRadioButton("Selected shapes only (+ connecting vias and ports)")
            self.mode_box = pya.QRadioButton("Everything inside the selection's bounding box (cut at the box)")
            self.mode_shapes.setChecked(True)
            self.mode_box.toggled += lambda checked: self._refresh()
            column = pya.QVBoxLayout()
            column.addWidget(self.mode_shapes)
            column.addWidget(self.mode_box)
            form.addRow("Export", column)
        self.region = pya.QLabel()
        form.addRow("Region", self.region)
        self.stackup_label = _stackup_row(self, form, self._change_stackup)
        self.output = pya.QLineEdit(self._default_output(cv))
        browse = pya.QPushButton("Browse...")
        browse.clicked += self._browse
        row = pya.QHBoxLayout()
        row.addWidget(self.output, 1)
        row.addWidget(browse)
        form.addRow("Output GDS", row)
        form.addRow("", pya.QLabel("The .simcfg for setupEM is written next to it."))
        self.layers = pya.QLabel()
        self.layers.setWordWrap(True)
        form.addRow("Layers", self.layers)
        self.ports = pya.QLabel()
        self.ports.setWordWrap(True)
        form.addRow("Ports", self.ports)
        self.setupem = pya.QCheckBox("Open in setupEM after the export")
        self.setupem.setChecked(_load_settings().get("open_setupem", True))
        form.addRow("", self.setupem)
        buttons = pya.QDialogButtonBox(self)
        self.export_button = buttons.addButton("Export", pya.QDialogButtonBox.AcceptRole)
        buttons.addButton(pya.QDialogButtonBox.Cancel)
        buttons.accepted += self.accept
        buttons.rejected += self.reject
        form.addRow(buttons)
        self._refresh()

    def shapes_only(self):
        return self.mode_shapes is not None and self.mode_shapes.isChecked()

    def _default_output(self, cv):
        remembered = self.em_layout.meta_info_value(META_OUTPUT)
        if remembered:
            return remembered
        base = os.path.splitext(cv.filename())[0] if cv.filename() else os.path.join(os.path.expanduser("~"), self.cell.name)
        return base + "_em.gds"

    def _browse(self):
        path = pya.FileDialog.ask_save_file_name("Export EM layout", self.output.text, "GDSII (*.gds)")
        if path:
            self.output.setText(path)

    def _change_stackup(self):
        if ask_stackup(self.em_layout):
            self._refresh()

    def _refresh(self):
        shapes_only = self.shapes_only()
        self.region.setText("the selected shapes" if shapes_only else
                            f"{self.source}\n{self.box}" if self.box is not None else self.source)
        path = stackup_path(self.em_layout)
        self.stackup, error = read_stackup(path) if path else (None, "no stackup chosen yet")
        self.export_button.setEnabled(self.stackup is not None)
        if self.stackup is None:
            self.stackup_label.setText(f"<b>{error}</b>")
            self.layers.setText("choose a stackup first")
            self.ports.setText("")
            return
        self.stackup_label.setText(os.path.basename(path))
        self.stackup_label.setToolTip(path)
        if shapes_only:
            self.completed = self.selection.completed(self.stackup)
            kept, dropped = layer_summary(self.em_layout, self.cell, self.stackup, selection=self.completed)
            ports = ports_of(self.em_layout, self.cell, self.completed.ports, stackup=self.stackup)
            added = [f"{n} via(s) on layer {layer}" for layer, n in sorted(self.completed.added_vias.items())]
            if self.completed.added_ports:
                added.append(f"{self.completed.added_ports} port shape(s)")
            added_text = "\nadded to the selection: " + (", ".join(added) or "nothing")
        else:
            kept, dropped = layer_summary(self.em_layout, self.cell, self.stackup, self.box)
            clip = None if self.box is None else self.box.to_itype(self.em_layout.dbu)
            ports = collect_ports(self.em_layout, self.cell, clip, stackup=self.stackup)
            added_text = ""
        self.layers.setText(f"kept: {_layers_text(kept)}\ndropped (not in the stackup, or other purpose): "
                            f"{_layers_text(dropped)}{added_text}")
        problems = check_ports(ports, self.stackup)
        left_out = [ports[layer].number for layer in sorted(ports) if not is_complete(ports[layer])]
        if not ports:
            text = "no ports in the region (add them with the EM Port tool)"
        else:
            text = f"{len(ports)} port(s)" + ("" if problems else ", all complete")
            if left_out:
                text += (f"\nport(s) {', '.join(map(str, left_out))} without complete settings are left out of the "
                         ".simcfg (setupEM cannot load them); their shapes are exported. Set them with Port "
                         "Settings first.")
            if problems:
                text += "\n" + "\n".join(problems)
        self.ports.setText(text)


def export_region():
    view, cv = _current()
    if view is None:
        return
    layout, cell = cv.layout(), cv.cell
    selection = Selection.from_view(view, cv)
    box = None if selection.is_empty() else selection.bbox().to_dtype(layout.dbu)
    source = "bounding box of the selected shapes"
    if box is None:
        box = marker_box(layout, cell, EM_REGION)
        source = f"EM region box (layer {EM_REGION[0]}/{EM_REGION[1]})"
    if box is None:
        source = f"whole cell {cell.name} (nothing selected, no EM region box)"

    dialog = ExportDialog(cv, box, source, selection)
    while True:
        if not dialog.exec_():
            return
        gds_path = dialog.output.text.strip()
        problem = None
        if not gds_path.lower().endswith(".gds"):
            problem = "The output file must end with .gds."
        elif cv.filename() and os.path.normcase(os.path.abspath(gds_path)) == os.path.normcase(os.path.abspath(cv.filename())):
            problem = "The output file is the layout itself. Choose another file."
        if problem is None:
            if (os.path.exists(gds_path) and gds_path != layout.meta_info_value(META_OUTPUT) and
                    pya.MessageBox.question("EM Export", f"{gds_path} exists. Overwrite it?",
                                            pya.MessageBox.Yes | pya.MessageBox.No) != pya.MessageBox.Yes):
                continue
            break
        pya.MessageBox.warning("EM Export", problem, pya.MessageBox.Ok)

    stackup = dialog.stackup
    if dialog.shapes_only():
        result = export_flat(layout, cell, stackup, gds_path, selection=dialog.completed)
        ports = ports_of(layout, cell, dialog.completed.ports, stackup=stackup)
    else:
        result = export_flat(layout, cell, stackup, gds_path, box=box)
        ports = collect_ports(layout, cell, None if box is None else box.to_itype(layout.dbu), stackup=stackup)
    simcfg_path = os.path.splitext(gds_path)[0] + ".simcfg"
    port_list = simcfg_ports(ports)
    write_simcfg(simcfg_path, gds_path, stackup.path, result.cellname, ports=port_list)
    layout.add_meta_info(pya.LayoutMetaInfo(META_OUTPUT, gds_path, "EM export output file", True))
    settings = _load_settings()
    settings["open_setupem"] = dialog.setupem.isChecked()
    settings.pop("export_mode", None)      # no longer remembered: a selection always starts as "selected shapes"
    _save_settings(settings)
    _status(f"Exported {gds_path} and {os.path.basename(simcfg_path)} ({len(port_list)} of {len(ports)} port(s) "
            "in the .simcfg)", 10)
    if dialog.setupem.isChecked():
        open_in_setupem(simcfg_path)


# ---------- ports ----------

class PortDialog(pya.QDialog):
    """Port settings for one or more port shapes. Layer choices: the metals drawn at the port(s), or all stackup
    metals. available(stackup) gives the metals at the port; the stackup can be changed here."""

    def __init__(self, layout, available, current, count):
        super().__init__(pya.Application.instance().main_window())
        self.em_layout, self.available_for, self.current = layout, available, current
        self.setWindowTitle("Port Settings")
        form = pya.QFormLayout(self)
        form.addRow(pya.QLabel(f"{count} port shape(s)"))
        self.stackup_label = _stackup_row(self, form, self._change_stackup)
        self.at_port = pya.QLabel()
        self.at_port.setWordWrap(True)
        form.addRow("Drawn at the port", self.at_port)
        self.show_all = pya.QCheckBox("offer all stackup metals")
        self.show_all.toggled += lambda checked: self._fill()
        form.addRow("", self.show_all)
        self.direction = pya.QComboBox()
        self.direction.addItems(list(DIRECTIONS))
        self.from_layer, self.to_layer, self.target = pya.QComboBox(), pya.QComboBox(), pya.QComboBox()
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
        if current.direction in DIRECTIONS:
            self.direction.setCurrentText(current.direction)
        self.direction.currentIndexChanged += lambda index: self._update()
        self.stackup, self.available = None, []
        self._load_stackup()
        self._update()

    def _load_stackup(self):
        path = stackup_path(self.em_layout)
        self.stackup, error = read_stackup(path) if path else (None, "no stackup chosen yet")
        if self.stackup is None:
            self.available = []
            self.stackup_label.setText(f"<b>{error}</b>")
            self.at_port.setText("")
        else:
            self.stackup_label.setText(os.path.basename(path))
            self.stackup_label.setToolTip(path)
            self.available = self.available_for(self.stackup)
            self.at_port.setText(", ".join(self.available) or "no stackup metal (check the port position)")
        self._fill(initial=True)

    def _change_stackup(self):
        if ask_stackup(self.em_layout):
            self._load_stackup()

    def _fill(self, initial=False):
        available = self.available
        if self.stackup is None:
            names = []
        else:
            names = self.stackup.metal_names() if self.show_all.isChecked() or not available else available
        # keep the user's choice; else the stored settings if possible; else from = lowest, to = highest metal
        for box, stored, default in ((self.from_layer, self.current.from_layer, available[-1] if available else ""),
                                     (self.to_layer, self.current.to_layer, available[0] if available else ""),
                                     (self.target, self.current.target, available[0] if available else "")):
            chosen = "" if initial else box.currentText
            wanted = next((n for n in (chosen, stored, default) if n and n in names), names[0] if names else "")
            box.clear()
            box.addItems(names)
            box.setCurrentText(wanted)

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
    """[(shape, trans into the current cell)] of the selected port shapes."""
    layout = cv.layout()
    shapes = []
    for obj in view.each_object_selected():
        if obj.cv_index != view.active_cellview_index or obj.is_cell_inst():
            continue
        info = layout.get_info(obj.layer)
        if info.layer in PORT_LAYERS and info.datatype == 0:
            shapes.append((obj.shape, obj.trans()))
    return shapes


def edit_ports(view, cv, shapes, current=None):
    """Open the port dialog for [(shape, trans)] and store the result on the shapes. Returns True if applied."""
    layout, cell = cv.layout(), cv.cell
    if not stackup_path(layout) and not ask_stackup(layout):
        return False

    def available(stackup):
        common = None
        for shape, trans in shapes:
            here = metals_at(layout, cell, stackup, shape.bbox().transformed(trans))
            common = here if common is None else [n for n in common if n in here]
        return common or []

    settings = _load_settings()
    current = current or settings_of(shapes[0][0]) or PortSettings.decode(settings.get("last_port")) or PortSettings()
    dialog = PortDialog(layout, available, current, len(shapes))
    if not dialog.exec_():
        return False
    new = dialog.result_settings()
    view.transaction("Port settings")
    try:
        for shape, _ in shapes:
            shape.set_property(PROP_KEY, new.encode())
    finally:
        view.commit()
    settings["last_port"] = new.encode()
    _save_settings(settings)
    if dialog.stackup is None:
        problems = ["no readable stackup: the layers were not checked"]
    else:
        drawn = {name for name, _ in drawn_metals(dialog.stackup)}
        problems = new.problems(dialog.stackup.metal_names())
        problems += [f"{n} is not drawn at the port" for n in new.layer_names()
                     if n in drawn and n not in dialog.available]
    if problems:
        pya.MessageBox.warning("EM Export", "\n".join(problems), pya.MessageBox.Ok)
    return True


def port_settings():
    view, cv = _current()
    if view is None:
        return
    shapes = _selected_port_shapes(view, cv)
    if not shapes:
        pya.MessageBox.warning("EM Export", "Select one or more port shapes first (layers 201..299, datatype 0), "
                               "or create one with the EM Port tool.", pya.MessageBox.Ok)
        return
    edit_ports(view, cv, shapes)


def port_overview():
    view, cv = _current()
    if view is None:
        return
    path = stackup_path(cv.layout())
    stackup = read_stackup(path)[0] if path else None
    ports = collect_ports(cv.layout(), cv.cell, stackup=stackup)
    if not ports:
        pya.MessageBox.info("EM Export", f"Cell {cv.cell.name} has no port shapes on layers 201..299.", pya.MessageBox.Ok)
        return
    lines = [f"Ports in cell {cv.cell.name}:"]
    for layer in sorted(ports):
        port = ports[layer]
        lines.append(f"  port {port.number:2d} (layer {layer}, {port.shapes} shape(s)): "
                     + (str(port.settings) if port.settings else "no settings"))
    if stackup is not None:
        problems = check_ports(ports, stackup)
        lines += ["", f"Checked against {os.path.basename(stackup.path)}:"] + (problems or ["all complete"])
    pya.MessageBox.info("EM Export", "\n".join(lines), pya.MessageBox.Ok)


def port_tool():
    view, cv = _current()
    if view is not None:
        view.switch_mode("em_port_tool")


# ---------- menu ----------

_actions = []    # keep references, or the menu entries lose their handlers
_panel = None    # the EM panel (panel.EMPanel) in its dock, once created
_dock = None


def refresh_panel():
    if _panel is not None:
        _panel.refresh()


def show_panel():
    """Show the EM panel, docked at the right of the main window (created on first use)."""
    global _panel, _dock
    main_window = pya.Application.instance().main_window()
    if _dock is None:
        from .panel import EMPanel
        _dock = pya.QDockWidget("EM Export", main_window)
        _dock.setObjectName("klayout_em_export_panel")
        _panel = EMPanel(_dock)
        _dock.setWidget(_panel)
        main_window.addDockWidget(pya.Qt.RightDockWidgetArea, _dock)
    _dock.show()
    _panel.refresh()


def _with_refresh(handler):
    def run():
        handler()
        refresh_panel()
    return run


def install_menu():
    from .tool import PortToolFactory
    _actions.append(PortToolFactory())     # registers the EM Port tool in the toolbar
    menu = pya.Application.instance().main_window().menu()
    if not menu.is_valid("em_menu"):
        menu.insert_menu("help_menu", "em_menu", "EM")    # own menu in the menu bar, before Help
    entries = (("show_panel", "EM Panel", show_panel),
               None,
               ("choose_stackup", "Choose Stackup...", choose_stackup),
               None,
               ("port_tool", "EM Port Tool (click edge: via port, Shift+click gap: in-plane port)", port_tool),
               ("port_settings", "Port Settings...", port_settings),
               ("port_overview", "Port Overview", port_overview),
               None,
               ("mark_region", "Mark EM Region from Selection", mark_region),
               ("export_region", "Export for EM...", export_region))
    for n, entry in enumerate(entries):
        if entry is None:
            menu.insert_separator("em_menu.end", f"separator{n}")
            continue
        name, title, handler = entry
        action = pya.Action()
        action.title = title
        action.on_triggered = _with_refresh(handler)
        _actions.append(action)
        menu.insert_item("em_menu.end", name, action)
    show_panel()
