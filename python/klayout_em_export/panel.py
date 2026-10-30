"""EM panel: a dock beside the layout with the whole EM export workflow in one place.

Stackup, the ports of the current cell (click: select in the layout, double-click: settings) and what the export
will use. The actions are the same functions as in the EM menu. The port table is rebuilt when the view or cell
changes and after every action from the plug-in; ports drawn with KLayout's own tools show up on Refresh.
"""
import os

import pya

from . import gui
from .export import marker_box
from .ports import collect_ports, is_complete, port_problems

COLUMNS = ("Port", "Layer", "Dir", "Layers", "Z0", "Status")
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


def _heading(text):
    return pya.QLabel(f"<b>{text}</b>")


class EMPanel(pya.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.port_rows = []         # Port per table row
        self.markers = []           # pya.Marker of the shown ground net
        self._bound = set()         # ids of the views whose events are connected
        column = pya.QVBoxLayout(self)

        column.addWidget(_heading("Stackup"))
        row = pya.QHBoxLayout()
        self.stackup_label = pya.QLabel()
        self.stackup_label.setWordWrap(True)
        row.addWidget(self.stackup_label, 1)
        row.addWidget(_button("Change...", self._change_stackup))
        column.addLayout(row)

        column.addWidget(_heading("Ports"))
        row = pya.QHBoxLayout()
        port_tool = _button("EM Port tool", lambda: self._run(gui.port_tool),
                            "click a metal edge: via port; Shift+click into a gap: in-plane port")
        port_tool.setIcon(pya.QIcon(gui.PORT_ICON))
        row.addWidget(port_tool)
        row.addWidget(_button("Settings...", self._edit, "settings of the selected ports (or double-click a row)"))
        row.addWidget(_button("Delete", self._delete, "delete the selected ports' shapes"))
        row.addWidget(_button("Refresh", self.refresh, "rebuild the table, e.g. after drawing ports by hand"))
        column.addLayout(row)
        self.table = pya.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(pya.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(pya.QAbstractItemView.NoEditTriggers)
        _get(self.table.verticalHeader).setVisible(False)
        _get(self.table.horizontalHeader).setStretchLastSection(True)
        self.table.itemSelectionChanged += self._rows_selected
        self.table.cellDoubleClicked += lambda row, col: self._edit()
        column.addWidget(self.table, 1)

        column.addWidget(_heading("Ground"))
        row = pya.QHBoxLayout()
        row.addWidget(_button("Mark Selected", self._mark_ground,
                              "mark the selected metal shapes as ground (stored in the layout)"))
        row.addWidget(_button("Use Ports", self._use_ports,
                              "forget the marks: ground is the net that most via ports reach"))
        row.addWidget(_button("Check", self._check_ground,
                              "trace the ground net through the vias and outline it in the layout"))
        row.addWidget(_button("Hide", self._hide_ground, "remove the ground outline"))
        column.addLayout(row)
        self.ground_label = pya.QLabel()
        self.ground_label.setWordWrap(True)
        column.addWidget(self.ground_label)

        column.addWidget(_heading("Export"))
        self.region_label = pya.QLabel()
        self.region_label.setWordWrap(True)
        column.addWidget(self.region_label)
        row = pya.QHBoxLayout()
        row.addWidget(_button("Mark Region", lambda: self._run(gui.mark_region),
                              f"draw the selection's bounding box on layer {gui.EM_REGION[0]}/{gui.EM_REGION[1]}"))
        row.addWidget(_button("Export for EM...", lambda: self._run(gui.export_region)))
        column.addLayout(row)

        main_window = pya.Application.instance().main_window()
        if main_window is not None:
            main_window.on_current_view_changed += self.refresh
        self.refresh()

    # ---------- state ----------

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
        view.on_active_cellview_changed += self.refresh
        view.on_cellview_changed += lambda index: self.refresh()

    def refresh(self):
        view, cv = self._view()
        self.table.setRowCount(0)
        self.port_rows = []
        if view is None:
            self.stackup_label.setText("no layout loaded")
            self.region_label.setText("")
            return
        self._bind(view)
        layout, cell = cv.layout(), cv.cell
        path = gui.stackup_path(layout)
        stackup = gui.read_stackup(path)[0] if path else None
        if stackup is None:
            self.stackup_label.setText("<b>none chosen yet</b>" if not path else f"<b>cannot read</b> {path}")
        else:
            self.stackup_label.setText(os.path.basename(path))
            self.stackup_label.setToolTip(path)
        ports = collect_ports(layout, cell, stackup=stackup)
        for layer in sorted(ports):
            port = ports[layer]
            s = port.settings
            problems = port_problems(port, stackup) if stackup is not None else []
            if not is_complete(port):
                status = "not in .simcfg: " + ("; ".join(problems) or "incomplete")
            else:
                status = "; ".join(problems) or "ok"
            layers = "" if s is None else (f"{s.from_layer} -> {s.to_layer}" if s.is_via else s.target)
            values = (str(port.number), str(layer), "" if s is None else s.direction, layers,
                      "" if s is None else f"{s.z0:g}" + ("" if s.voltage else " (off)"), status)
            row = _get(self.table.rowCount)
            self.table.insertRow(row)
            for col, value in enumerate(values):
                item = pya.QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
            self.port_rows.append(port)
        self.table.resizeColumnsToContents()
        self._update_region()
        marks = len(gui.ground_seeds(layout))
        if not self.markers:
            self.ground_label.setText((f"{marks} marked ground shape(s)" if marks else
                                       "not marked: found from the via ports") + "; Check traces it")

    def _update_region(self):
        view, cv = self._view()
        if view is None:
            return
        selected = sum(1 for _ in view.each_object_selected())
        if selected:
            text = (f"{selected} object(s) selected: the export uses the selected shapes (or, if chosen, "
                    "everything inside their bounding box)")
        else:
            box = marker_box(cv.layout(), cv.cell, gui.EM_REGION)
            text = (f"nothing selected: the export uses the EM region box {box}" if box is not None else
                    f"nothing selected, no EM region box: the export uses the whole cell {cv.cell.name}")
        self.region_label.setText(text)

    # ---------- actions ----------

    def _run(self, action):
        action()
        self.refresh()

    def _change_stackup(self):
        view, cv = self._view()
        if view is not None and gui.ask_stackup(cv.layout()):
            self.refresh()

    def _mark_ground(self):
        gui.mark_ground()
        self._check_ground()

    def _use_ports(self):
        gui.clear_ground()
        self._check_ground()

    def _hide_ground(self):
        for marker in self.markers:
            marker._destroy()
        self.markers = []
        self.refresh()

    def _check_ground(self):
        view, cv = self._view()
        if view is None:
            return
        for marker in self.markers:
            marker._destroy()
        self.markers = []
        result = gui.ground_check(view, cv)
        if result is None:
            self.ground_label.setText("choose a stackup first")
            return
        dbu = cv.layout().dbu
        shown = 0
        for region in result.net.values():
            for polygon in region.each():
                if shown >= MAX_MARKERS:
                    break
                marker = pya.Marker(view)
                marker.set(polygon.to_dtype(dbu))
                marker.color = 0x00d000
                marker.line_width = 2
                self.markers.append(marker)
                shown += 1
        text = result.summary()
        if shown >= MAX_MARKERS:
            text += f"\n(outline shows the first {MAX_MARKERS} polygons)"
        self.ground_label.setText(text)

    def _selected_ports(self):
        rows = sorted({_get(index.row) for index in _get(self.table.selectionModel).selectedRows()})
        return [self.port_rows[r] for r in rows if r < len(self.port_rows)]

    def _rows_selected(self):
        """Select the ports' shapes in the layout and bring them into view."""
        view, cv = self._view()
        ports = self._selected_ports()
        if view is None or not ports:
            return
        layout = cv.layout()
        paths, box = [], pya.Box()
        for port in ports:
            li = layout.find_layer(port.layer, 0)
            for shape, trans, inst_path in port.items:
                p = pya.ObjectInstPath()
                p.cv_index = view.active_cellview_index
                p.top = cv.cell.cell_index()
                for element in inst_path or []:
                    p.append_path(element)
                p.layer = li
                p.shape = shape
                paths.append(p)
                box += shape.bbox().transformed(trans)
        view.object_selection = paths
        dbox = box.to_dtype(layout.dbu)
        if not dbox.inside(view.box()):
            margin = max(dbox.width(), dbox.height(), 5.0)
            view.zoom_box(dbox.enlarged(margin, margin))

    def _edit(self):
        view, cv = self._view()
        ports = self._selected_ports()
        if view is None or not ports:
            return
        shapes = [(shape, trans) for port in ports for shape, trans, _ in port.items]
        gui.edit_ports(view, cv, shapes)
        self.refresh()

    def _delete(self):
        view, cv = self._view()
        ports = self._selected_ports()
        if view is None or not ports:
            return
        numbers = ", ".join(str(p.number) for p in ports)
        if pya.MessageBox.question("EM Export", f"Delete the shapes of port(s) {numbers}?",
                                   pya.MessageBox.Yes | pya.MessageBox.No) != pya.MessageBox.Yes:
            return
        view.clear_selection()
        view.transaction("Delete ports")
        try:
            for port in ports:
                for shape, _, _ in port.items:
                    shape.delete()
        finally:
            view.commit()
        self.refresh()
