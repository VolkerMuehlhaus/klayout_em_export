"""Ports where conductors cross the EM region box: the export cuts them there.

A crossing is a piece of a metal edge that lies on the box edge after clipping. Crossings of the ground net
(connectivity.check_ground) get no port. A signal crossing gets a via port along the cut, from the signal metal to
the ground metal found at the cut (the one closest in height if there are several): a zero-width box on the box
edge, in the source layout, with complete settings (from = lower metal, to = upper metal, direction Z, as the port
dialog's default). The export clips the metal exactly there, so the port sits on the cut.

This needs a region that is kept with the layout, so it works on the EM region box (layer 800/0) only.
"""
import pya

from .locate import next_port_layer
from .ports import PROP_KEY, PortSettings

BOUNDARY_KEY = 201                  # property on ports made here: "boundary" (to find them again)


class Crossing:
    def __init__(self, side, layer, name, edge):
        self.side = side            # left, right, bottom, top
        self.layer = layer          # GDS layer of the metal
        self.name = name            # stackup name of the metal
        self.edge = edge            # pya.Edge on the box edge (dbu)
        self.ground = False         # part of the ground net: no port
        self.ground_layer = None    # (GDS layer, name) of the ground metal at the cut, for a signal crossing
        self.port = None            # number of a port already on this crossing

    @property
    def needs_port(self):
        return not self.ground and self.port is None and self.ground_layer is not None

    def status(self):
        if self.ground:
            return "ground"
        if self.port is not None:
            return f"port {self.port}"
        if self.ground_layer is None:
            return "signal, no ground metal at the cut"
        return f"signal -> port to {self.ground_layer[1]}"


def _sides(box):
    return {"left": pya.Edge(box.left, box.bottom, box.left, box.top),
            "right": pya.Edge(box.right, box.bottom, box.right, box.top),
            "bottom": pya.Edge(box.left, box.bottom, box.right, box.bottom),
            "top": pya.Edge(box.left, box.top, box.right, box.top)}


def _line(edge):
    """The crossing as a Region a touching test can use (a zero-width line grown by 1 dbu)."""
    return pya.Region(edge.bbox().enlarged(1, 1))


def _port_lines(layout, cell, box):
    """[(port number, Box)] of the port shapes touching the box."""
    out = []
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if not 201 <= info.layer <= 299 or info.datatype != 0:
            continue
        it = cell.begin_shapes_rec_touching(li, box)
        while not it.at_end():
            if not it.shape().is_text():
                out.append((info.layer - 200, it.shape().bbox().transformed(it.trans())))
            it.next()
    return out


def find_crossings(layout, cell, stackup, box, ground):
    """Crossings of the traced metals with the edge of box (Box in dbu), classified with ground (GroundCheck of
    the same box)."""
    z = {l.layer: stackup.z_range(l) for l in stackup.layers}
    ports = _port_lines(layout, cell, box)
    out = []
    for layer, region in sorted(ground.metals.items()):
        edges = region.edges()
        for side, side_edge in _sides(box).items():
            on_side = edges & pya.Edges(side_edge)
            on_side.merge()
            for edge in on_side.each():
                # dup(): an object from Edges.each() points into the collection, which is gone after the loop
                crossing = Crossing(side, layer, ground.names[layer], edge.dup())
                line = _line(edge)
                crossing.ground = layer in ground.net and not ground.net[layer].interacting(line).is_empty()
                crossing.port = next((n for n, b in ports if not line.interacting(pya.Region(b.enlarged(1, 1))).is_empty()
                                      and (b.width() == 0 or b.height() == 0)), None)
                if not crossing.ground:
                    candidates = [l for l, r in ground.net.items() if l != layer and not r.interacting(line).is_empty()]
                    if candidates and z.get(layer):
                        mid = (z[layer][1] + z[layer][2]) / 2
                        best = min(candidates, key=lambda l: abs((z[l][1] + z[l][2]) / 2 - mid) if z.get(l) else 1e9)
                        crossing.ground_layer = (best, ground.names[best])
                out.append(crossing)
    return out


def moved_ports(layout, cell, box):
    """Numbers of the ports made here (BOUNDARY_KEY) that no longer lie on the edge of box: the box was moved."""
    sides = pya.Edges()
    for side in _sides(box).values():
        sides.insert(side)
    out = []
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if not 201 <= info.layer <= 299 or info.datatype != 0:
            continue
        it = cell.begin_shapes_rec(li)
        while not it.at_end():
            shape = it.shape()
            if shape.property(BOUNDARY_KEY) == "boundary":
                b = shape.bbox().transformed(it.trans())
                if (pya.Edges(pya.Edge(b.p1, b.p2)) - sides).count() > 0:
                    out.append(info.layer - 200)
            it.next()
    return sorted(set(out))


def create_ports(view, cell, stackup, crossings, z0=50.0):
    """Via ports on the given crossings (those that need one), in cell. Returns the new port numbers."""
    layout = cell.layout()
    z = {l.name: stackup.z_range(l) for l in stackup.layers}
    numbers = []
    view.transaction("Boundary ports")
    try:
        for crossing in crossings:
            if not crossing.needs_port:
                continue
            layer = next_port_layer(layout, cell)
            if layer is None:
                break
            a, b = crossing.name, crossing.ground_layer[1]
            lower, upper = (a, b) if z[a] and z[b] and z[a][1] < z[b][1] else (b, a)
            # both properties at insertion: set_property can move the shape, a second call on the old reference
            # crashes KLayout 0.29.4
            properties = layout.properties_id([[PROP_KEY, PortSettings("Z", lower, upper, z0=z0).encode()],
                                               [BOUNDARY_KEY, "boundary"]])
            cell.shapes(layout.layer(layer, 0)).insert(crossing.edge.bbox(), properties)
            crossing.port = layer - 200
            numbers.append(layer - 200)
    finally:
        view.commit()
    view.add_missing_layers()
    return numbers
