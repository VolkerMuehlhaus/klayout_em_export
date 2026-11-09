"""EM Port tool (toolbar): click a metal edge for a via port, Shift+click into a gap for an in-plane port.
EM Ground tool: click a metal to mark it as ground (every traced metal drawn under the click, through the hierarchy,
so a stacked pad frame takes one click), Shift+click to unmark.
Split Region tool: click inside the EM region box to cut it into two pieces there, Shift+click for a horizontal cut.
Draw Region tool: drag a rectangle, it becomes the EM region box; Shift+drag adds one more box (a piece).

The port shape goes on the next free port layer of the current cell: a zero-width box along the edge (via port)
or a box that bridges the gap (in-plane port). Then the port dialog opens; Cancel removes the shape again.
"""
import os

import pya

from . import gui
from .locate import create_layers, edge_at, gap_at, metals_at, next_port_layer, via_layers
from .ports import PortSettings
from .stackup import Stackup

def _status(text, seconds):
    """Status bar message (KLayout 0.29: MainWindow.message, time in ms; LayoutView has none)."""
    pya.Application.instance().main_window().message(text, seconds * 1000)


def _get(value, *args):
    """KLayout exposes some getters as properties, others as methods, depending on the version; accept both."""
    return value(*args) if callable(value) else value


HINT = "EM Port: click a metal edge for a via port, Shift+click into a gap between metals for an in-plane port (visible layers only)"


def candidate(view, stackup, p, buttons, layers="visible"):
    """('via', metal, Box) or ('plane', metal, Box, direction) at DPoint p in view, or None. Searches the visible
    layers; layers=None searches all drawn metals. Shift in buttons: an in-plane port across a gap."""
    cv = view.active_cellview()
    if cv is None or cv.layout() is None or stackup is None:
        return None
    layout, cell = cv.layout(), cv.cell
    if layers == "visible":
        layers = visible_layers(view)
    point = pya.Point(round(p.x / layout.dbu), round(p.y / layout.dbu))
    shown = view.box()
    tol = max(1, round(max(shown.width(), shown.height()) / 150 / layout.dbu))
    if buttons & pya.ButtonState.ShiftKey:
        found = gap_at(layout, cell, stackup, point, 20 * tol, layers)
        return None if found is None else ("plane",) + tuple(found)
    found = edge_at(layout, cell, stackup, point, tol, layers)
    return None if found is None else ("via", found[0], found[1].bbox())


def visible_layers(view):
    """GDS layer numbers (datatype 0) shown in the layer panel for the current layout: a click picks only what the
    designer sees. A hidden group hides its members (visible is the effective visibility, visible?(true))."""
    index = _get(view.active_cellview_index)
    layout = view.active_cellview().layout()
    layers = set()
    it = view.begin_layers()
    while not it.at_end():
        node = it.current()
        li = _get(node.layer_index)
        if not _get(node.has_children) and _get(node.cellview) == index and _get(node.visible, True) and li >= 0:
            info = layout.get_info(li)
            if info.datatype == 0:
                layers.add(info.layer)
        it.next()
    return layers


def hidden_hint(view, stackup, p, buttons):
    """Status text when the only candidate under the cursor is on a hidden layer, else None."""
    found = candidate(view, stackup, p, buttons, layers=None)
    if found is None:
        return None
    kind = "gap" if found[0] == "plane" else "edge"
    return f"{found[1]} {kind} here, but {found[1]} is hidden: show the layer to place a port on it"


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
        return candidate(self.layout_view, self.stackup(), p, buttons, layers)

    def _hidden_hint(self, p, buttons):
        return hidden_hint(self.layout_view, self.stackup(), p, buttons)

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
        gui.backup_original(layout)
        create_layers(layout, [(layer, 0)])         # before the undo step (locate.create_layers)
        self.layout_view.transaction("Add port")
        try:
            shape = cell.shapes(layout.layer(layer, 0)).insert(found[2])
            self.layout_view.add_missing_layers()  # inside the step: after it, KLayout 0.29.4 clears the undo list
        finally:
            self.layout_view.commit()
        if found[0] == "via":   # from the clicked metal down to the next metal at the port (hidden ones count)
            current = PortSettings("Z", *via_layers(metals_at(layout, cell, self.stackup(), found[2]), found[1]))
        else:
            current = PortSettings(found[3], target=found[1])
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


GROUND_HINT = "EM Ground: click a metal to mark it as ground (all metals under the click), Shift+click to unmark"


