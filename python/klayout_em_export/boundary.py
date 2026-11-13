"""Ports where conductors cross the EM region box: the export cuts them there.

A crossing is a piece of a metal edge that lies on the box edge after clipping. Crossings of the ground net
(connectivity.check_ground) get no port, unless they are joined to the ground metal at the cut only away from the
cut (connectivity.connected_near: a balun winding grounded at its far end is a signal), and neither does a plane: a metal that covers the whole side of the box
(the crossing is as long as that side) is a plane, not a line, whether or not it is marked as ground. A signal crossing gets a via port along the cut, from the signal metal to
the ground metal found at the cut (the one closest in height if there are several): a zero-width box on the box
edge, in the source layout, with complete settings (from = lower metal, to = upper metal, direction Z, as the port
dialog's default). The export clips the metal exactly there, so the port sits on the cut.

As port walls (port_wall=True), a signal crossing gets an in-plane port instead: the same zero-width box, on the cut
metal (target), pointing into the region. It needs ground metal reaching the same side of the box, on any metal,
also the cut metal itself (a coplanar line: ground strips beside it); a via port needs it on another metal. Such a port needs gds2palace's port wall on that side (a PEC wall at the
layout edge; the port is then calibrated): the export writes it into the .simcfg (port_wall_sides). Without a port
wall, an in-plane port at the layout edge has no ground to connect to, so via ports stay the default.

This needs a region that is kept with the layout, so it works on the EM region box (layer 800/0) only.

With several boxes (regions.py), each box is a piece and is checked on its own; a crossing on a cut (an edge shared
with another piece) always gets an in-plane port wall port of this piece (OWNER_KEY = the piece's name), whatever the
port wall choice for the outer sides: the two ports of a cut, one per piece, are joined after the simulation, which
needs both reference planes on the cut. A via port there would not be calibrated.
"""
import pya

from .connectivity import connected_near, near_window
from .export import port_layer_numbers
from .locate import create_layers, free_port_layers, next_port_layer
from .ports import PROP_KEY, PortSettings
from .regions import OWNER_KEY

BOUNDARY_KEY = 201                  # property on ports made here: "boundary" (to find them again)
INWARD = {"left": "X", "right": "-X", "bottom": "Y", "top": "-Y"}     # in-plane port direction into the region
WALL_OF = {"left": "xmin", "right": "xmax", "bottom": "ymin", "top": "ymax"}   # gds2palace's name of the side


class Crossing:
    def __init__(self, side, layer, name, edge):
        self.side = side            # left, right, bottom, top
        self.layer = layer          # GDS layer of the metal
        self.name = name            # stackup name of the metal
        self.edge = edge            # pya.Edge on the box edge (dbu)
        self.ground = False         # part of the ground net: no port
        self.grounded_line = False  # on the ground net, but joined to the ground at the cut only far away: a signal
        self.plane = False          # covers the whole side of the box: a plane, no port
        self.ground_layer = None    # (GDS layer, name) of the ground metal at the cut, for a signal crossing
        self.wall_ground = False    # ground metal reaches this side of the box (any metal): enough for a port wall
        self.port = None            # number of a port already on this crossing
        self.piece = None           # name of the piece checked (several EM region boxes), else None
        self.cut = None             # regions.Cut the crossing lies on (shared with another piece), else None

    @property
    def needs_port(self):
        """a via port: needs ground on another metal at the cut"""
        return self.needs(False)

    def needs(self, port_wall=False):
        """Whether a port is proposed here: a signal crossing without a port, with ground for the kind of port
        (port_wall: ground reaching this side on any metal; else ground on another metal at the cut)."""
        if self.ground or self.plane or self.port is not None:
            return False
        if self.cut is not None:            # always a port wall port: joined at the cut after the simulation
            return self.wall_ground
        return self.wall_ground if port_wall else self.ground_layer is not None

    def status(self, port_wall=False):
        if self.ground:
            return "ground"
        if self.plane:
            return "plane across the whole side, no port"
        if self.port is not None:
            return f"port {self.port}"
        if self.cut is not None:
            other = self.cut.other(self.piece)
            if not self.wall_ground:
                return f"signal at the cut to {other}, no ground metal reaching the cut"
            return f"signal -> port on {self.name} at the cut to {other} (port wall, joined)"
        if port_wall:
            if not self.wall_ground:
                return "signal, no ground metal reaching this side"
            return f"signal -> port on {self.name} at the port wall ({WALL_OF[self.side]})"
        if self.ground_layer is None:
            return "signal, no ground metal at the cut"
        if self.grounded_line:
            return f"signal (grounded only away from the cut) -> port to {self.ground_layer[1]}"
        return f"signal -> port to {self.ground_layer[1]}"


def _sides(box):
    return {"left": pya.Edge(box.left, box.bottom, box.left, box.top),
            "right": pya.Edge(box.right, box.bottom, box.right, box.top),
            "bottom": pya.Edge(box.left, box.bottom, box.right, box.bottom),
            "top": pya.Edge(box.left, box.top, box.right, box.top)}


def _line(edge):
    """The crossing as a Region a touching test can use (a zero-width line grown by 1 dbu)."""
    return pya.Region(edge.bbox().enlarged(1, 1))


def _port_lines(layout, cell, box, stackup=None):
    """[(port number, Box, owner)] of the port shapes touching the box; owner: the piece a cut port belongs to
    (OWNER_KEY), else None."""
    out = []
    port_layers = port_layer_numbers(stackup)
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer not in port_layers or info.datatype != 0:
            continue
        it = cell.begin_shapes_rec_touching(li, box)
        while not it.at_end():
            if not it.shape().is_text():
                owner = it.shape().property(OWNER_KEY)
                out.append((info.layer - 200, it.shape().bbox().transformed(it.trans()),
                            owner if isinstance(owner, str) else None))
            it.next()
    return out


