"""KLayout menu: Tools > EM Export.

One stackup per layout, chosen once (menu, port dialog or export dialog) and used by every step. It is stored in the
layout's meta info, so it is saved with the layout, and as the default for new layouts.
"""
import html
import json
import os
import shutil
import subprocess

import pya

from .export import PORT_LAYERS, marker_box
from .locate import drawn_metals, metals_at, via_layers
from .pipeline import EM_REGION, META_GROUND, META_OUTPUT, META_STACKUP, export_checks, export_em
from .ports import DIRECTIONS, PROP_KEY, PortSettings, check_ports, collect_ports, ports_of, settings_of
from .selection import Selection
from .stackup import Stackup

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".klayout_em_export.json")
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


BACKUP_SUFFIX = ".bak"              # <layout file>.bak: the original, before the plug-in's first change
_backup_checked = set()             # layout files checked in this session (backed up, or not an original)


def has_em_data(layout):
    """Whether layout holds anything the plug-in stores: its meta info, shapes with its properties (port settings
    200, boundary tag 201, device tag 202) on the port layers and the REF layer 300, or the EM region box. A layout
    without any of it is an original that the plug-in has never changed."""
    from .boundary import BOUNDARY_KEY
    from .ports import DEVICE_KEY
    if any(layout.meta_info_value(key) for key in (META_STACKUP, META_OUTPUT, META_GROUND)):
        return True
    keys = {PROP_KEY, BOUNDARY_KEY, DEVICE_KEY}
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        region = (info.layer, info.datatype) == tuple(EM_REGION)
        if not (region or info.layer in PORT_LAYERS or info.layer == 300):
            continue
        for c in layout.each_cell():
            for shape in c.shapes(li).each():
                if region:
                    return True
                if shape.prop_id and any(key in keys for key, _ in layout.properties(shape.prop_id)):
                    return True
    return False


def backup_original(layout):
    """Before the plug-in changes layout: if its file is an original (has_em_data is false, so saving would write the
    plug-in's data into it), copy the file as it is on disk to <file>.bak - never over an existing one, which keeps
    the oldest original. Checked once per file and session. Returns the backup's path, or None."""
    path = _layout_file(layout)
    if not path or path in _backup_checked:
        return None
    _backup_checked.add(path)
    backup = path + BACKUP_SUFFIX
    if not os.path.isfile(path) or os.path.exists(backup) or has_em_data(layout):
        return None
    try:
        shutil.copy2(path, backup)
    except OSError as e:
        _status(f"No backup of the original layout: {e}", 10)
        return None
    _status(f"Original layout kept as {backup}", 10)
    return backup


def native_path(path):
    """path with one kind of separator. KLayout's Python joins with "/" also on Windows (os.sep is "/" there), so a
    Windows path can come out as D:\\work\\guide/cascode_em.gds; decided by the path itself, not by os.sep: one with a
    drive letter or a UNC path (\\\\server\\share) gets backslashes throughout, any other path stays as it is (on Linux
    a backslash can be part of a file name)."""
    if path and (len(path) > 1 and path[1] == ":" and path[0].isalpha() or path.startswith("\\\\")):
        return path.replace("/", "\\")
    return path


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
    backup_original(layout)
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
    set_layout_value(layout, META_STACKUP, path, "stackup for EM export")
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
    region = marker_box(layout, cv.cell, EM_REGION)     # the point goes inside it, where the check looks
    region = None if region is None else pya.Region(region.to_itype(layout.dbu))
    seeds, skipped, shapes = ground_seeds(layout), 0, 0
    for obj in view.each_object_selected():
        if obj.cv_index != view.active_cellview_index or obj.is_cell_inst() or obj.shape.is_text():
            skipped += 1
            continue
        info = layout.get_info(obj.layer)
        if info.layer not in traced or info.datatype != 0:
            skipped += 1
            continue
        shapes += 1
        polygon = obj.shape.polygon.transformed(obj.trans())
        if region is not None:                          # its part in the EM region box, if it has one
            for part in (pya.Region(polygon) & region).each():
                polygon = part.dup()
                break
        inside = polygon.decompose_trapezoids()[0].bbox().center()    # a trapezoid is convex: its center is inside
        if (info.layer, inside) not in seeds:           # marking the same shape again adds nothing
            seeds.append((info.layer, inside))
    if not shapes:
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


