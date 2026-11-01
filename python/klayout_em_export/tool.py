"""EM Port tool (toolbar): click a metal edge for a via port, Shift+click into a gap for an in-plane port.

The port shape goes on the next free port layer of the current cell: a zero-width box along the edge (via port)
or a box that bridges the gap (in-plane port). Then the port dialog opens; Cancel removes the shape again.
"""
import os

import pya

from . import gui
from .locate import edge_at, gap_at, next_port_layer
from .ports import PortSettings
from .stackup import Stackup

def _status(text, seconds):
    """Status bar message (KLayout 0.29: MainWindow.message, time in ms; LayoutView has none)."""
    pya.Application.instance().main_window().message(text, seconds * 1000)


def _get(value, *args):
    """KLayout exposes some getters as properties, others as methods, depending on the version; accept both."""
    return value(*args) if callable(value) else value


HINT = "EM Port: click a metal edge for a via port, Shift+click into a gap between metals for an in-plane port (visible layers only)"


class PortTool(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self.layout_view = view
        self.marker = None
        self._stackup = (None, None)     # (path, Stackup) cache

    def stackup(self):
        """The current layout's stackup (cached), or None."""
        cv = self.layout_view.active_cellview()
        path = gui.stackup_path(cv.layout() if cv is not None else None)
        if self._stackup[0] != path:
            try:
                self._stackup = (path, Stackup(path))
            except Exception:           # no or unreadable stackup: the click asks for one
                self._stackup = (path, None)
        return self._stackup[1]

    def activated(self):
        _status(HINT, 10)

    def deactivated(self):
        self._clear()

    def _clear(self):
        if self.marker is not None:
            self.marker._destroy()
            self.marker = None

    def _candidate(self, p, buttons, layers="visible"):
        """('via', metal, Box) or ('plane', metal, Box, direction) at DPoint p, or None. Searches the visible
        layers; layers=None searches all drawn metals."""
        cv = self.layout_view.active_cellview()
        stackup = self.stackup()
        if cv is None or cv.layout() is None or stackup is None:
            return None
        layout, cell = cv.layout(), cv.cell
        if layers == "visible":
            layers = self._visible_layers()
        point = pya.Point(round(p.x / layout.dbu), round(p.y / layout.dbu))
        shown = self.layout_view.box()
        tol = max(1, round(max(shown.width(), shown.height()) / 150 / layout.dbu))
        if buttons & pya.ButtonState.ShiftKey:
            found = gap_at(layout, cell, stackup, point, 20 * tol, layers)
            return None if found is None else ("plane",) + tuple(found)
        found = edge_at(layout, cell, stackup, point, tol, layers)
        return None if found is None else ("via", found[0], found[1].bbox())

    def _visible_layers(self):
        """GDS layer numbers (datatype 0) shown in the layer panel for the current layout: a click picks only what
        the designer sees. A hidden group hides its members (visible is the effective visibility, visible?(true))."""
        index = _get(self.layout_view.active_cellview_index)
        layout = self.layout_view.active_cellview().layout()
        layers = set()
        it = self.layout_view.begin_layers()
        while not it.at_end():
            node = it.current()
            li = _get(node.layer_index)
            if not _get(node.has_children) and _get(node.cellview) == index and _get(node.visible, True) and li >= 0:
                info = layout.get_info(li)
                if info.datatype == 0:
                    layers.add(info.layer)
            it.next()
        return layers

    def _hidden_hint(self, p, buttons):
        """Status text when the only candidate under the cursor is on a hidden layer, else None."""
        found = self._candidate(p, buttons, layers=None)
        if found is None:
            return None
        kind = "gap" if found[0] == "plane" else "edge"
        return f"{found[1]} {kind} here, but {found[1]} is hidden: show the layer to place a port on it"

    def mouse_moved_event(self, p, buttons, prio):
        if not prio:
            return False
        self._clear()
        found = self._candidate(p, buttons)
        if found is not None:
            dbu = self.layout_view.active_cellview().layout().dbu
            self.marker = pya.Marker(self.layout_view)
            self.marker.set(found[2].to_dtype(dbu))
            self.marker.color = 0xff00ff
            self.marker.line_width = 3
            _status(f"{'via port on' if found[0] == 'via' else 'in-plane port across a gap in'} {found[1]}", 2)
        else:
            hint = self._hidden_hint(p, buttons)
            if hint:
                _status(hint, 2)
        return False

    def mouse_click_event(self, p, buttons, prio):
        if not prio or not buttons & pya.ButtonState.LeftButton:
            return False
        if self.stackup() is None:
            cv = self.layout_view.active_cellview()
            if cv is None or cv.layout() is None or not gui.ask_stackup(cv.layout()):
                return True
        found = self._candidate(p, buttons)
        self._clear()
        if found is None:
            _status(self._hidden_hint(p, buttons)
                    or ("No metal edge here" if not buttons & pya.ButtonState.ShiftKey
                        else "No gap between two shapes of one metal here"), 5)
            return True
        cv = self.layout_view.active_cellview()
        layout, cell = cv.layout(), cv.cell
        layer = next_port_layer(layout, cell, stackup=self.stackup())
        if layer is None:
            pya.MessageBox.warning("EM Export", "All port layers 201..299 are used in this cell.", pya.MessageBox.Ok)
            return True
        self.layout_view.transaction("Add port")
        try:
            shape = cell.shapes(layout.layer(layer, 0)).insert(found[2])
        finally:
            self.layout_view.commit()
        self.layout_view.add_missing_layers()
        current = (PortSettings("Z") if found[0] == "via"
                   else PortSettings(found[3], target=found[1]))
        if not gui.edit_ports(self.layout_view, cv, [(shape, pya.ICplxTrans())], current):
            self.layout_view.transaction("Remove cancelled port")
            try:
                shape.delete()
            finally:
                self.layout_view.commit()
        else:
            _status(f"port {layer - 200} on layer {layer}", 5)
        gui.refresh_panel()
        return True


class PortToolFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = True
        self.register(-1000, "em_port_tool", "EM Port", gui.PORT_ICON)

    def create_plugin(self, manager, root, view):
        return PortTool(view)
