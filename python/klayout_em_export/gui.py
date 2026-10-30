"""KLayout menu: Tools > EM Export.

One stackup per layout, chosen once (menu, port dialog or export dialog) and used by every step. It is stored in the
layout's meta info, so it is saved with the layout, and as the default for new layouts.
"""
import json
import os
import shutil
import subprocess

import pya

from .export import PORT_LAYERS, export_flat, marker_box
from .locate import drawn_metals, metals_at
from .ports import (DIRECTIONS, PROP_KEY, PortSettings, check_ports, collect_ports, export_numbering, is_complete,
                    port_map, ports_of, settings_of, simcfg_ports)
from .selection import Selection
from .simcfg import write_simcfg
from .stackup import Stackup

EM_REGION = (800, 0)      # marker layer: a box on it keeps the export region in the layout
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")
META_STACKUP = "klayout_em_export.stackup"
META_OUTPUT = "klayout_em_export.output"
META_GROUND = "klayout_em_export.ground"    # JSON [[GDS layer, x, y], ...] in dbu: points in marked ground shapes
PORT_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "em_port.png")


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


# ---------- values per layout ----------
# Stored twice: in the layout's meta info (saved with the layout) and in the settings file under the layout's file
# name. Adding meta info does not mark the layout as modified, so KLayout does not ask to save it on close; the
# settings file keeps the value when the layout is closed without saving.

def _layout_file(layout):
    """File name of layout, found through the open views (a pya.Layout does not know it), or ""."""
    main_window = pya.Application.instance().main_window()
    if layout is None or main_window is None:
        return ""
    for i in range(main_window.views()):
        view = main_window.view(i)
        for j in range(view.cellviews()):
            if view.cellview(j).layout() is layout:
                return view.cellview(j).filename()
    return ""


def _file_key(path):
    return os.path.normcase(os.path.abspath(path))


def layout_value(layout, meta_name):
    """Value stored for this layout: its meta info, else the settings file's record for its file, else None."""
    value = layout.meta_info_value(meta_name) if layout is not None else None
    if value:
        return value
    path = _layout_file(layout)
    return _load_settings().get("layouts", {}).get(_file_key(path), {}).get(meta_name) if path else None


def set_layout_value(layout, meta_name, value, description):
    if layout is None:
        return
    layout.add_meta_info(pya.LayoutMetaInfo(meta_name, value, description, True))
    path = _layout_file(layout)
    if path:
        settings = _load_settings()
        settings.setdefault("layouts", {}).setdefault(_file_key(path), {})[meta_name] = value
        _save_settings(settings)


# ---------- stackup, one per layout ----------

def stackup_path(layout):
    """The layout's stackup, else the last one used, or "" if there is none (or the file is gone)."""
    path = layout_value(layout, META_STACKUP)
    if path and os.path.isfile(path):
        return path
    path = _load_settings().get("stackup", "")
    return path if os.path.isfile(path) else ""


def set_stackup(layout, path):
    set_layout_value(layout, META_STACKUP, path, "gds2palace stackup for EM export")
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


# ---------- ground ----------

def ground_seeds(layout):
    """[(GDS layer, Point)] of the marked ground shapes of this layout."""
    try:
        return [(int(l), pya.Point(int(x), int(y))) for l, x, y in json.loads(layout_value(layout, META_GROUND) or "[]")]
    except (TypeError, ValueError):
        return []


def _set_ground_seeds(layout, seeds):
    set_layout_value(layout, META_GROUND, json.dumps([[l, p.x, p.y] for l, p in seeds]),
                     "EM export: points in the marked ground shapes")


def mark_ground():
    """Mark the selected metal shapes as ground (added to earlier marks). A point inside each shape is stored."""
    view, cv = _current()
    if view is None:
        return
    layout = cv.layout()
    path = stackup_path(layout)
    stackup = read_stackup(path)[0] if path else None
    if stackup is None:
        pya.MessageBox.warning("EM Export", "Choose a stackup first.", pya.MessageBox.Ok)
        return
    from .connectivity import wiring
    traced = wiring(stackup)[0]
    seeds, skipped = ground_seeds(layout), 0
    for obj in view.each_object_selected():
        if obj.cv_index != view.active_cellview_index or obj.is_cell_inst() or obj.shape.is_text():
            skipped += 1
            continue
        info = layout.get_info(obj.layer)
        if info.layer not in traced or info.datatype != 0:
            skipped += 1
            continue
        polygon = obj.shape.polygon.transformed(obj.trans())
        inside = polygon.decompose_trapezoids()[0].bbox().center()    # a trapezoid is convex: its center is inside
        seeds.append((info.layer, inside))
    if len(seeds) == len(ground_seeds(layout)):
        pya.MessageBox.warning("EM Export", "Select one or more metal shapes of the ground first (shapes, not "
                               "instances; on the stackup's wiring layers).", pya.MessageBox.Ok)
        return
    _set_ground_seeds(layout, seeds)
    _status(f"{len(seeds)} ground mark(s)" + (f"; {skipped} selected object(s) skipped" if skipped else ""), 10)


