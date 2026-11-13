"""Ground net: the metal connected to a ground shape through vias, inside the export region.

Lightweight on purpose: merged metal polygons per layer, grown through the vias between vertically adjacent metals
(from the stackup's z positions) until nothing new is added. Only wiring is traced: conductor layers of the
stackup above the device level. The technology's device level (SG13G2: Activ), and every via that touches it
(like Cont), is left out, because tracing
through it merges source and drain, and so all nets, through the transistor diffusions; sheets (resistors,
PEC reference sheets) are not wiring either. A transistor or resistor is an open circuit for this check.

The ground shape is marked by the user, or found from the via ports: of the nets at both ends of the via ports,
the one most ports reach is ground (on a tie, the larger one: ground planes are large). Ports of replaced devices
do not count: their only traced end is the device terminal.

The net is DC connectivity. A short circuit at a port (and ground at a cut, boundary.py) is judged near the port
only (connected_near): metal that reaches ground only through a line leaving the port's neighbourhood (a balun or
inductor winding grounded at its far end, a grounded stub) is a DC path, but no RF short.
"""
import pya

from .ports import device_of
from .tech import device_level_names

OTHER_NETS_LIMIT = 300              # count the separate other nets only up to this many polygons
NEAR_UM = 10.0                      # neighbourhood of a port or cut (µm, at least the port's own length): connected
                                    # within it = a short; connected only through metal leaving it = a line


def wiring(stackup):
    """(metal layers {GDS layer: name}, connections [(via layer, layer below, layer above)]) that are traced."""
    device_level = device_level_names()      # see the module doc
    metals = {l.layer: l.name for l in stackup.layers
              if l.kind == "conductor" and l.layer not in stackup.derived and l.name not in device_level}
    connections = []
    for via, (below, above) in stackup.via_neighbors().items():
        if len(below) == 1 and len(above) == 1 and below[0].layer in metals and above[0].layer in metals:
            connections.append((via, below[0].layer, above[0].layer))
    return metals, connections


def layer_regions(layout, cell, layers, box=None, datatype=0):
    """{GDS layer: merged Region} of the given layers in cell, clipped to box (Box in dbu) if given."""
    out = {}
    for layer in layers:
        li = layout.find_layer(layer, datatype)
        if li is None:
            continue
        region = pya.Region(cell.begin_shapes_rec(li) if box is None else cell.begin_shapes_rec_touching(li, box))
        if box is not None:
            region &= pya.Region(box)
        region.merge()
        if not region.is_empty():
            out[layer] = region
    return out


def via_blocks(vias, below, above):
    """vias as blocks for tracing: the areas where the metal below and above overlap that hold at least one via. A
    via connects only the metal polygon below and the one above that hold it, and each overlap area lies in one
    polygon of each, so the blocks connect exactly what the single vias connect - with one polygon per via array
    instead of thousands of vias, which made tracing slow (77k vias per layer in a large PA). The metals are grown
    by 1 dbu: a via touching a metal edge connects, as in flood.
    For the checks only: the export keeps every via (gds2palace corrects merged via arrays itself)."""
    return (below.sized(1) & above.sized(1)).interacting(vias)


def _touching(small, large):
    """The polygons of small (merged, e.g. vias) that touch large: small.interacting(large), but a boolean AND first,
    which is much faster for many small polygons against a large one with many holes (77k vias against a cheesed
    plane: 0.7 s instead of 3.5 s). large is grown by 1 dbu so that touching, not only overlapping, counts."""
    return small.interacting(small & large.sized(1))