def remove_dummy_fill():
    """Remove the dummy metal fill of the current cell, in one undo step (dummyfill.py)."""
    view, cv = _current()
    if view is None:
        return
    layout = cv.layout()
    stackup = read_stackup(stackup_path(layout))[0] if stackup_path(layout) else None
    if stackup is None:
        pya.MessageBox.warning("EM Export", "Choose a stackup first.", pya.MessageBox.Ok)
        return
    from .dummyfill import MINCOUNT, remove_dummy_fill as remove
    names = {l.layer: l.name for l in stackup.layers}
    _status("Removing dummy fill...", 0)
    backup_original(layout)
    view.transaction("Remove dummy fill")
    try:
        removed, cells = remove(layout, cv.cell, stackup)
    finally:
        view.commit()
    if not removed:
        pya.MessageBox.info("EM Export", f"No dummy fill found in {cv.cell.name}: no floating shapes on a stackup "
                            f"metal that repeat {MINCOUNT} times or more.", pya.MessageBox.Ok)
        return
    lines = [f"{names.get(l, l)} ({l}/{d}): {n}" for (l, d), n in sorted(removed.items())]
    pya.MessageBox.info("EM Export", f"Removed {sum(removed.values())} dummy fill shapes from {cv.cell.name}" +
                        (f" ({cells} empty fill cells deleted)" if cells else "") + ":\n" + "\n".join(lines) +
                        "\n\nFill is a floating shape on a stackup metal (no via, label, port or device touching "
                        f"it) whose size repeats {MINCOUNT} times or more; vias are never removed. Edit > Undo takes "
                        "it back.", pya.MessageBox.Ok)


def fill_and_merge():
    """Fill the density holes and merge the metal of the current cell, in one undo step (density.py)."""
    view, cv = _current()
    if view is None:
        return
    layout = cv.layout()
    stackup = read_stackup(stackup_path(layout))[0] if stackup_path(layout) else None
    if stackup is None:
        pya.MessageBox.warning("EM Export", "Choose a stackup first.", pya.MessageBox.Ok)
        return
    from .density import MINCOUNT, fill_and_merge as convert
    backup_original(layout)
    view.transaction("Fill density holes and merge metal")
    try:
        done, cells = convert(layout, cv.cell, stackup)
    finally:
        view.commit()
    lines = [f"{name}: {r.filled} holes filled" + (f" ({r.kept} other kept)" if r.kept else "") +
             f", {r.before} -> {r.after} polygons" for name, r in done.items() if r.filled or r.after != r.before]
    head = (f"{sum(r.filled for r in done.values())} density holes filled (a hole size found {MINCOUNT} times or "
            f"more), metal merged in {cv.cell.name}" +
            (f", with the metal of {cells} subcell(s) (repeated, or holding filled holes; their vias stay)"
             if cells else "") + ":")
    pya.MessageBox.info("EM Export", head + "\n" + ("\n".join(lines) or "nothing to change") +
                        "\n\nEdit > Undo takes it back. Do not tape out this layout once saved: the fill breaks "
                        "the density rules.", pya.MessageBox.Ok)


def create_boundary_ports(view, cv, crossings):
    from .boundary import create_ports
    stackup = read_stackup(stackup_path(cv.layout()))[0]
    backup_original(cv.layout())
    return create_ports(view, cv.cell, stackup, crossings)


# ---------- region ----------

def layout_technology(layout):
    """(technology module, reason) of the layout: the settings file's "technology" if set, else from the layout
    (tech.for_layout)."""
    from .tech import for_layout
    return for_layout(layout, _load_settings().get("technology"))