def clear_ground():
    """Forget the marked ground shapes: the ground is found from the via ports again."""
    view, cv = _current()
    if view is not None:
        _set_ground_seeds(cv.layout(), [])


def create_boundary_ports(view, cv, crossings):
    from .boundary import create_ports
    stackup = read_stackup(stackup_path(cv.layout()))[0]
    return create_ports(view, cv.cell, stackup, crossings)


# ---------- region ----------

def find_layout_devices(layout, cell, stackup):
    """(devices, unknown) of cell, with the replaced ones marked (devices.find_devices, mark_replaced)."""
    from .devices import find_devices, mark_replaced
    devices, unknown = find_devices(layout, cell, stackup)
    return mark_replaced(layout, cell, devices), unknown


def replace_devices(view, cv, include_resistors=False):
    from .devices import replace
    layout, cell = cv.layout(), cv.cell
    stackup = read_stackup(stackup_path(layout))[0]
    if stackup is None:
        return {}
    try:
        return replace(view, cell, stackup, find_layout_devices(layout, cell, stackup)[0], include_resistors)
    except ValueError as e:
        pya.MessageBox.warning("EM Export", str(e), pya.MessageBox.Ok)
        return {}


def unreplace_devices(view, cv):
    from .devices import unreplace
    return unreplace(view, cv.cell)


def region_source(view, cv):
    """What the export uses as its region: (DBox or None for the whole cell, description, Selection or None).
    The selection counts only if it holds something besides port shapes: a selected port line (e.g. from
    clicking a port) never defines a region. Else the EM region box, else the whole cell."""
    layout, cell = cv.layout(), cv.cell
    selection = Selection.from_view(view, cv)
    if selection.regions:
        return selection.bbox().to_dtype(layout.dbu), "bounding box of the selected shapes", selection
    box = marker_box(layout, cell, EM_REGION)
    if box is not None:
        return box, f"EM region box (layer {EM_REGION[0]}/{EM_REGION[1]})", None
    return None, f"whole cell {cell.name} (nothing selected, no EM region box)", None


def mark_region():
    """Draw the bounding box of the selected shapes on the EM_REGION layer, to keep the region for re-export."""
    view, cv = _current()
    if view is None:
        return
    selection = Selection.from_view(view, cv)
    box = selection.bbox() if selection.regions else None      # port lines alone are no region
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


def last_simcfg(layout):
    """The .simcfg of this layout's last export, or None if there was none (or it is gone)."""
    gds = layout_value(layout, META_OUTPUT)
    path = os.path.splitext(gds)[0] + ".simcfg" if gds else None
    return path if path and os.path.isfile(path) else None


def open_last_in_setupem():
    """Open the last export of the current layout in setupEM, without exporting again."""
    view, cv = _current()
    if view is None:
        return
    path = last_simcfg(cv.layout())
    if path is None:
        pya.MessageBox.warning("EM Export", "This layout has not been exported yet (or its .simcfg is gone). "
                               "Use Export for EM first.", pya.MessageBox.Ok)
        return
    open_in_setupem(path)
    _status(f"setupEM: {path}", 10)