def find_crossings(layout, cell, stackup, box, ground, piece=None, cuts=()):
    """Crossings of the traced metals with the edge of box (Box in dbu), classified with ground (GroundCheck of
    the same box). With several EM region boxes: piece = the name of the box checked, cuts = its regions.Cuts; a
    crossing on a cut is matched only with a port of this piece, other crossings with ports of no piece or this one."""
    z = {l.layer: stackup.z_range(l) for l in stackup.layers}
    ports = _port_lines(layout, cell, box, stackup)
    out = []
    # sides of the box that ground metal reaches (any metal): enough ground for a port wall there
    grounded = {side for side, side_edge in _sides(box).items()
                if any(not r.interacting(_line(side_edge)).is_empty() for r in ground.net.values())}
    # a cut needs ground reaching the cut itself, not only its side of the box
    cut_grounded = {id(c) for c in cuts
                    if any(not r.interacting(_line(c.edge)).is_empty() for r in ground.net.values())}
    for layer, region in sorted(ground.metals.items()):
        edges = region.edges()
        for side, side_edge in _sides(box).items():
            on_side = edges & pya.Edges(side_edge)
            on_side.merge()
            for edge in on_side.each():
                # dup(): an object from Edges.each() points into the collection, which is gone after the loop
                crossing = Crossing(side, layer, ground.names[layer], edge.dup())
                crossing.piece = piece
                crossing.cut = next((c for c in cuts if c.contains(edge)), None)
                line = _line(edge)
                crossing.ground = layer in ground.net and not ground.net[layer].interacting(line).is_empty()
                crossing.wall_ground = (id(crossing.cut) in cut_grounded) if crossing.cut is not None else side in grounded
                crossing.plane = edge.length() >= side_edge.length() - 1
                owners = (piece,) if crossing.cut is not None else (None, piece)
                crossing.port = next((n for n, b, owner in ports
                                      if owner in owners and (b.width() == 0 or b.height() == 0)
                                      and not line.interacting(pya.Region(b.enlarged(1, 1))).is_empty()), None)
                candidates = [l for l, r in ground.net.items() if l != layer and not r.interacting(line).is_empty()]
                if crossing.ground and candidates and not crossing.plane:
                    # on the ground net, but is it ground here? Only if joined to the ground metal at the cut near
                    # the cut; else it reaches ground through a line (a winding grounded at its far end): a signal
                    at_cut = {l: ground.net[l].interacting(line) for l in candidates}
                    crossing.ground = connected_near(ground.metals, ground.vias, ground.connections,
                                                     {layer: ground.metals[layer].interacting(line)}, at_cut,
                                                     near_window(edge.bbox(), layout.dbu))
                    crossing.grounded_line = not crossing.ground
                if not crossing.ground:
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


def port_wall_sides(ports, box):
    """gds2palace port walls for the export of box (Box in dbu): the sides of box with an in-plane port on them
    (a port shape with an edge on that side of the box). ports: {layer: Port}. Returns e.g. ['xmin', 'xmax']."""
    out = set()
    for port in ports.values():
        if port.settings is None or port.settings.is_via:
            continue
        for shape, trans, _ in port.items:
            b = shape.bbox().transformed(trans)
            if b.left == box.left:
                out.add("xmin")
            if b.right == box.right:
                out.add("xmax")
            if b.bottom == box.bottom:
                out.add("ymin")
            if b.top == box.top:
                out.add("ymax")
    return [side for side in ("xmin", "xmax", "ymin", "ymax") if side in out]


def create_ports(view, cell, stackup, crossings, z0=50.0, port_wall=False):
    """Ports on the given crossings (those that need one), in cell: via ports to the ground metal at the cut, or
    with port_wall, in-plane ports on the cut metal pointing into the region (for a gds2palace port wall).
    Returns the new port numbers."""
    layout = cell.layout()
    z = {l.name: stackup.z_range(l) for l in stackup.layers}
    numbers = []
    needed = sum(c.needs(port_wall) for c in crossings)
    create_layers(layout, [(l, 0) for l in free_port_layers(layout, cell, needed, stackup=stackup)])
    view.transaction("Boundary ports")
    try:
        for crossing in crossings:
            if not crossing.needs(port_wall):
                continue
            layer = next_port_layer(layout, cell, stackup=stackup)
            if layer is None:
                break
            if port_wall or crossing.cut is not None:
                settings = PortSettings(INWARD[crossing.side], target=crossing.name, z0=z0)
            else:
                a, b = crossing.name, crossing.ground_layer[1]
                lower, upper = (a, b) if z[a] and z[b] and z[a][1] < z[b][1] else (b, a)
                settings = PortSettings("Z", lower, upper, z0=z0)
            # both properties at insertion: set_property can move the shape, a second call on the old reference
            # crashes KLayout 0.29.4
            props = [[PROP_KEY, settings.encode()], [BOUNDARY_KEY, "boundary"]]
            if crossing.cut is not None:
                props.append([OWNER_KEY, crossing.piece])
            properties = layout.properties_id(props)
            cell.shapes(layout.layer(layer, 0)).insert(crossing.edge.bbox(), properties)
            crossing.port = layer - 200
            numbers.append(layer - 200)
        view.add_missing_layers()  # inside the step: after it, KLayout 0.29.4 clears the undo list
    finally:
        view.commit()
    return numbers