def find_layout_devices(layout, cell, stackup):
    """(devices, unknown) of cell, with the replaced ones marked (devices.find_devices, mark_replaced)."""
    from .devices import find_devices, mark_replaced
    devices, unknown = find_devices(layout, cell, stackup, layout_technology(layout)[0])
    return mark_replaced(layout, cell, devices), unknown


def replace_devices(view, cv, include_resistors=False):
    from .devices import replace
    layout, cell = cv.layout(), cv.cell
    stackup = read_stackup(stackup_path(layout))[0]
    if stackup is None:
        return {}
    backup_original(layout)
    try:
        return replace(view, cell, stackup, find_layout_devices(layout, cell, stackup)[0], include_resistors)
    except ValueError as e:
        pya.MessageBox.warning("EM Export", str(e), pya.MessageBox.Ok)
        return {}


def unreplace_devices(view, cv):
    from .devices import unreplace
    backup_original(cv.layout())
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
    backup_original(layout)
    view.transaction("Mark EM region")
    try:
        li = layout.layer(*EM_REGION)
        cv.cell.shapes(li).clear()
        cv.cell.shapes(li).insert(box)
    finally:
        view.commit()
    view.add_missing_layers()


# ---------- setupEM / EMStudio ----------

# The programs that open the exported .simcfg. EMStudio imports it as a Palace or OpenEMS model (it asks which;
# File > Import setupEM Config);
# when <name>.py exists next to it, EMStudio updates only that model's ports, layout file, stackup, cell and purpose.
TOOLS = ("setupEM", "EMStudio")
_TOOL_HINT = {"setupEM": "e.g. <venv>\\Scripts\\setupEM.exe or <venv>/bin/setupEM",
              "EMStudio": "e.g. C:\\Program Files\\EMStudio\\EMStudio.exe or <EMStudio folder>/EMStudio"}


def open_with(settings=None):
    """The program that opens exports: 'setupEM' (default) or 'EMStudio', as last chosen in the export dialog."""
    tool = (settings if settings is not None else _load_settings()).get("open_with", "setupEM")
    return tool if tool in TOOLS else "setupEM"


def launch_command(tool, exe, simcfg_path):
    """Command line that opens simcfg_path in tool (setupEM: -simcfg <file>, EMStudio: the file itself)."""
    return [exe, "-simcfg", simcfg_path] if tool == "setupEM" else [exe, simcfg_path]


def _program(tool, settings):
    """Path of tool's program: the one chosen before, else on PATH, else asked for (and remembered)."""
    exe = settings.get(tool) or shutil.which(tool) or shutil.which(tool + ".bat")
    if exe and os.path.isfile(exe):
        return exe
    programs = "Programs (*.exe *.bat);;All files (*)" if os.name == "nt" else "All files (*)"
    exe = pya.FileDialog.ask_open_file_name(f"Where is {tool}? ({_TOOL_HINT[tool]})", "", programs)
    if exe:
        settings[tool] = exe
        _save_settings(settings)
    return exe


def open_simcfg(simcfg_path, tool=None):
    """Open simcfg_path in tool (default: open_with())."""
    settings = _load_settings()
    tool = tool or open_with(settings)
    exe = _program(tool, settings)
    if not exe:
        return
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)      # KLayout's own Python must not leak into the Pythons these programs run
    env.pop("PYTHONPATH", None)
    try:
        process = subprocess.Popen(launch_command(tool, exe, simcfg_path), env=env)
    except OSError as e:
        pya.MessageBox.critical("EM Export", f"Failed to start {tool}:\n{e}", pya.MessageBox.Ok)
        return
    # a program that cannot open the file ends at once with an error code (an EMStudio without the .simcfg
    # import exits with 1), which would go unnoticed: look again after QUICK_EXIT_MS, without blocking KLayout
    timer = pya.QTimer()
    timer.setSingleShot(True)

    def check():
        _timers.remove(timer)
        text = quick_exit_text(tool, process.poll())
        if text:
            pya.MessageBox.warning("EM Export", text, pya.MessageBox.Ok)
    timer.timeout += check
    _timers.append(timer)               # kept alive until it fires
    timer.start(QUICK_EXIT_MS)