# ---------- export ----------

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
        remembered = layout_value(self.em_layout, META_OUTPUT)
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
        region = ("the selected shapes" if shapes_only else
                  f"{self.source}\n{self.box}" if self.box is not None else self.source)
        self.region.setText(region)
        path = stackup_path(self.em_layout)
        self.stackup, error = read_stackup(path) if path else (None, "no stackup chosen yet")
        self.export_button.setEnabled(self.stackup is not None)
        if self.stackup is None:
            self.stackup_label.setText(f"<b>{error}</b>")
            self.ports.setText("choose a stackup first")
            return
        self.stackup_label.setText(os.path.basename(path))
        self.stackup_label.setToolTip(path)
        if shapes_only:
            self.completed = self.selection.completed(self.stackup)
            ports = ports_of(self.em_layout, self.cell, self.completed.ports, stackup=self.stackup)
            names = {l.layer: l.name for l in self.stackup.layers}
            added = [f"{n} {names.get(layer, layer)}" for layer, n in sorted(self.completed.added_vias.items())]
            if self.completed.added_ports:
                added.append(f"{self.completed.added_ports} port shape(s)")
            self.region.setText(region + "\nadded: " + (", ".join(added) or "nothing (no vias between selected "
                                                                             "metals, no touching ports)"))
        else:
            clip = None if self.box is None else self.box.to_itype(self.em_layout.dbu)
            ports = collect_ports(self.em_layout, self.cell, clip, stackup=self.stackup)
        problems = check_ports(ports, self.stackup)
        from .connectivity import check_ground
        clip = None if self.box is None else self.box.to_itype(self.em_layout.dbu)
        shorted = check_ground(self.em_layout, self.cell, self.stackup, clip, ground_seeds(self.em_layout),
                               ports).shorted
        problems += [f"port {n}: both ends are on the same net (short circuit)" for n in shorted]
        left_out =[ports[layer].number for layer in sorted(ports) if not is_complete(ports[layer])]
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
            try:
                numbering = export_numbering(ports)
            except ValueError as e:
                text += f"\n{e}: the export is not possible"
                self.export_button.setEnabled(False)
            else:
                pairs = sorted((new - 200, ports[old].number) for old, new in numbering.items())
                if any(new != old for new, old in pairs):
                    text += ("\nnumbered without gaps for the export (exported/.snp port <- layout port): " +
                             ", ".join(f"{new} <- {old}" for new, old in pairs) + "; written to the port map file")
        self.ports.setText(text)


def export_region():
    view, cv = _current()
    if view is None:
        return
    layout, cell = cv.layout(), cv.cell
    box, source, selection = region_source(view, cv)

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
            if (os.path.exists(gds_path) and gds_path != layout_value(layout, META_OUTPUT) and
                    pya.MessageBox.question("EM Export", f"{gds_path} exists. Overwrite it?",
                                            pya.MessageBox.Yes | pya.MessageBox.No) != pya.MessageBox.Yes):
                continue
            break
        pya.MessageBox.warning("EM Export", problem, pya.MessageBox.Ok)

    stackup = dialog.stackup
    if dialog.shapes_only():
        ports = ports_of(layout, cell, dialog.completed.ports, stackup=stackup)
    else:
        ports = collect_ports(layout, cell, None if box is None else box.to_itype(layout.dbu), stackup=stackup)
    numbering = export_numbering(ports)      # ports 1..N without gaps, see export_numbering
    from .devices import device_shapes
    devices = find_layout_devices(layout, cell, stackup)[0]
    remove = device_shapes(layout, devices, stackup)    # replaced devices: their shapes below the pins
    if dialog.shapes_only():
        result = export_flat(layout, cell, stackup, gds_path, selection=dialog.completed, port_layers=numbering,
                             remove=remove)
    else:
        result = export_flat(layout, cell, stackup, gds_path, box=box, port_layers=numbering, remove=remove)
    simcfg_path = os.path.splitext(gds_path)[0] + ".simcfg"
    port_list = simcfg_ports(ports, numbering)
    kept = write_simcfg(simcfg_path, gds_path, stackup.path, result.cellname, ports=port_list)
    with open(os.path.splitext(gds_path)[0] + "_portmap.json", "w") as f:
        json.dump(port_map(ports, numbering), f, indent=2)
    set_layout_value(layout, META_OUTPUT, gds_path, "EM export output file")
    settings = _load_settings()
    settings["open_setupem"] = dialog.setupem.isChecked()
    settings.pop("export_mode", None)      # no longer remembered: a selection always starts as "selected shapes"
    _save_settings(settings)
    _status(f"Exported {gds_path} and {os.path.basename(simcfg_path)} ({len(port_list)} of {len(ports)} port(s) "
            "in the .simcfg" + ("; setupEM's other settings kept" if kept else "") + ")", 10)
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
        form.addRow("Drawn at the port" if count == 1 else f"Drawn at all {count} shapes", self.at_port)
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
               ("export_region", "Export for EM...", export_region),
               ("open_setupem", "Open Last Export in setupEM", open_last_in_setupem))
    for n, entry in enumerate(entries):
        if entry is None:
            menu.insert_separator("em_menu.end", f"separator{n}")
            continue
        name, title, handler = entry
        action = pya.Action()
        action.title = title
        if name == "port_tool":
            action.icon = PORT_ICON
        action.on_triggered = _with_refresh(handler)
        _actions.append(action)
        menu.insert_item("em_menu.end", name, action)
    show_panel()