def _no_metal(layout, cell, point):
    """Status text for a ground click that found no traced metal: names what is drawn there instead."""
    drawn = gui.layers_at_point(layout, cell, point)
    if not drawn:
        return "No metal here"
    return ("No metal of the stackup's wiring here (drawn: " + ", ".join(drawn) + "); ground must be a conductor "
            "layer of the stackup with datatype 0")


class GroundTool(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self.layout_view = view
        self.marker = None
        self._stackup = (None, None)

    stackup = PortTool.stackup

    def activated(self):
        _status(GROUND_HINT, 10)

    def deactivated(self):
        self._clear()

    def _clear(self):
        if self.marker is not None:
            self.marker._destroy()
            self.marker = None

    def _point(self, p):
        cv = self.layout_view.active_cellview()
        if cv is None or cv.layout() is None or cv.cell is None:
            return None, None
        return cv, p.to_itype(cv.layout().dbu)

    def mouse_moved_event(self, p, buttons, prio):
        if not prio:
            return False
        self._clear()
        cv, point = self._point(p)
        if cv is None or self.stackup() is None:
            return False
        metals = gui.metals_at_point(cv.layout(), cv.cell, self.stackup(), point)
        if metals:
            names = ", ".join(name for _, name in metals)
            unmark = buttons & pya.ButtonState.ShiftKey
            _status(("unmark ground on " if unmark else "mark ground on ") + names, 2)
            self.marker = pya.Marker(self.layout_view)
            self.marker.set(pya.DBox(p.x - 1, p.y - 1, p.x + 1, p.y + 1))
            self.marker.color = 0x40c040 if not unmark else 0xc04040
            self.marker.line_width = 3
        return False

    def mouse_click_event(self, p, buttons, prio):
        if not prio or not buttons & pya.ButtonState.LeftButton:
            return False
        cv, point = self._point(p)
        if cv is None:
            return True
        if self.stackup() is None and not gui.ask_stackup(cv.layout()):
            return True
        self._clear()
        layout, cell = cv.layout(), cv.cell
        if buttons & pya.ButtonState.ShiftKey:
            names = gui.unmark_ground_at(layout, cell, self.stackup(), point)
            _status(f"ground mark(s) removed on {', '.join(names)}" if names else "No ground mark here", 5)
        else:
            names = gui.mark_ground_at(layout, cell, self.stackup(), point)
            _status(f"ground marked on {', '.join(names)}" if names else _no_metal(layout, cell, point), 8)
        gui.refresh_panel()
        return True


class GroundToolFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = True
        self.register(-999, "em_ground_tool", "EM Ground", gui.GROUND_ICON)

    def create_plugin(self, manager, root, view):
        return GroundTool(view)


class PortToolFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = True
        self.register(-1000, "em_port_tool", "EM Port", gui.PORT_ICON)

    def create_plugin(self, manager, root, view):
        return PortTool(view)


SPLIT_HINT = ("Split Region: click inside an EM region box to cut it there (a vertical cut), Shift+click: a horizontal "
              "cut. Each piece becomes its own model; setupEM joins the results.")


class SplitTool(pya.Plugin):
    """Split Region: one click cuts the EM region box under the cursor into two pieces (regions.split_piece), on the
    grid. The left (lower) half keeps its number."""

    def __init__(self, view):
        super().__init__()
        self.layout_view = view
        self.marker = None

    def activated(self):
        _status(SPLIT_HINT, 10)

    def deactivated(self):
        self._clear()

    def _clear(self):
        if self.marker is not None:
            self.marker._destroy()
            self.marker = None

    def _target(self, p, buttons):
        """(cv, point dbu on the grid, the piece hit or None, vertical)."""
        from .regions import read_pieces
        cv = self.layout_view.active_cellview()
        if cv is None or cv.layout() is None or cv.cell is None:
            return None, None, None, True
        try:
            grid = float(self.layout_view.get_config("grid-micron") or 0)
        except ValueError:
            grid = 0
        if grid > 0:
            p = pya.DPoint(round(p.x / grid) * grid, round(p.y / grid) * grid)
        layout = cv.layout()
        point = p.to_itype(layout.dbu)
        vertical = not buttons & pya.ButtonState.ShiftKey
        minimum = round(1.0 / layout.dbu)             # no piece narrower than 1 um
        hit = None
        for piece in read_pieces(layout, cv.cell)[0]:
            b = piece.box
            if vertical and b.left + minimum <= point.x <= b.right - minimum and b.bottom < point.y < b.top:
                hit = piece
            elif not vertical and b.bottom + minimum <= point.y <= b.top - minimum and b.left < point.x < b.right:
                hit = piece
        return cv, point, hit, vertical

    def mouse_moved_event(self, p, buttons, prio):
        if not prio:
            return False
        self._clear()
        cv, point, hit, vertical = self._target(p, buttons)
        if hit is None:
            return False
        dbu = cv.layout().dbu
        b = hit.box.to_dtype(dbu)
        x, y = point.x * dbu, point.y * dbu
        self.marker = pya.Marker(self.layout_view)
        self.marker.set(pya.DBox(x, b.bottom, x, b.top) if vertical else pya.DBox(b.left, y, b.right, y))
        self.marker.color = 0xdc6e14
        self.marker.line_width = 2
        self.marker.line_style = 2
        _status(f"cut {hit.name or 'the EM region'} at {'x' if vertical else 'y'} = {x if vertical else y:g} µm", 2)
        return False

    def mouse_click_event(self, p, buttons, prio):
        if not prio or not buttons & pya.ButtonState.LeftButton:
            return False
        from .regions import split_piece
        self._clear()
        cv, point, hit, vertical = self._target(p, buttons)
        if cv is None:
            return True
        if hit is None:
            _status("Click inside an EM region box, at least 1 µm from its edges (Mark Region draws the first box)", 8)
            return True
        gui.backup_original(cv.layout())
        self.layout_view.transaction("Split EM region")
        try:
            low, high = split_piece(cv.layout(), cv.cell, point, vertical)
        finally:
            self.layout_view.commit()
        _status(f"Split into {low.name} and {high.name}: Create Proposed Ports puts the ports at the new cut", 10)
        gui.refresh_panel()
        return True


class SplitToolFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = True
        self.register(-998, "em_split_tool", "Split Region", gui.SPLIT_ICON)

    def create_plugin(self, manager, root, view):
        return SplitTool(view)


REGION_HINT = ("Draw EM Region: drag a rectangle, it becomes the EM region box. Shift+drag: one more box, a piece of "
               "a split region.")


def _on_grid(view, p):
    """p (DPoint) on the view's grid"""
    try:
        grid = float(view.get_config("grid-micron") or 0)
    except ValueError:
        grid = 0
    return pya.DPoint(round(p.x / grid) * grid, round(p.y / grid) * grid) if grid > 0 else p


class RegionTool(pya.Plugin):
    """Draw Region: press, drag and release draws the EM region box (gui.set_region_box), on the grid."""

    def __init__(self, view):
        super().__init__()
        self.layout_view = view
        self.start = None
        self.marker = None

    def activated(self):
        _status(REGION_HINT, 10)

    def deactivated(self):
        self._clear()
        self.start = None

    def _clear(self):
        if self.marker is not None:
            self.marker._destroy()
            self.marker = None

    def mouse_button_pressed_event(self, p, buttons, prio):
        if not prio or not buttons & pya.ButtonState.LeftButton:
            return False
        self.start = _on_grid(self.layout_view, p)
        self.grab_mouse()
        return True

    def mouse_moved_event(self, p, buttons, prio):
        if self.start is None:
            return False
        self._clear()
        box = pya.DBox(self.start, _on_grid(self.layout_view, p))
        self.marker = pya.Marker(self.layout_view)
        self.marker.set(box)
        self.marker.color = 0xd23cc8
        self.marker.line_width = 2
        self.marker.line_style = 2
        _status(f"EM region {box.width():g} x {box.height():g} µm" +
                (" (one more box)" if buttons & pya.ButtonState.ShiftKey else ""), 2)
        return True

    def mouse_button_released_event(self, p, buttons, prio):
        if self.start is None:
            return False
        box = pya.DBox(self.start, _on_grid(self.layout_view, p))
        self.start = None
        self.ungrab_mouse()
        self._clear()
        cv = self.layout_view.active_cellview()
        if cv is None or cv.layout() is None or cv.cell is None:
            return True
        if box.width() <= 0 or box.height() <= 0:
            _status("Drag a rectangle: press, move and release", 5)
            return True
        add = bool(buttons & pya.ButtonState.ShiftKey)
        if gui.set_region_box(self.layout_view, cv, box, add=add):
            where = ""
            if cv.ctx_cell().cell_index() != cv.cell.cell_index():
                where = (f" in cell {cv.cell.name}, the instance you descended into: the export takes that cell "
                         f"(Ascend first for the region in {cv.ctx_cell().name})")
            _status(f"EM region {'box added' if add else 'set'}: {box.width():g} x {box.height():g} µm" + where,
                    20 if where else 8)
            gui.refresh_panel()
        return True


class RegionToolFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = True
        self.register(-997, "em_region_tool", "EM Region", gui.REGION_ICON)

    def create_plugin(self, manager, root, view):
        return RegionTool(view)