QUICK_EXIT_MS = 2000
_timers = []


def quick_exit_text(tool, returncode):
    """The message for a program that ended at once (returncode from poll(): None while it runs), else None."""
    if returncode is None or returncode == 0:
        return None
    return f"{tool} ended at once (exit code {returncode}): this {tool} cannot open a .simcfg"


def last_simcfg(layout):
    """The .simcfg of this layout's last export, or None if there was none (or it is gone)."""
    gds = layout_value(layout, META_OUTPUT)
    path = os.path.splitext(gds)[0] + ".simcfg" if gds else None
    return path if path and os.path.isfile(path) else None


def open_last_export(tool=None):
    """Open the last export of the current layout in tool (default: open_with()), without exporting again."""
    view, cv = _current()
    if view is None:
        return
    path = last_simcfg(cv.layout())
    if path is None:
        pya.MessageBox.warning("EM Export", "This layout has not been exported yet (or its .simcfg is gone). "
                               "Use Export for EM first.", pya.MessageBox.Ok)
        return
    tool = tool or open_with()
    open_simcfg(path, tool)
    _status(f"{tool}: {path}", 10)


# ---------- export ----------

OK, WARN, ERROR = ("✓", "#1a8f1a"), ("⚠", "#c87800"), ("✗", "#c00000")     # status marks, also in the panel


def _marked(state, text, detail=""):
    """Rich text: the status mark (none for OK), the text and, if given, a smaller grey line below (plain text)."""
    mark = html.escape(text) if state == OK else \
        f'<span style="color:{state[1]}; font-weight:bold">{state[0]}</span>&nbsp; {html.escape(text)}'
    if detail:
        mark += f'<br><span style="color:#777">{html.escape(detail).replace(chr(10), "<br>")}</span>'
    return mark


def add_form_row(dialog, form, *args):
    """form.addRow(*args), with the dialog keeping the widgets and layouts of the row. KLayout 0.30.12 deletes a
    widget or layout that Python no longer refers to, also after addRow (0.30.5 kept it): rows went missing, and a
    combo box was left over the whole dialog."""
    dialog._form_rows = getattr(dialog, "_form_rows", []) + [args]
    form.addRow(*args)