def flood(metals, vias, connections, seed, stop=None):
    """Net grown from seed {layer: Region}: {layer: Region of the metal polygons in the net}: the metal polygons
    reached through vias, and those touching a net polygon on its own layer. stop(net): checked after each step;
    True returns the net grown so far (a yes/no question needs no full net).
    Grown from the frontier: each step tests only the polygons added in the step before, against the vias and metal
    not yet in the net. Testing many vias against a large polygon is slow (77k vias against a cheesed plane with
    1000 holes: seconds), so each such test is done once, not in every step."""
    net = {layer: metals[layer].interacting(region) for layer, region in seed.items() if layer in metals}
    net = {layer: region for layer, region in net.items() if not region.is_empty()}
    # copies: they shrink in place below (-=), and metals and vias are the caller's, used by every other flood
    pool = {layer: region - net[layer] if layer in net else region.dup() for layer, region in metals.items()}
    left = {via: vias[via].dup() for via, _, _ in connections if via in vias}
    new = dict(net)
    while new and (stop is None or not stop(net)):
        probes = {layer: region.dup() for layer, region in new.items()}     # same layer: touching polygons
        for via, below, above in connections:
            if via not in left:
                continue
            hit = pya.Region()
            for layer in (below, above):
                if layer in new:
                    hit += _touching(left[via], new[layer])
            if hit.is_empty():
                continue
            left[via] -= hit
            for layer in (below, above):
                probes[layer] = probes[layer] + hit if layer in probes else hit
        new = {}
        for layer, probe in probes.items():
            if layer not in pool:
                continue
            fresh = pool[layer].interacting(probe)
            if fresh.is_empty():
                continue
            pool[layer] -= fresh
            net[layer] = net[layer] + fresh if layer in net else fresh
            new[layer] = fresh
    return net


def near_window(box, dbu):
    """The neighbourhood of a port or cut (box in dbu) that connected_near looks in: box grown by NEAR_UM, or by its
    own length if that is longer (a wide ground strip: its vias may be further from the cut)."""
    grow = max(round(NEAR_UM / dbu), box.width(), box.height())
    return box.enlarged(grow, grow)


def connected_near(metals, vias, connections, start, target, window):
    """Whether start {layer: Region} connects to target {layer: Region} through the metal and vias inside window
    (Box in dbu) alone. A path that leaves the window (a coil, a long line) does not count: it has its own
    inductance, a port across it measures that, not a short."""
    w = pya.Region(window)
    near = {layer: region & w for layer, region in metals.items() if region.bbox().overlaps(window)}
    near_vias = {layer: region & w for layer, region in vias.items() if region.bbox().overlaps(window)}
    goal = {layer: region & w for layer, region in target.items()}
    seed = {layer: region & w for layer, region in start.items()}

    def reached(net):
        return any(_touches(net, layer, region) for layer, region in goal.items() if not region.is_empty())

    return reached(flood(near, near_vias, connections, seed, stop=reached))


def _area(net):
    return sum(region.area() for region in net.values())


def _touches(net, layer, region):
    return layer in net and not net[layer].interacting(region).is_empty()


class GroundCheck:
    def __init__(self):
        self.net = {}               # {GDS layer: Region} of the ground net
        self.names = {}             # GDS layer -> stackup name
        self.source = ""            # how the ground was found
        self.ports = []             # numbers of the via ports that reach the ground net
        self.via_ports = []         # numbers of all via ports with settings
        self.pieces = 1             # separate ground pieces (marked shapes that do not connect in the region)
        self.other_polygons = 0     # metal polygons not in the ground net
        self.other_nets = None      # number of separate other nets, None if not counted (too many polygons)
        self.metals = {}            # {GDS layer: merged Region} of the traced metals in the region
        self.vias = {}              # {GDS layer: Region} of the vias between them, as blocks (via_blocks)
        self.connections = []       # [(via layer, layer below, layer above)]
        self.shorted = []           # numbers of via ports whose two ends are on the same net (a short circuit)

    def summary(self):
        if not self.net:
            return self.source
        per_layer = ", ".join(f"{self.names[l]} {r.count()}" for l, r in sorted(self.net.items()))
        lines = [f"ground ({self.source}): {per_layer} polygon(s)"]
        if self.via_ports:
            lines.append(f"via ports reaching ground: {', '.join(map(str, self.ports)) or 'none'} "
                         f"of {len(self.via_ports)}")
        if self.shorted:
            lines.append(f"short circuit: both ends of via port(s) {', '.join(map(str, self.shorted))} are on the "
                         "same net")
        if self.pieces > 1:
            lines.append(f"the marked ground is {self.pieces} separate pieces in the region (connected outside?)")
        others = f"{self.other_polygons} other metal polygon(s)"
        if self.other_nets is not None:
            others += f" in {self.other_nets} separate net(s)"
        lines.append(others)
        return "\n".join(lines)


