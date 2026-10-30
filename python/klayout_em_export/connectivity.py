"""Ground net: the metal connected to a ground shape through vias, inside the export region.

Lightweight on purpose: merged metal polygons per layer, grown through the vias between vertically adjacent metals
(from the stackup's z positions) until nothing new is added. Only wiring is traced: conductor layers of the
stackup above the device level. Activ (and every via that touches it, like Cont) is left out, because tracing
through it merges source and drain, and so all nets, through the transistor diffusions; sheets (resistors,
PEC reference sheets) are not wiring either. A transistor or resistor is an open circuit for this check.

The ground shape is marked by the user, or found from the via ports: of the nets at both ends of the via ports,
the one most ports reach is ground (on a tie, the larger one: ground planes are large).
"""
import pya

DEVICE_LEVEL = {"Activ"}            # SG13G2: diffusion, below Metal1; see the module doc
OTHER_NETS_LIMIT = 300              # count the separate other nets only up to this many polygons


def wiring(stackup):
    """(metal layers {GDS layer: name}, connections [(via layer, layer below, layer above)]) that are traced."""
    metals = {l.layer: l.name for l in stackup.layers
              if l.kind == "conductor" and l.layer not in stackup.derived and l.name not in DEVICE_LEVEL}
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


def flood(metals, vias, connections, seed):
    """Net grown from seed {layer: Region}: {layer: Region of the metal polygons in the net}."""
    empty = pya.Region()
    net = {layer: metals[layer].interacting(region) for layer, region in seed.items() if layer in metals}
    changed = True
    while changed:
        changed = False
        for via, below, above in connections:
            if via not in vias:
                continue
            touching = vias[via].interacting(net.get(below, empty)) + vias[via].interacting(net.get(above, empty))
            if touching.is_empty():
                continue
            for layer in (below, above):
                if layer not in metals:
                    continue
                grown = metals[layer].interacting(touching + net.get(layer, empty))
                if grown.count() > net.get(layer, empty).count():
                    net[layer] = grown
                    changed = True
    return {layer: region for layer, region in net.items() if not region.is_empty()}


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

    def summary(self):
        if not self.net:
            return self.source
        per_layer = ", ".join(f"{self.names[l]} {r.count()}" for l, r in sorted(self.net.items()))
        lines = [f"ground ({self.source}): {per_layer} polygon(s)"]
        if self.via_ports:
            lines.append(f"via ports reaching ground: {', '.join(map(str, self.ports)) or 'none'} "
                         f"of {len(self.via_ports)}")
        if self.pieces > 1:
            lines.append(f"the marked ground is {self.pieces} separate pieces in the region (connected outside?)")
        others = f"{self.other_polygons} other metal polygon(s)"
        if self.other_nets is not None:
            others += f" in {self.other_nets} separate net(s)"
        lines.append(others)
        return "\n".join(lines)


def check_ground(layout, cell, stackup, box=None, seeds=(), ports=None):
    """Ground net in cell (clipped to box, Box in dbu). seeds: [(GDS layer, Point)] marked ground shapes; without
    them the ground is found from ports ({layer: Port} from ports.collect_ports)."""
    metal_names, connections = wiring(stackup)
    metals = layer_regions(layout, cell, metal_names, box)
    vias = layer_regions(layout, cell, [c[0] for c in connections], box)
    result = GroundCheck()
    result.names = metal_names
    port_ends = []                  # (port number, layer, Region of the metal at the port line)
    for port in (ports or {}).values():
        s = port.settings
        if s is None or not s.is_via:
            continue
        result.via_ports.append(port.number)
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

    if seeds:
        result.source = f"{len(seeds)} marked shape(s)"
        pieces = []
        for layer, point in seeds:
            seed = pya.Region(pya.Box(point, point).enlarged(1, 1))
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
        nets = []                   # [net, set of port numbers]
        for number, layer, region in port_ends:
            found = next((n for n in nets if _touches(n[0], layer, region)), None)
            if found is None:
                found = [flood(metals, vias, connections, {layer: region}), set()]
                nets.append(found)
            found[1].add(number)
        if not nets:
            result.source = ("no ground: mark a ground shape, or add via ports whose ends lie on metal"
                             if result.via_ports or not ports else "no ground: mark a ground shape or add via ports")
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
            start = pya.Region(next(iter(other[layer].each())))
            net = flood(metals, vias, connections, {layer: start})
            result.other_nets += 1
            for l, region in net.items():
                if l in other:
                    other[l] = other[l].not_interacting(region)
            other[layer] = other[layer].not_interacting(start)    # always progress, even if the seed was lost
            other = {l: r for l, r in other.items() if not r.is_empty()}
    return result