def _stackup_row(dialog, form, on_change, title="Stackup"):
    """Stackup label + Change... button as a form row; returns the label."""
    label = pya.QLabel()
    change = pya.QPushButton("Change...")
    change.clicked += on_change
    row = pya.QHBoxLayout()
    row.addWidget(label, 1)
    row.addWidget(change)
    add_form_row(dialog, form, title, row)
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
        form.setLabelAlignment(pya.Qt.AlignRight | pya.Qt.AlignTop)
        self.mode_box = self.mode_shapes = None
        if self.selection is not None:
            # a selection means "these shapes": that is the default, the bounding box is the deliberate choice
            self.mode_shapes = pya.QRadioButton("Selected shapes only (+ connecting vias and ports)")
            self.mode_box = pya.QRadioButton("Everything inside their bounding box (cut at the box)")
            self.mode_shapes.setChecked(True)
            self.mode_box.toggled += lambda checked: self._refresh()
            column = pya.QVBoxLayout()
            column.addWidget(self.mode_shapes)
            column.addWidget(self.mode_box)
            add_form_row(self, form, "<b>Export</b>", column)
        self.region = pya.QLabel()
        self.region.setWordWrap(True)
        add_form_row(self, form, "<b>Region</b>", self.region)
        self.stackup_label = _stackup_row(self, form, self._change_stackup, "<b>Stackup</b>")
        self.output = pya.QLineEdit(self._default_output(cv))
        self.output.setToolTip("The .simcfg (for setupEM and EMStudio) and the port map are written next to it, "
                               "with the same name")
        browse = pya.QPushButton("Browse...")
        browse.clicked += self._browse
        row = pya.QHBoxLayout()
        row.addWidget(self.output, 1)
        row.addWidget(browse)
        add_form_row(self, form, "<b>Output</b>", row)
        companions = pya.QLabel('<span style="color:#777">+ .simcfg and _portmap.json with the same name</span>')
        add_form_row(self, form, "", companions)
        self.ports = pya.QLabel()
        self.ports.setWordWrap(True)
        add_form_row(self, form, "<b>Ports</b>", self.ports)
        line = pya.QFrame()
        line.setFrameShape(pya.QFrame.HLine)
        line.setFrameShadow(pya.QFrame.Sunken)
        add_form_row(self, form, line)
        settings = _load_settings()
        self.open_after = pya.QCheckBox("Open in")
        self.open_after.setChecked(settings.get("open_setupem", True))
        self.open_tool = pya.QComboBox()
        self.open_tool.addItems(list(TOOLS))
        self.open_tool.setCurrentIndex(TOOLS.index(open_with(settings)))
        self.open_tool.setToolTip("EMStudio imports the .simcfg as a Palace or OpenEMS model (it asks which); when "
                                  "<name>.py exists next to it, only that model's ports, layout file, stackup, cell "
                                  "and purpose are updated")
        buttons = pya.QDialogButtonBox(self)
        self.export_button = buttons.addButton("Export", pya.QDialogButtonBox.AcceptRole)
        buttons.addButton(pya.QDialogButtonBox.Cancel)
        buttons.accepted += self.accept
        buttons.rejected += self.reject
        row = pya.QHBoxLayout()
        row.addWidget(self.open_after)
        row.addWidget(self.open_tool)
        row.addStretch(1)
        row.addWidget(buttons)
        add_form_row(self, form, row)
        self._refresh()

    def shapes_only(self):
        return self.mode_shapes is not None and self.mode_shapes.isChecked()

    def _default_output(self, cv):
        remembered = layout_value(self.em_layout, META_OUTPUT)
        if remembered:
            return native_path(remembered)
        base = os.path.splitext(cv.filename())[0] if cv.filename() else os.path.join(os.path.expanduser("~"), self.cell.name)
        return native_path(base + "_em.gds")

    def _browse(self):
        path = pya.FileDialog.ask_save_file_name("Export EM layout", self.output.text, "GDSII (*.gds)")
        if path:
            self.output.setText(native_path(path))

    def _change_stackup(self):
        if ask_stackup(self.em_layout):
            self._refresh()

    def _region_text(self):
        """(headline, detail) of the region: the source's parenthesis goes into the detail line."""
        head, _, rest = self.source.partition(" (")
        detail = rest.rstrip(")")
        if self.box is not None:
            size = f"{self.box.width():g} × {self.box.height():g} µm"
            detail = f"{size} at ({self.box.left:g}, {self.box.bottom:g})" + (f", {detail}" if detail else "")
        return head[:1].upper() + head[1:], detail

    def _refresh(self):
        shapes_only = self.shapes_only()
        head, detail = ("Selected shapes", "") if shapes_only else self._region_text()
        self.region.setText(_marked(OK, head, detail))
        path = stackup_path(self.em_layout)
        self.stackup, error = read_stackup(path) if path else (None, "no stackup chosen yet")
        self.export_button.setEnabled(self.stackup is not None)
        if self.stackup is None:
            self.stackup_label.setText(_marked(ERROR, error))
            self.ports.setText(_marked(ERROR, "choose a stackup first"))
            return
        self.stackup_label.setText(_marked(OK, os.path.basename(path)))
        self.stackup_label.setToolTip(path)
        if shapes_only:
            self.completed = self.selection.completed(self.stackup)
            ports = ports_of(self.em_layout, self.cell, self.completed.ports, stackup=self.stackup)
            names = {l.layer: l.name for l in self.stackup.layers}
            added = [f"{n} {names.get(layer, layer)}" for layer, n in sorted(self.completed.added_vias.items())]
            if self.completed.added_ports:
                added.append(f"{self.completed.added_ports} port shape(s)")
            if self.completed.added_patches:
                added.append(f"{self.completed.added_patches} REF patch(es) of replaced devices")
            self.region.setText(_marked(OK, head, "added: " + (", ".join(added) or "nothing (no vias between the "
                                                                                    "selected metals, no ports)")))
        else:
            clip = None if self.box is None else self.box.to_itype(self.em_layout.dbu)
            ports = collect_ports(self.em_layout, self.cell, clip, stackup=self.stackup)
        devices = find_layout_devices(self.em_layout, self.cell, self.stackup)[0]
        checks = export_checks(self.em_layout, self.cell, self.stackup, ports, devices,
                               ground_seeds(self.em_layout), self.box)
        problems, left_out = checks["problems"], checks["left_out"]
        if not ports:
            self.ports.setText(_marked(WARN, "no ports in the region", "add them with the EM Port tool"))
            return
        notes = []
        if left_out:
            notes.append(f"port(s) {', '.join(map(str, left_out))}: no settings, left out of the .simcfg "
                         "(their shapes are exported)")
        # "no port settings" of a left-out port is already said in the line above
        notes += [p for p in problems if not p.endswith(": no port settings")]
        if checks["numbering_error"]:
            notes.append(f"{checks['numbering_error']}: the export is not possible")
            self.export_button.setEnabled(False)
        elif checks["renumbered"]:
            notes.append("renumbered for the export (.snp port ← layout port): " +
                         ", ".join(f"{new} ← {old}" for new, old in checks["renumbered"]))
        state = ERROR if checks["numbering_error"] else WARN if problems or left_out else OK
        headline = f"{len(ports)} port(s)" + ("" if problems or left_out else ", all complete")
        self.ports.setText(_marked(state, headline, "\n".join("• " + n for n in notes)))


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
        gds_path = native_path(dialog.output.text.strip())
        problem = None
        if not gds_path.lower().endswith(".gds"):
            problem = "The output file must end with .gds."
        elif cv.filename() and os.path.normcase(os.path.abspath(gds_path)) == os.path.normcase(os.path.abspath(cv.filename())):
            problem = "The output file is the layout itself. Choose another file."
        if problem is None:
            if (os.path.exists(gds_path) and gds_path != native_path(layout_value(layout, META_OUTPUT)) and
                    pya.MessageBox.question("EM Export", f"{gds_path} exists. Overwrite it?",
                                            pya.MessageBox.Yes | pya.MessageBox.No) != pya.MessageBox.Yes):
                continue
            break
        pya.MessageBox.warning("EM Export", problem, pya.MessageBox.Ok)

    result = export_em(layout, cell, dialog.stackup, gds_path, layout_technology(layout)[0], box=box,
                       selection=dialog.completed if dialog.shapes_only() else None, seeds=ground_seeds(layout))
    simcfg_path, port_list, kept = result["simcfg"], result["port_list"], result["kept_settings"]
    set_layout_value(layout, META_OUTPUT, gds_path, "EM export output file")
    settings = _load_settings()
    open_after = dialog.open_after.isChecked()
    tool = TOOLS[dialog.open_tool.currentIndex]
    settings["open_setupem"] = open_after               # "open after the export", whichever program
    settings["open_with"] = tool
    settings.pop("export_mode", None)      # no longer remembered: a selection always starts as "selected shapes"
    _save_settings(settings)
    _status(f"Exported {gds_path} and {os.path.basename(simcfg_path)} ({len(port_list)} of {result['ports']} port(s) "
            "in the .simcfg" + ("; setupEM's other settings kept" if kept else "") + ")", 10)
    _warn_stale_scripts(gds_path, simcfg_path, port_list, tool if open_after else None)
    if open_after:
        open_simcfg(simcfg_path, tool)