def shorted_ports(metals, vias, connections, port_ends, windows):
    """Numbers of the via ports whose two ends (port_ends: [(port number, layer, Region at the port line)]) are
    connected through the traced metal and vias near the port (windows: {port number: Box from near_window}): such
    a port measures a short circuit. Ends joined only far away (a winding grounded at its other end) are not."""
    ends = {}                       # port number -> {layer: Region of the metal at that end}
    for number, layer, region in port_ends:
        ends.setdefault(number, {}).setdefault(layer, region)
    out = []
    for number, by_layer in sorted(ends.items()):
        if len(by_layer) < 2:
            continue                # one end on a sheet (REF_FOR_TRANSISTOR) or outside the metal: not traced
        (layer_a, a), (layer_b, b) = list(by_layer.items())[:2]
        if connected_near(metals, vias, connections, {layer_a: a}, {layer_b: b}, windows[number]):
            out.append(number)
    return out


def _seed(layout, cell, layer, point, box):
    """Region that a ground mark (a point in the marked shape) starts from: the point; or, if the point lies outside
    box (the region checked), the drawn shapes at the point, cut to box - a mark is one point in a shape that may
    reach far beyond the region (a ground plane)."""
    at = pya.Box(point, point).enlarged(1, 1)
    if box is None or box.contains(point):
        return pya.Region(at)
    li = layout.find_layer(layer, 0)
    if li is None:
        return pya.Region()
    shapes = pya.Region()
    it = cell.begin_shapes_rec_touching(li, at)
    while not it.at_end():
        if not it.shape().is_text():
            polygon = it.shape().polygon.transformed(it.trans())
            if polygon.inside(point):
                shapes.insert(polygon)
        it.next()
    return shapes & pya.Region(box)


def check_ground(layout, cell, stackup, box=None, seeds=(), ports=None):
    """Ground net in cell (clipped to box, Box in dbu). seeds: [(GDS layer, Point)] marked ground shapes; without
    them the ground is found from ports ({layer: Port} from ports.collect_ports)."""
    metal_names, connections = wiring(stackup)
    metals = layer_regions(layout, cell, metal_names, box)
    vias = layer_regions(layout, cell, [c[0] for c in connections], box)
    for via, below, above in connections:
        if via in vias and below in metals and above in metals:
            vias[via] = via_blocks(vias[via], metals[below], metals[above])
    result = GroundCheck()
    result.names = metal_names
    result.metals, result.vias, result.connections = metals, vias, connections
    port_ends = []                  # (port number, layer, Region of the metal at the port line)
    windows = {}                    # port number -> Box: the port's neighbourhood for the short check
    for port in (ports or {}).values():
        s = port.settings
        if s is None or not s.is_via:
            continue
        result.via_ports.append(port.number)
        bbox = pya.Box()
        for shape, trans, _ in port.items:
            bbox += shape.bbox().transformed(trans)
        windows[port.number] = near_window(bbox, layout.dbu)
        for name in (s.from_layer, s.to_layer):
            layer = next((l for l, n in metal_names.items() if n == name), None)
            if layer is None or layer not in metals:
                continue
            for shape, trans, _ in port.items:
                line = pya.Region(shape.bbox().transformed(trans).enlarged(1, 1))
                touched = metals[layer].interacting(line)
                if not touched.is_empty():
                    port_ends.append((port.number, layer, touched))
    result.via_ports.sort()
    result.shorted = shorted_ports(metals, vias, connections, port_ends, windows)

    if seeds:
        result.source = f"{len(seeds)} marked shape(s)"
        pieces = []
        for layer, point in seeds:
            seed = _seed(layout, cell, layer, point, box)
            if any(_touches(piece, layer, seed) for piece in pieces):
                continue
            piece = flood(metals, vias, connections, {layer: seed})
            if piece:
                pieces.append(piece)
        if not pieces:
            result.source = "the marked ground shapes are not in the region (or not on a traced metal)"
            return result
        result.pieces = len(pieces)
        for piece in pieces:
            for layer, region in piece.items():
                result.net[layer] = (result.net[layer] + region) if layer in result.net else region
    else:
        # a device port's only traced end is the device terminal (its other end is the REF sheet, not traced): it
        # says nothing about which net is ground, so only the other via ports vote
        device_ports = {p.number for p in (ports or {}).values() if device_of(p) is not None}
        nets = []                   # [net, set of port numbers]
        for number, layer, region in port_ends:
            if number in result.shorted or number in device_ports:
                continue            # shorted: both ends on one net, says nothing about which net is ground
            found = next((n for n in nets if _touches(n[0], layer, region)), None)
            if found is None:
                found = [flood(metals, vias, connections, {layer: region}), set()]
                nets.append(found)
            found[1].add(number)
        if not nets:
            if result.via_ports and set(result.via_ports) <= device_ports:
                result.source = "no ground: device ports do not show it; mark a ground shape or add pad ports"
            elif result.via_ports or not ports:
                result.source = "no ground: mark a ground shape, or add via ports whose ends lie on metal"
            else:
                result.source = "no ground: mark a ground shape or add via ports"
            return result
        best = max(nets, key=lambda n: (len(n[1]), _area(n[0])))
        result.net = best[0]
        result.source = "found from the via ports"
    result.ports = sorted({number for number, layer, region in port_ends if _touches(result.net, layer, region)})

    other = {layer: region.not_interacting(result.net[layer]) if layer in result.net else region
             for layer, region in metals.items()}
    other = {layer: region for layer, region in other.items() if not region.is_empty()}
    result.other_polygons = sum(region.count() for region in other.values())
    if result.other_polygons <= OTHER_NETS_LIMIT:
        result.other_nets = 0
        while other:
            layer = next(iter(other))
            # copy the polygon while its iterator is alive: next(region.each()) leaves a dangling reference
            # (access violation in KLayout 0.29.4)
            for polygon in other[layer].each():
                start = pya.Region(polygon)
                break
            net = flood(metals, vias, connections, {layer: start})
            result.other_nets += 1
            for l, region in net.items():
                if l in other:
                    other[l] = other[l].not_interacting(region)
            other[layer] = other[layer].not_interacting(start)    # always progress, even if the seed was lost
            other = {l: r for l, r in other.items() if not r.is_empty()}
    return result


