"""EM panel: the export workflow as a checklist beside the layout, for EM or (mode switch at the top) thermal.

Each step is one line: status mark, summary, and details behind the arrow. Stackup and region are shared by both
modes. EM: the ports table holds the ports of the cell and the ports proposed where the EM region box cuts conductors;
the ground and boundary checks run with every refresh (view or cell change, every action of the plug-in, Refresh), a
very large region runs them on request. Thermal: the heat sources of the region (thermal.py) with their schematic
names from the LVS database, and the boundaries in the last thermal export's setupThermal file.
Clicking a row only highlights it: selecting the port shape would make the export use it as the region.
"""
import json
import os

import pya

from . import gui
from .boundary import find_crossings
from .connectivity import check_ground, wiring
from .export import marker_box
from .lvs import assign_names, read_lvs_devices
from .ports import collect_ports, device_of, export_numbering, export_port_numbers, is_complete, port_problems
from .thermal import heat_sources, heat_target, marker_layers

OK, WARN, ERROR = gui.OK, gui.WARN, gui.ERROR
COLUMNS = ("#", "Layer", "Port", "Export #", "Status")
DEVICE_COLUMNS = ("#", "Type", "Value", "Ports", "Status")
SOURCE_COLUMNS = ("Layer", "Device", "Instance", "Area µm²", "Heat area")
MODES = ("EM", "Thermal")
DEVICE_ROWS_SHOWN = 8               # the device table grows up to this many rows, then scrolls
AUTO_CHECK_LIMIT = 50000            # metal shapes in the region; above, the checks run on request only
MAX_MARKERS = 2000                  # ground outline: at most this many polygons


def _get(value):
    """KLayout's Qt binding exposes some getters as properties, others as methods; accept both."""
    return value() if callable(value) else value


def _button(text, handler, tip=""):
    button = pya.QPushButton(text)
    button.clicked += handler
    if tip:
        button.setToolTip(tip)
    return button


def _label(text=""):
    label = pya.QLabel(text)
    label.setWordWrap(True)
    return label


class Step(pya.QWidget):
    """One checklist line: status mark, title and summary; the arrow shows the details widget, if any."""

    def __init__(self, title, details=None):
        super().__init__()
        column = pya.QVBoxLayout(self)
        column.setContentsMargins(0, 2, 0, 2)
        row = pya.QHBoxLayout()
        self.mark = pya.QLabel()
        self.mark.setFixedWidth(16)
        heading = pya.QLabel(f"<b>{title}</b>")
        heading.setFixedWidth(64)
        self.summary = _label()
        row.addWidget(self.mark)
        row.addWidget(heading)
        row.addWidget(self.summary, 1)
        self.details = details
        if details is not None:
            self.arrow = pya.QToolButton()
            self.arrow.setArrowType(pya.Qt.RightArrow)
            self.arrow.setCheckable(True)
            self.arrow.setAutoRaise(True)
            self.arrow.setToolTip("details")
            self.arrow.toggled += self._toggled
            row.addWidget(self.arrow)
        column.addLayout(row)
        if details is not None:
            details.setVisible(False)
            column.addWidget(details)

    def _toggled(self, shown):
        self.details.setVisible(shown)
        self.arrow.setArrowType(pya.Qt.DownArrow if shown else pya.Qt.RightArrow)

    def set(self, state, text, tip=""):
        self.mark.setText(f'<span style="color:{state[1]}; font-weight:bold">{state[0]}</span>')
        self.summary.setText(text)
        self.summary.setToolTip(tip or text)


def _table(columns, tip):
    """A read-only table with whole-row selection, as the panel's port and device tables."""
    table = pya.QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setSelectionBehavior(pya.QAbstractItemView.SelectRows)
    table.setEditTriggers(pya.QAbstractItemView.NoEditTriggers)
    _get(table.verticalHeader).setVisible(False)
    _get(table.horizontalHeader).setStretchLastSection(True)
    table.setToolTip(tip)
    return table


def _set_row(table, row, values, tip=""):
    for col, value in enumerate(values):
        item = pya.QTableWidgetItem(value)
        item.setToolTip(tip or value)
        table.setItem(row, col, item)


def _row_widget(*widgets):
    """The widgets side by side, left-aligned, in a widget of their own (which can be hidden as a whole)."""
    box = pya.QWidget()
    row = pya.QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch(1)
    return box


def _details(*widgets):
    """A details widget: the given labels and button rows, indented under the step line."""
    box = pya.QWidget()
    column = pya.QVBoxLayout(box)
    column.setContentsMargins(24, 0, 0, 4)
    for widget in widgets:
        if isinstance(widget, list):
            row = pya.QHBoxLayout()
            for button in widget:
                row.addWidget(button)
            row.addStretch(1)
            column.addLayout(row)
        else:
            column.addWidget(widget)
    return box