def updated_on_open(stale, simcfg_path, tool):
    """The stale scripts (stale_scripts) left to warn about when simcfg_path is opened in tool right after the
    export: EMStudio updates <name>.py next to the .simcfg on import (ports, layout file, stackup, cell, purpose),
    so that one is not stale for long. tool None: nothing is opened."""
    if tool != "EMStudio":
        return stale
    model = os.path.normcase(os.path.abspath(os.path.splitext(simcfg_path)[0] + ".py"))
    return [(path, diff) for path, diff in stale if os.path.normcase(os.path.abspath(path)) != model]


def _warn_stale_scripts(gds_path, simcfg_path, port_list, opened_in=None):
    """Warn about model scripts that read the exported GDS but still have other ports (made before a re-export).
    opened_in: the program the export opens right now (see updated_on_open)."""
    from .modelcheck import stale_scripts
    folders = [os.path.dirname(os.path.abspath(gds_path))]
    try:
        with open(simcfg_path) as f:
            sim_path = json.load(f).get("saved_values", {}).get("sim_path")
        if sim_path:
            folders.append(sim_path)
    except (OSError, ValueError):
        pass
    stale = updated_on_open(stale_scripts(gds_path, port_list, folders), simcfg_path, opened_in)
    if not stale:
        return
    # short message, the port list and the how-to behind "Show Details..."
    names = [os.path.basename(path) for path, _ in stale]
    details = [os.path.basename(path) + ":\n  " + "\n  ".join(diff) for path, diff in stale]
    details.append(
        "Run as they are, these scripts simulate the new layout with their old ports, so their S-parameters do "
        "not match the new port map.\n\n"
        "setupEM: \"Continue with the script\" opens the script for editing in place and takes the ports, GDSII "
        "file, stackup and cell from the export. Your other settings (frequencies, mesh, ...) and your own code "
        "stay. Create Model writes the script.\n\n"
        "EMStudio: File > Import setupEM Config with the .simcfg; <name>.py next to it takes the new ports.")
    box = pya.QMessageBox(pya.Application.instance().main_window())
    box.setWindowTitle("EM Export")
    box.setIcon(pya.QMessageBox.Warning)
    if len(stale) == 1:
        box.setText(f"The model script {names[0]} has other ports than this export ({len(stale[0][1])} differ).")
    else:
        box.setText(f"{len(stale)} model scripts have other ports than this export: {', '.join(names)}.")
    box.setInformativeText("Before you simulate: open this export in setupEM, choose \"Continue with the script\" "
                           "and press Create Model. In EMStudio: import the .simcfg.")
    box.setDetailedText("\n\n".join(details))
    box.setStandardButtons(pya.QMessageBox.Ok)
    box.exec_()