def port_nets(ports, check):
    """{port layer: (net id, on the ground net, signal layer name or None)} of each port's signal end, from check
    (a GroundCheck of the same region): for a device port its terminal (the other end is the device's REF patch,
    which is not traced); for a port between two metals the end that is not on the ground net, or, if both are and
    they are joined only away from the port (not check.shorted), the smaller metal. The signal layer is None where
    that is ambiguous (a short, or both ends on other nets). Ports on the same net share
    the net id. A circuit wrapper ties them together for DC: a port measures a voltage difference, so the EM model
    alone does not fix the absolute potential of a device whose ports end on its floating REF patch."""
    nets = []                   # [{layer: Region}]
    out = {}

    def net_id(layer, region):
        for i, net in enumerate(nets):
            if layer in net and not net[layer].interacting(region).is_empty():
                return i
        nets.append(flood(check.metals, check.vias, check.connections, {layer: region}))
        return len(nets) - 1

    by_name = {name: layer for layer, name in check.names.items()}
    for layer, port in ports.items():
        s = port.settings
        if s is None:
            continue
        ends = []
        for name in (s.layer_names() if s.is_via else [s.target]):
            metal = by_name.get(name)
            if metal is None or metal not in check.metals:
                continue        # a sheet (REF_FOR_TRANSISTOR) or a layer that is not traced
            seed = pya.Region()
            for shape, trans, _ in port.items:
                seed += check.metals[metal].interacting(pya.Region(shape.bbox().transformed(trans).enlarged(1, 1)))
            if not seed.is_empty():
                ground = _touches(check.net, metal, seed)
                ends.append((ground, net_id(metal, seed), name, seed.area()))
        signal = [e for e in ends if not e[0]]
        if not signal and len(ends) == 2 and port.number not in check.shorted:
            # both ends on the ground net, joined only away from the port (a winding grounded at its other end):
            # the signal end is the smaller metal, the ground end the plane
            signal = [min(ends, key=lambda e: e[3])]
        signal = signal or ends
        if signal:
            ground, net, name, _ = signal[0]
            other_is_sheet = any(by_name.get(n) is None for n in s.layer_names())   # e.g. REF_FOR_TRANSISTOR
            known = len(signal) == 1 and (len(ends) == 2 or other_is_sheet)
            out[layer] = (net, ground, name if known else None)
    return out