class EMPanel(pya.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []              # per table row: ("port", Port) / ("proposed", Crossing) / ("cut", Crossing)
        self.numbering = {}         # {layout port layer: exported layer} for the current region
        self.result = None          # GroundCheck of the last refresh, None if not run
        self.ground_markers = []
        self.highlight = []
        self._bound = set()
        self.source_rows = []       # the HeatSource of each row of sources_table
        self._lvs_cache = {}        # {(lvsdb, mtime, layout, cell): (LVS devices, notes)}
        column = pya.QVBoxLayout(self)

        self.mode_bar = pya.QTabBar()
        for mode in MODES:
            self.mode_bar.addTab(mode)
        self.mode_bar.setToolTip("EM: ports and devices, for setupEM; Thermal: the devices as heat sources, for "
                                 "setupThermal")
        self.mode_bar.setCurrentIndex(1 if gui._load_settings().get("panel_mode") == "thermal" else 0)
        self.mode_bar.currentChanged += self._mode_changed
        column.addWidget(self.mode_bar)

        self.stackup_detail = _label()
        self.stackup_step = Step("Stackup", _details(self.stackup_detail, [_button("Change...", self._change_stackup)]))
        self.region_detail = _label()
        self.region_step = Step("Region", _details(self.region_detail, [
            _button("Mark Region from Selection", lambda: self._run(gui.mark_region),
                    f"draw the selection's bounding box on layer {gui.EM_REGION[0]}/{gui.EM_REGION[1]}")]))
        self.ground_detail = _label()
        self.show_ground = _button("Show in Layout", self._show_ground, "outline the ground net in green")
        self.show_ground.setCheckable(True)
        self.ground_step = Step("Ground", _details(self.ground_detail, [
            _button("Mark Selected", lambda: self._run(gui.mark_ground), "mark the selected metal shapes as ground"),
            _button("Use Ports", lambda: self._run(gui.clear_ground),
                    "forget the marks: ground is the net that most via ports reach"),
            self.show_ground,
            _button("Run Checks", lambda: self.refresh(run_checks=True),
                    "ground and boundary checks for a region too large to check on every refresh")]))
        self.devices_table = _table(DEVICE_COLUMNS, "click: highlight the device; double-click: zoom to it. #: its "
                                    "number in Create Circuit (X# in the subcircuit, R# for a resistor from its label)")
        self.devices_table.itemSelectionChanged += self._devices_selected
        self.devices_table.cellDoubleClicked += lambda row, col: self._zoom_to_device(row)
        self.device_rows = []       # the Device of each row of devices_table
        self.device_numbers = {}    # {device id: its # in devices_table}, for the port table
        self.device_types = {}      # {device id: its type, e.g. rhigh}, for the port table
        self.devices_detail = _label()
        self.include_resistors = pya.QCheckBox("include resistors")
        self.include_resistors.setChecked(True)
        self.include_resistors.setToolTip("also replace rsil, rppd, rhigh by two via ports each (recommended); "
                                          "unreplaced, the stackup models them as sheet resistors of the drawn size, "
                                          "without the PDK's width offset and contact end resistance: R too low")
        self.devices_step = Step("Devices", _details(self.devices_table, self.devices_detail, [
            _button("Replace All", self._replace_devices,
                    "replace each PDK transistor (and, if ticked, each resistor) by ports at its pins: a "
                    "REF_FOR_TRANSISTOR patch and one via port per terminal; the export removes the device's "
                    "shapes below its pins"),
            self.include_resistors,
            _button("Undo Replace", self._unreplace_devices, "remove the patches and ports made by Replace All")]))
        self.ports_step = Step("Ports")
        self.sources_step = Step("Sources")
        self.names_detail = _label()
        self.names_step = Step("Names", _details(self.names_detail, [
            _button("Choose...", self._choose_lvsdb, "the LVS database (.lvsdb) of KLayout's LVS of this layout "
                    "against your schematic: each heat source gets its schematic instance name"),
            _button("Clear", self._clear_lvsdb, "no LVS database: the export keeps the names of the last export")]))
        self.boundary_detail = _label()
        self.boundary_step = Step("Boundary", _details(self.boundary_detail))
        for step in (self.stackup_step, self.region_step, self.ground_step, self.devices_step, self.ports_step,
                     self.sources_step, self.names_step, self.boundary_step):
            column.addWidget(step)

        self.table = _table(COLUMNS, "click: highlight; double-click: settings (or create a proposed port); "
                            "right-click: more")
        self.table.itemSelectionChanged += self._rows_selected
        self.table.cellDoubleClicked += lambda row, col: self._activate(row)
        self.table.setContextMenuPolicy(pya.Qt.CustomContextMenu)
        self.table.customContextMenuRequested += self._context_menu
        column.addWidget(self.table, 1)
        self.sources_table = _table(SOURCE_COLUMNS, "click: highlight the device; double-click: zoom to it. Layer: "
                                    "its marker layer in the export")
        self.sources_table.itemSelectionChanged += self._sources_selected
        self.sources_table.cellDoubleClicked += lambda row, col: self._zoom_to(self.source_rows[row].device.bbox)
        column.addWidget(self.sources_table, 1)
        tool = _button("EM Port tool", lambda: self._run(gui.port_tool),
                       "click a metal edge: via port; Shift+click into a gap: in-plane port")
        tool.setIcon(pya.QIcon(gui.PORT_ICON))
        self.create_button = _button("Create Proposed Ports", self._create_proposed,
                                     "via ports where the EM region box cuts signal conductors")
        self.tool_row = _row_widget(tool, self.create_button)
        self.refresh_button = _button("Refresh", lambda: self.refresh())
        row = pya.QHBoxLayout()
        row.addWidget(self.tool_row)
        row.addWidget(self.refresh_button)
        row.addStretch(1)
        column.addLayout(row)

        line = pya.QFrame()
        line.setFrameShape(pya.QFrame.HLine)
        column.addWidget(line)
        self.open_button = _button(f"Open in {gui.open_with()}", lambda: gui.open_last_export())
        self.em_buttons = _row_widget(_button("Export for EM...", lambda: self._run(gui.export_region)),
                                      self.open_button)
        self.open_thermal_button = _button(f"Open in {gui.THERMAL_TOOL}", lambda: gui.open_last_thermal_export())
        self.thermal_buttons = _row_widget(_button("Export for Thermal...", lambda: self._run(gui.export_thermal_region),
                                                   "the devices as heat sources, for setupThermal"),
                                           self.open_thermal_button)
        column.addWidget(self.em_buttons)
        column.addWidget(self.thermal_buttons)
        self._show_mode()

        main_window = pya.Application.instance().main_window()
        if main_window is not None:
            main_window.on_current_view_changed += lambda: self.refresh()
        self.refresh()

    # ---------- state ----------

    def _thermal(self):
        return _get(self.mode_bar.currentIndex) == 1

    def _show_mode(self):
        """Show the steps, table and buttons of the current mode."""
        thermal = self._thermal()
        for widget in (self.ground_step, self.devices_step, self.ports_step, self.table, self.tool_row, self.em_buttons):
            widget.setVisible(not thermal)
        for widget in (self.sources_step, self.names_step, self.boundary_step, self.sources_table,
                       self.thermal_buttons):
            widget.setVisible(thermal)
        self.refresh_button.setToolTip("e.g. after editing devices or running LVS again" if thermal else
                                       "e.g. after drawing ports by hand")

    def _mode_changed(self, index):
        settings = gui._load_settings()
        settings["panel_mode"] = "thermal" if index == 1 else "em"
        gui._save_settings(settings)
        self._show_mode()
        self.refresh()

    def _view(self):
        main_window = pya.Application.instance().main_window()
        view = main_window.current_view() if main_window is not None else None
        if view is None or view.active_cellview().layout() is None:
            return None, None
        return view, view.active_cellview()

    def _bind(self, view):
        if id(view) in self._bound:
            return
        self._bound.add(id(view))
        view.on_selection_changed += self._update_region
        view.on_active_cellview_changed += lambda: self.refresh()
        view.on_cellview_changed += lambda index: self.refresh()

    def _clear_markers(self, markers):
        for marker in markers:
            marker._destroy()
        markers.clear()

    def refresh(self, run_checks=False):
        self._clear_markers(self.highlight)
        self._clear_markers(self.ground_markers)
        self.show_ground.setChecked(False)
        view, cv = self._view()
        if view is None:
            for step in (self.stackup_step, self.region_step, self.ground_step, self.devices_step, self.ports_step,
                         self.sources_step, self.names_step, self.boundary_step):
                step.set(ERROR, "no layout loaded")
            self.table.setRowCount(0)
            self.devices_table.setRowCount(0)
            self.sources_table.setRowCount(0)
            self.source_rows = []
            self.device_rows, self.device_numbers, self.device_types = [], {}, {}
            return
        self._bind(view)
        layout, cell = cv.layout(), cv.cell
        path = gui.stackup_path(layout)
        stackup, error = gui.read_stackup(path) if path else (None, "none chosen yet")
        if stackup is None:
            self.stackup_step.set(ERROR, f"{error}: open the details to choose one")
            self.stackup_detail.setText(path or "")
        else:
            unresolved = stackup.unresolved()
            if unresolved:
                self.stackup_step.set(WARN, f"{os.path.basename(path)}: height of {', '.join(unresolved)} is not "
                                      "resolved (given by a variable), so it is left out of nets and ground", path)
            else:
                self.stackup_step.set(OK, os.path.basename(path), path)
            self.stackup_detail.setText(path)
        if self._thermal():
            self._update_region()           # with the heat sources of the region, the names and the boundaries
            last = gui.last_tsimcfg(layout)
            self.open_thermal_button.setEnabled(last is not None)
            self.open_thermal_button.setToolTip(f"open {last} in {gui.THERMAL_TOOL}, without exporting again" if last
                                                else "this layout has no thermal export yet")
            return

        # ground and boundary: in the EM region box (else the whole cell), not in a selection - one selects metal
        # to mark it as ground
        marker = marker_box(layout, cell, gui.EM_REGION)
        clip = None if marker is None else marker.to_itype(layout.dbu)
        self.result, crossings = None, []
        if stackup is not None:
            size = self._region_size(layout, cell, stackup, clip)
            if run_checks or size <= AUTO_CHECK_LIMIT:
                self.result = check_ground(layout, cell, stackup, clip, gui.ground_seeds(layout),
                                           collect_ports(layout, cell, clip, stackup=stackup))
                if clip is not None:
                    crossings = find_crossings(layout, cell, stackup, clip, self.result)
        self._show_ground_step(stackup, layout)
        self._show_devices_step(stackup, layout, cell)
        self._fill_table(layout, cell, stackup, crossings)
        self._update_region()
        last = gui.last_simcfg(layout)
        tool = gui.open_with()                  # as last chosen in the export dialog
        self.open_button.setText(f"Open in {tool}")
        self.open_button.setEnabled(last is not None)
        self.open_button.setToolTip(f"open {last} in {tool}, without exporting again (the other program: EM menu)"
                                    if last else "this layout has not been exported yet")

    def _region_size(self, layout, cell, stackup, clip):
        layers = wiring(stackup)[0]
        total = 0
        for layer in layers:
            li = layout.find_layer(layer, 0)
            if li is not None:
                total += pya.Region(cell.begin_shapes_rec(li) if clip is None else
                                    cell.begin_shapes_rec_touching(li, clip)).count()
        return total

    def _show_ground_step(self, stackup, layout):
        marks = len(gui.ground_seeds(layout))
        how = f"{marks} marked shape(s)" if marks else "from the via ports"
        if stackup is None:
            self.ground_step.set(ERROR, "needs a stackup")
            self.ground_detail.setText("")
        elif self.result is None:
            self.ground_step.set(WARN, "large region, not checked: Run Checks in the details")
            self.ground_detail.setText(f"more than {AUTO_CHECK_LIMIT} metal shapes in the region")
        elif not self.result.net:
            self.ground_step.set(WARN, f"not found ({how})")
            self.ground_detail.setText(self.result.source)
        else:
            names = ", ".join(self.result.names[l] for l in sorted(self.result.net))
            state = WARN if self.result.pieces > 1 else OK
            self.ground_step.set(state, f"{names} ({how})", self.result.summary())
            self.ground_detail.setText(self.result.summary())

    def _show_devices_step(self, stackup, layout, cell):
        self._fill_devices([], layout)
        if stackup is None:
            self.devices_step.set(ERROR, "needs a stackup")
            self.devices_detail.setText("")
            return
        technology, reason = gui.layout_technology(layout)
        self.devices_step.summary.setToolTip(f"technology: {technology.LABEL} ({reason})")
        devices, unknown = gui.find_layout_devices(layout, cell, stackup)
        transistors = [d for d in devices if not d.is_resistor]
        resistors = [d for d in devices if d.is_resistor]
        self._fill_devices(devices, layout, technology)
        lines = [f"{count} x {qname}: not supported yet" for qname, count in unknown]
        from .devices import REF_NAME, orphaned_tags, touching_patches, unconnected_terminals
        # device ports end on the REF_FOR_TRANSISTOR sheet: a stackup without it cannot replace devices; Replace All
        # would only say so afterwards. Device replacement is for Palace only (gds2palace stackups have the layer).
        no_ref = stackup.layer(REF_NAME) is None and any(not d.replaced for d in devices)
        if no_ref:
            lines.insert(0, f"this stackup has no {REF_NAME} layer: devices cannot be replaced by ports (device "
                            "replacement is for Palace, with a gds2palace stackup)")
        touching = touching_patches(layout, cell, stackup)
        loose = unconnected_terminals(layout, devices, self.result) if self.result is not None else []
        orphans = orphaned_tags(layout, cell, devices)
        lines += [f"{t} of {d.pcell} {d.id.split('@')[0]} is not connected to any wiring (floats in the EM model)"
                  for d, t in loose]
        lines += [f"REF patches of {a.split('@')[0]} and {b.split('@')[0]} touch: one shared reference"
                  for a, b in touching]
        lines += [f"ports {', '.join(str(n) for _, n in sorted(p.items())) or '(none)'} and the REF patch of "
                  f"{i.split('@')[0]} at {i.split('@')[1]} dbu: that device is no longer there (moved or deleted); "
                  "Undo Replace, then Replace All" for i, p in sorted(orphans.items())]
        self.devices_detail.setText("\n".join(lines) or ("" if devices else technology.NO_DEVICES))
        self.devices_detail.setVisible(bool(_get(self.devices_detail.text)))
        if not devices and not unknown and not orphans:
            self.devices_step.set(OK, "none" if technology.KLAYOUT_TECHNOLOGIES else "no device support")
            return
        parts = []
        if transistors:
            parts.append(f"{len(transistors)} transistor(s), {sum(d.replaced for d in transistors)} replaced")
        if resistors:
            parts.append(f"{len(resistors)} resistor(s), {sum(d.replaced for d in resistors)} replaced")
        if unknown:
            parts.append(f"{sum(c for _, c in unknown)} not supported")
        if touching:
            parts.append(f"{len(touching)} pair(s) of REF patches touch")
        if loose:
            parts.append(f"{len(loose)} terminal(s) not connected")
        if orphans:
            parts.append(f"ports of {len(orphans)} device(s) no longer there")
        if no_ref:
            parts.append(f"stackup has no {REF_NAME}")
        # an unreplaced resistor is a warning too: its sheet in the EM model lacks the PDK's width offset and contact
        # end resistance, so its R is too low (Palace: rhigh and rppd by 9 to 13 %, see tests/resistor_palace)
        state = (OK if all(d.replaced for d in devices) and not unknown and not touching and not loose and not orphans
                 else WARN)
        self.devices_step.set(state, ", ".join(parts))

    def _fill_devices(self, devices, layout, technology=None):
        """One row per device, ordered by device id. # is the device's number k in Create Circuit (X<k>, or R<k> for
        a resistor from its label): the wrapper numbers the replaced devices of the port map in id order."""
        self.device_rows = sorted(devices, key=lambda d: d.id)
        self.devices_table.setRowCount(len(self.device_rows))
        number = {i: k for k, i in enumerate(sorted(d.id for d in devices if d.replaced), start=1)}
        self.device_numbers = number
        self.device_types = {d.id: d.pcell for d in devices}
        dbu = layout.dbu
        for row, d in enumerate(self.device_rows):
            if d.replaced:
                state, why = "replaced", "replaced by ports; Create Circuit puts the PDK model back"
            elif d.problems:
                state, why = "cannot be replaced", "; ".join(d.problems)
            elif d.is_resistor:
                state, why = "not replaced: EM gives R too low", technology.resistor_note(d)
            else:
                state, why = "not replaced", "simulated as drawn layout"
            ports = ", ".join(f"{t} {n}" for t, n in sorted(d.ports.items(), key=lambda item: item[1]))
            center = d.bbox.center()
            where = f"{d.id.split('@')[0]} at ({center.x * dbu:.2f}, {center.y * dbu:.2f}) µm"
            _set_row(self.devices_table, row, (str(number.get(d.id, "")), d.pcell, technology.describe(d), ports,
                                               state), f"{where}\n{why}")
        self.devices_table.resizeColumnsToContents()
        # as high as its rows, up to DEVICE_ROWS_SHOWN; then it scrolls
        rows = min(len(self.device_rows), DEVICE_ROWS_SHOWN)
        height = (_get(_get(self.devices_table.horizontalHeader).height) + 2 * _get(self.devices_table.frameWidth)
                  + sum(self.devices_table.rowHeight(r) for r in range(rows)))
        self.devices_table.setFixedHeight(height)
        self.devices_table.setVisible(bool(self.device_rows))

    def _device_boxes(self):
        return [self.device_rows[r].bbox for r in sorted({_get(i.row) for i in self.devices_table.selectedItems()})]

    def _devices_selected(self):
        """Highlight the selected devices (markers, not a selection) and bring them into view."""
        self._clear_markers(self.highlight)
        view, cv = self._view()
        if view is None:
            return
        self._mark(view, cv.layout().dbu, self._device_boxes())

    def _zoom_to_device(self, row):
        view, cv = self._view()
        if view is not None and row < len(self.device_rows):
            box = self.device_rows[row].bbox.to_dtype(cv.layout().dbu)
            margin = max(box.width(), box.height())
            view.zoom_box(box.enlarged(margin, margin))

    def _replace_devices(self):
        view, cv = self._view()
        if view is not None:
            done = gui.replace_devices(view, cv, self.include_resistors.isChecked())
            self.refresh()
            gui._status(f"{len(done)} device(s) replaced by ports", 10)

    def _unreplace_devices(self):
        view, cv = self._view()
        if view is not None:
            removed = gui.unreplace_devices(view, cv)
            self.refresh()
            gui._status(f"device replacement undone ({removed} shape(s) removed)", 10)

    def _fill_table(self, layout, cell, stackup, crossings):
        self.table.setRowCount(0)
        self.rows = []
        ports = collect_ports(layout, cell, stackup=stackup)
        shorted = set(self.result.shorted) if self.result is not None else set()
        problems_total = 0
        for layer in sorted(ports):
            port = ports[layer]
            s = port.settings
            problems = list(port_problems(port, stackup)) if stackup is not None else []
            if port.number in shorted:
                problems.append("short circuit: both ends on one net")
            if not is_complete(port):
                problems.insert(0, "not simulated (incomplete)")
            problems_total += bool(problems)
            text = "" if s is None else (f"{s.direction} {s.from_layer} → {s.to_layer}" if s.is_via
                                         else f"{s.direction} on {s.target}")
            if s is not None and s.voltage == 0:
                text += " (not excited)"
            device = device_of(port)
            if device is not None:
                k = self.device_numbers.get(device[0])      # the device's # in the Devices table
                name = self.device_types.get(device[0]) or device[0].split("@")[0]    # the type, not a cell name
                text += f"  [{device[1]} of {'#' + str(k) + ' ' if k else ''}{name}]"
            self._add_row(("port", port), (str(port.number), str(layer), text, "", "; ".join(problems) or "ok"))
        proposed = [c for c in crossings if c.needs_port]
        unground = [c for c in crossings if not c.ground and c.port is None and c.ground_layer is None]
        for c in proposed:
            self._add_row(("proposed", c), ("–", "–", f"{c.name} cut ({c.side} edge) → {c.ground_layer[1]}",
                                            "", "proposed: double-click or Create Proposed Ports"))
        for c in unground:
            self._add_row(("cut", c), ("–", "–", f"{c.name} cut ({c.side} edge)", "",
                                       "signal cut, but no ground metal at the cut: add a port by hand"))
        self.table.resizeColumnsToContents()
        self.create_button.setText(f"Create {len(proposed)} Proposed Port(s)" if proposed else "Create Proposed Ports")
        self.create_button.setEnabled(bool(proposed))
        parts = [f"{len(ports)} port(s)"]
        if problems_total:
            parts.append(f"{problems_total} with problems")
        if proposed:
            parts.append(f"{len(proposed)} proposed at the cut")
        if unground:
            parts.append(f"{len(unground)} cut without ground")
        state = ERROR if not ports and not proposed else WARN if (problems_total or proposed or unground) else OK
        self.ports_step.set(state, ", ".join(parts) if ports or proposed else
                            "none yet: EM Port tool, or ports proposed where the EM region box cuts conductors")

    def _add_row(self, kind, values):
        row = _get(self.table.rowCount)
        self.table.insertRow(row)
        for col, value in enumerate(values):
            item = pya.QTableWidgetItem(value)
            item.setToolTip(value)
            if kind[0] != "port":
                item.setForeground(pya.QBrush(pya.QColor("#888888")))
            self.table.setItem(row, col, item)
        self.rows.append(kind)

    def _update_region(self):
        """Region line and the Export # column: they follow the selection."""
        view, cv = self._view()
        if view is None:
            return
        layout, cell = cv.layout(), cv.cell
        box, source, selection = gui.region_source(view, cv)
        state = WARN if selection is not None else OK
        self.region_step.set(state, source + ("" if box is None else f": {box}"))
        thermal = self._thermal()
        if selection is not None:
            detail = ("The export uses the bounding box of the selection" +
                      (". " if thermal else " (or, chosen in the export dialog, the selected shapes only). ") +
                      "Clear the selection to use the EM region box.")
        else:
            detail = (f"Keep the region with the layout: select shapes and Mark Region (layer {gui.EM_REGION[0]}/"
                      f"{gui.EM_REGION[1]})." + ("" if thermal else " Ports proposed at the cut need this box."))
        self.region_detail.setText(detail + "\nA selection of port shapes only does not count as a region.")
        path = gui.stackup_path(layout)
        stackup = gui.read_stackup(path)[0] if path else None
        if thermal:
            self._show_thermal(layout, cell, stackup, box)
            return
        clip = None if box is None else box.to_itype(layout.dbu)
        try:
            self.numbering = export_numbering(collect_ports(layout, cell, clip, stackup=stackup), stackup)
        except ValueError:
            self.numbering = {}
        numbers = export_port_numbers(self.numbering)
        for row, (kind, item) in enumerate(self.rows):
            if kind == "port":
                new = numbers.get(item.layer)
                cell_item = self.table.item(row, 3)
                text = "– (outside)" if new is None else str(new)
                cell_item.setText(text)
                cell_item.setToolTip("number in the .simcfg and .snp" if new else "not in the region")

    # ---------- thermal ----------

    def _show_thermal(self, layout, cell, stackup, box):
        """Sources, Names and Boundary steps and the heat source table, for the region box (DBox, None: whole cell)."""
        self._clear_markers(self.highlight)
        self.sources_table.setRowCount(0)
        self.source_rows = []
        if stackup is None:
            for step in (self.sources_step, self.names_step):
                step.set(ERROR, "needs a stackup")
            self.names_detail.setText("")
            self._show_boundary(layout, None)
            return
        technology = gui.layout_technology(layout)[0]
        try:
            target = heat_target(stackup, technology)
        except ValueError as e:
            self.sources_step.set(ERROR, "no layer for the heat sources", str(e))
            target = False
        sources = heat_sources(layout, cell, stackup, technology, box) if target else []
        layers = marker_layers(stackup, len(sources) + 1)
        names = self._show_names(layout, cell, sources, technology)
        self._fill_sources(layout, technology, sources, layers[1:], names)
        self._show_boundary(layout, layers[0])
        if target is None:
            self.sources_step.set(OK, "no device support for this technology")
        elif target is False:
            pass
        elif not sources:
            self.sources_step.set(WARN, "no devices in the region: the export has no heat sources")
        else:
            parts = [f"{len(sources)} heat source(s) in {target}"]
            fallback = sum(not s.from_pdk for s in sources)
            from_rule = sum(s.how == "rule" for s in sources)
            cut = sum(s.cut for s in sources)
            if fallback:
                parts.append(f"{fallback} without a heat area (bounding box)")
            if from_rule:
                parts.append(f"{from_rule} from the PDK's rule (this PDK draws no heat shapes)")
            if cut:
                parts.append(f"{cut} cut by the region")
            self.sources_step.set(WARN if fallback or cut else OK, ", ".join(parts),
                                  "one per device, on its own marker layer; power 0 W until set in setupThermal "
                                  "(Load powers...)")

    def _fill_sources(self, layout, technology, sources, layers, names):
        self.source_rows = list(sources)
        self.sources_table.setRowCount(len(sources))
        dbu = layout.dbu
        for row, (layer, s) in enumerate(zip(layers, sources)):
            d = s.device
            heat = {"shapes": "PDK heat shapes", "rule": "PDK rule (no heat shapes)"}.get(s.how, "bounding box")
            if s.cut:
                heat += ", cut by the region"
            center = d.bbox.center()
            where = f"{d.id.split('@')[0]} at ({center.x * dbu:.2f}, {center.y * dbu:.2f}) µm"
            _set_row(self.sources_table, row, (str(layer), f"{d.pcell} {technology.describe(d)}".strip(),
                                               names.get(d.id, ""), f"{s.area.area() * dbu * dbu:.3g}", heat), where)
        self.sources_table.resizeColumnsToContents()

    def _last_map(self, layout):
        """The thermal map of the layout's last thermal export, or {}."""
        tsimcfg = gui.last_tsimcfg(layout)
        if tsimcfg is None:
            return {}
        try:
            with open(os.path.splitext(tsimcfg)[0] + "_thermalmap.json") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _lvs_devices(self, lvsdb, layout, cell):
        """read_lvs_devices, kept until the file changes (else every refresh would read it again)."""
        key = (lvsdb, os.path.getmtime(lvsdb), id(layout), cell.cell_index())
        if key not in self._lvs_cache:
            self._lvs_cache = {key: read_lvs_devices(lvsdb, layout, cell)}
        return self._lvs_cache[key]

    def _show_names(self, layout, cell, sources, technology):
        """The Names step; returns {device id: schematic instance name} for the table."""
        lvsdb = gui.lvsdb_path(layout)
        about = ("The schematic instance name of each heat source, from KLayout's LVS of this layout against your "
                 "schematic (LVS of this cell, or of a cell that contains it once). setupThermal's Load powers... "
                 "assigns the powers of your circuit simulation by these names.")
        if not lvsdb:
            previous = {r.get("device"): r.get("instance") for r in self._last_map(layout).get("sources", [])
                        if r.get("instance")}
            names = {s.device.id: previous[s.device.id] for s in sources if s.device.id in previous}
            self.names_step.set(OK, f"{len(names)} of {len(sources)} from the last export (no LVS database)" if names
                                else "none: optional, from an LVS database (details)")
            self.names_detail.setText(about)
            return names
        if not os.path.isfile(lvsdb):
            self.names_step.set(ERROR, f"{os.path.basename(lvsdb)} not found", lvsdb)
            self.names_detail.setText(f"{lvsdb}\n{about}")
            return {}
        try:
            lvs_devices, notes = self._lvs_devices(lvsdb, layout, cell)
        except ValueError as e:
            self.names_step.set(ERROR, str(e), lvsdb)
            self.names_detail.setText(f"{lvsdb}\n{about}")
            return {}
        instances, report = assign_names(sources, lvs_devices, technology, layout.dbu)
        problems = list(notes)
        if report["unnamed"]:
            problems.append("no LVS device: " + ", ".join(i.split("@")[0] for i in report["unnamed"]))
        if report["conflicts"]:
            problems.append("several LVS devices with different names (none used): " + "; ".join(report["conflicts"]))
        self.names_step.set(WARN if problems else OK,
                            f"{len(instances)} of {len(sources)} from {os.path.basename(lvsdb)}" +
                            (": " + "; ".join(problems) if problems else ""), lvsdb)
        self.names_detail.setText("\n".join([lvsdb] + problems + [about]))
        return {device: name for device, (name, _) in instances.items()}

    def _show_boundary(self, layout, outline_layer):
        """The Boundary step: the constant temperatures in the last thermal export's setupThermal file."""
        tsimcfg = gui.last_tsimcfg(layout)
        about = ("Constant temperatures are chosen in setupThermal. The export writes the region outline on a marker "
                 "layer of its own; without a boundary yet, it adds a placeholder there whose target layer (the height "
                 "of the fixed temperature, e.g. the substrate backside) you choose in setupThermal. The side faces "
                 "of the model are adiabatic.")
        rows = []
        if tsimcfg is not None:
            try:
                with open(tsimcfg) as f:
                    rows = [t for t in json.load(f).get("thermal", [])
                            if "SOURCE" not in str(t.get("type", "")).upper()]
            except (OSError, ValueError, AttributeError):
                tsimcfg = None
        if tsimcfg is None:
            where = f" (layer {outline_layer})" if outline_layer else ""
            self.boundary_step.set(OK, f"chosen in setupThermal; the export adds the region outline{where} as a "
                                   "placeholder")
            self.boundary_detail.setText(about)
            return
        outline = self._last_map(layout).get("outline_layer")
        parts = []
        for t in rows:
            layer = t.get("source_layernum")
            name = f"layer {layer}" + (" (region outline)" if layer == outline else "")
            temp = t.get("temp")
            parts.append(f"{name} → {t.get('target_layername') or 'no target layer yet'}, "
                         f"{format(temp, 'g') if isinstance(temp, (int, float)) else '?'} K")
        open_target = any(not t.get("target_layername") for t in rows)
        if not rows:
            self.boundary_step.set(WARN, "none in the last export: add one in setupThermal", tsimcfg)
        else:
            self.boundary_step.set(WARN if open_target else OK, "; ".join(parts) +
                                   (": choose the target layer in setupThermal" if open_target else ""), tsimcfg)
        self.boundary_detail.setText(f"From {tsimcfg}\n{about}")

    def _sources_selected(self):
        self._clear_markers(self.highlight)
        view, cv = self._view()
        if view is None:
            return
        rows = sorted({_get(i.row) for i in self.sources_table.selectedItems()})
        self._mark(view, cv.layout().dbu, [self.source_rows[r].device.bbox for r in rows if r < len(self.source_rows)])

    def _zoom_to(self, bbox):
        view, cv = self._view()
        if view is not None:
            box = bbox.to_dtype(cv.layout().dbu)
            margin = max(box.width(), box.height())
            view.zoom_box(box.enlarged(margin, margin))

    def _choose_lvsdb(self):
        view, cv = self._view()
        if view is not None and gui.ask_lvsdb(cv.layout()):
            self.refresh()

    def _clear_lvsdb(self):
        view, cv = self._view()
        if view is not None:
            gui.clear_lvsdb(cv.layout())
            self.refresh()

    # ---------- table ----------

    def _selected_rows(self):
        return sorted({_get(index.row) for index in _get(self.table.selectionModel).selectedRows()})

    def _rows_selected(self):
        """Highlight the selected rows in the layout (markers, not a selection) and bring them into view."""
        self._clear_markers(self.highlight)
        view, cv = self._view()
        if view is None:
            return
        boxes = []
        for r in self._selected_rows():
            kind, item = self.rows[r]
            boxes += ([s.bbox().transformed(t) for s, t, _ in item.items] if kind == "port" else [item.edge.bbox()])
        self._mark(view, cv.layout().dbu, boxes)

    def _mark(self, view, dbu, boxes):
        """Highlight markers on boxes (in the cell, dbu); zoom out to them if they are not all in view."""
        box = pya.Box()
        for b in boxes:
            marker = pya.Marker(view)
            marker.set(b.to_dtype(dbu))
            marker.color = 0xff00ff
            marker.line_width = 4
            marker.vertex_size = 6
            self.highlight.append(marker)
            box += b
        if box.empty():
            return
        dbox = box.to_dtype(dbu)
        if not dbox.inside(view.box()):
            margin = max(dbox.width(), dbox.height(), 5.0)
            view.zoom_box(dbox.enlarged(margin, margin))

    def _activate(self, row):
        kind, item = self.rows[row]
        if kind == "port":
            self._edit([item])
        elif kind == "proposed":
            self._create([item])

    def _context_menu(self, pos):
        row = self.table.rowAt(_get(pos.y))
        if row < 0:
            return
        if row not in self._selected_rows():
            self.table.selectRow(row)
        chosen = [self.rows[r] for r in self._selected_rows()]
        ports = [item for kind, item in chosen if kind == "port"]
        proposed = [item for kind, item in chosen if kind == "proposed"]
        menu = pya.QMenu(self)
        actions = []
        if ports:
            actions.append((menu.addAction("Settings..."), lambda: self._edit(ports)))
            actions.append((menu.addAction("Delete"), lambda: self._delete(ports)))
        if proposed:
            actions.append((menu.addAction(f"Create {len(proposed)} Port(s)"), lambda: self._create(proposed)))
        chosen_action = menu.exec_(_get(pya.QCursor.pos))
        for action, handler in actions:
            if chosen_action is not None and chosen_action == action:
                handler()

    # ---------- actions ----------

    def _run(self, action):
        action()
        self.refresh()

    def _change_stackup(self):
        view, cv = self._view()
        if view is not None and gui.ask_stackup(cv.layout()):
            self.refresh()

    def _show_ground(self, shown):
        self._clear_markers(self.ground_markers)
        view, cv = self._view()
        if not shown or view is None or self.result is None:
            return
        dbu = cv.layout().dbu
        for region in self.result.net.values():
            for polygon in region.each():
                if len(self.ground_markers) >= MAX_MARKERS:
                    return
                marker = pya.Marker(view)
                marker.set(polygon.to_dtype(dbu))
                marker.color = 0x00d000
                marker.line_width = 2
                self.ground_markers.append(marker)

    def _edit(self, ports):
        view, cv = self._view()
        if view is None or not ports:
            return
        gui.edit_ports(view, cv, [(shape, trans) for port in ports for shape, trans, _ in port.items])
        self.refresh()

    def _delete(self, ports):
        view, cv = self._view()
        if view is None or not ports:
            return
        numbers = ", ".join(str(p.number) for p in ports)
        if pya.MessageBox.question("EM Export", f"Delete the shapes of port(s) {numbers}?",
                                   pya.MessageBox.Yes | pya.MessageBox.No) != pya.MessageBox.Yes:
            return
        gui.backup_original(cv.layout())
        view.transaction("Delete ports")
        try:
            for port in ports:
                for shape, _, _ in port.items:
                    shape.delete()
        finally:
            view.commit()
        self.refresh()

    def _create(self, crossings):
        view, cv = self._view()
        if view is None or not crossings:
            return
        numbers = gui.create_boundary_ports(view, cv, crossings)
        self.refresh()
        gui._status(f"port(s) {', '.join(map(str, numbers))} created at the cut", 10)

    def _create_proposed(self):
        self._create([item for kind, item in self.rows if kind == "proposed"])