# ---------- ports ----------

class PortDialog(pya.QDialog):
    """Port settings for one or more port shapes. Layer choices: the metals drawn at the port(s), or all stackup
    metals. available(stackup) gives the metals at the port; the stackup can be changed here."""

    def __init__(self, layout, available, current, count):
        super().__init__(pya.Application.instance().main_window())
        self.em_layout, self.available_for, self.current = layout, available, current
        self.setWindowTitle("Port Settings")
        form = pya.QFormLayout(self)
        add_form_row(self, form, pya.QLabel(f"{count} port shape(s)"))
        self.stackup_label = _stackup_row(self, form, self._change_stackup)
        self.at_port = pya.QLabel()
        self.at_port.setWordWrap(True)
        add_form_row(self, form, "Drawn at the port" if count == 1 else f"Drawn at all {count} shapes", self.at_port)
        self.show_all = pya.QCheckBox("offer all stackup metals")
        self.show_all.toggled += lambda checked: self._fill()
        add_form_row(self, form, "", self.show_all)
        self.direction = pya.QComboBox()
        self.direction.addItems(list(DIRECTIONS))
        self.from_layer, self.to_layer, self.target = pya.QComboBox(), pya.QComboBox(), pya.QComboBox()
        self.z0 = pya.QLineEdit(f"{current.z0:g}")
        self.excited = pya.QCheckBox("excited (voltage 1)")
        self.excited.setChecked(current.voltage != 0)
        add_form_row(self, form, "Direction", self.direction)
        add_form_row(self, form, "From layer (via port)", self.from_layer)
        add_form_row(self, form, "To layer (via port)", self.to_layer)
        add_form_row(self, form, "Target layer (in-plane port)", self.target)
        add_form_row(self, form, "Z0 (Ohm)", self.z0)
        add_form_row(self, form, "", self.excited)
        buttons = pya.QDialogButtonBox(self)
        buttons.addButton(pya.QDialogButtonBox.Ok)
        buttons.addButton(pya.QDialogButtonBox.Cancel)
        buttons.accepted += self.accept
        buttons.rejected += self.reject
        add_form_row(self, form, buttons)
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
            # a via port needs two metals: with fewer at the port, offer them all
            names = self.stackup.metal_names() if self.show_all.isChecked() or len(available) < 2 else available
        # keep the user's choice; else the stored from and to if both are offered and differ; else as the EM Port
        # tool: from the top metal at the port down to the next metal below (at the port, else in the stackup)
        top = available[0] if available else ""
        start, end = via_layers(available, top) if top else ("", "")
        if top and not end and self.stackup is not None:
            start, end = via_layers(self.stackup.metal_names(), top)
        stored_from, stored_to = self.current.from_layer, self.current.to_layer
        if stored_from == stored_to or stored_from not in names or stored_to not in names:
            stored_from = stored_to = ""
        for box, stored, default in ((self.from_layer, stored_from, start),
                                     (self.to_layer, stored_to, end),
                                     (self.target, self.current.target, top)):
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
    current = current or settings_of(shapes[0][0])
    if current is None:     # the last port's direction, Z0 and excitation; its layers belong to another place
        last = PortSettings.decode(settings.get("last_port")) or PortSettings()
        current = PortSettings(last.direction, z0=last.z0, voltage=last.voltage)
    dialog = PortDialog(layout, available, current, len(shapes))
    if not dialog.exec_():
        return False
    new = dialog.result_settings()
    backup_original(layout)
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
        from . import __version__
        _dock = pya.QDockWidget(f"EM Export {__version__}", main_window)    # the version a bug report needs
        _dock.setObjectName("klayout_em_export_panel")
        # in a scroll area: a dock shorter than the open details gets a scrollbar instead of squeezed buttons
        _dock._scroll = pya.QScrollArea(_dock)
        _dock._scroll.setWidgetResizable(True)
        _dock._scroll.setFrameShape(pya.QFrame.NoFrame)
        _panel = EMPanel(_dock._scroll)
        _dock._scroll.setWidget(_panel)
        _dock.setWidget(_dock._scroll)
        main_window.addDockWidget(pya.Qt.RightDockWidgetArea, _dock)
    _dock.show()
    _panel.refresh()


def _with_refresh(handler):
    def run():
        handler()
        refresh_panel()
    return run


def _create_circuit():
    from .circuit import create_circuit
    create_circuit()


def install_menu():
    from .tool import PortToolFactory
    _actions.append(PortToolFactory())     # registers the EM Port tool in the toolbar
    menu = pya.Application.instance().main_window().menu()
    if not menu.is_valid("em_menu"):
        menu.insert_menu("help_menu", "em_menu", "EM")    # own menu in the menu bar, before Help
    entries = (("show_panel", "EM Panel", show_panel),
               None,
               ("choose_stackup", "Choose Stackup...", choose_stackup),
               ("remove_dummy_fill", "Remove Dummy Fill", remove_dummy_fill),
               ("fill_and_merge", "Fill Density Holes and Merge Metal", fill_and_merge),
               None,
               ("port_tool", "EM Port Tool (click edge: via port, Shift+click gap: in-plane port)", port_tool),
               ("port_settings", "Port Settings...", port_settings),
               ("port_overview", "Port Overview", port_overview),
               None,
               ("mark_region", "Mark EM Region from Selection", mark_region),
               ("export_region", "Export for EM...", export_region),
               ("open_setupem", "Open Last Export in setupEM", lambda: open_last_export("setupEM")),
               ("open_emstudio", "Open Last Export in EMStudio", lambda: open_last_export("EMStudio")),
               ("create_circuit", "Create Circuit (EM Result with Devices)...", _create_circuit))
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
