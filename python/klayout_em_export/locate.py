"""Find metals around a point or a port shape: which stackup metals are drawn there, the metal edge under a click
(via port) and the gap between two metals (in-plane port). Coordinates in dbu, in the given cell."""
import pya

from .export import PORT_LAYERS, port_layer_numbers


def drawn_metals(stackup):
    """[(name, GDS layer)] of the stackup metals drawn directly in the GDS, top to bottom.
    Derived layers (e.g. the SG13G2 resistor sheets) are computed by gds2palace and are left out."""
    return [(l.name, l.layer) for l in stackup.layers if l.is_metal and l.layer not in stackup.derived]


def _region(layout, cell, layer, box, datatype=0):
    li = layout.find_layer(layer, datatype)
    if li is None:
        return pya.Region()
    return pya.Region(cell.begin_shapes_rec_touching(li, box)).merged()


def metals_at(layout, cell, stackup, box):
    """Names of the stackup metals that touch box (a port shape's bbox), top to bottom."""
    return [name for name, layer in drawn_metals(stackup) if not _region(layout, cell, layer, box).is_empty()]


def via_layers(metals_here, clicked):
    """(from, to) metals of a new via port on an edge of the clicked metal. metals_here: the metals at the port, top
    to bottom (metals_at). A via port goes from the clicked metal down to the first metal it touches, never through
    one: from = the clicked metal (the signal, as in the user's guide), to = the next metal below. Without a metal
    below: to = the next metal above. ("", "") if the clicked metal is not at the port."""
    if clicked not in metals_here:
        return "", ""
    i = metals_here.index(clicked)
    if i + 1 < len(metals_here):
        return clicked, metals_here[i + 1]
    return clicked, metals_here[i - 1] if i > 0 else ""


def _manhattan(edge):
    return edge.p1.x == edge.p2.x or edge.p1.y == edge.p2.y


def _searched(stackup, layers):
    """(rank, name, GDS layer) of the drawn metals to search: all, or only those whose GDS layer is in layers (the
    EM Port tool passes the visible ones). The rank stays the metal's place in the stackup, top first."""
    return [(rank, name, layer) for rank, (name, layer) in enumerate(drawn_metals(stackup))
            if layers is None or layer in layers]


def edge_at(layout, cell, stackup, point, tol, layers=None):
    """(metal name, Edge) of the horizontal or vertical metal edge nearest to point within tol, preferring the
    upper metal when edges of several metals are equally close. None if there is none.
    layers: GDS layer numbers to search (None: all drawn metals)."""
    search = pya.Box(point, point).enlarged(tol, tol)
    best = None
    for rank, name, layer in _searched(stackup, layers):
        for edge in _region(layout, cell, layer, search).edges().each():
            if not _manhattan(edge) or not _projects(edge, point):
                continue
            d = edge.distance_abs(point)
            if d > tol:
                continue
            if best is None or (d, rank) < (best[0], best[1]):
                best = (d, rank, name, edge.dup())     # the edge must outlive the Edges it comes from
    return None if best is None else (best[2], best[3])


def _projects(edge, point):
    """point lies within the extent of the edge, measured along the edge."""
    if edge.p1.x == edge.p2.x:
        return min(edge.p1.y, edge.p2.y) <= point.y <= max(edge.p1.y, edge.p2.y)
    return min(edge.p1.x, edge.p2.x) <= point.x <= max(edge.p1.x, edge.p2.x)


def gap_at(layout, cell, stackup, point, reach, layers=None):
    """(metal name, Box, direction) of the narrowest gap around point between two shapes of one metal, looking up
    to reach in each direction: the box bridges the gap over the length both facing edges share. Direction X for
    a gap between left and right metal, Y for below and above. None if the point is on metal or no gap is found.
    layers: GDS layer numbers to search (None: all drawn metals)."""
    search = pya.Box(point, point).enlarged(reach, reach)
    best = None
    for rank, name, layer in _searched(stackup, layers):
        region = _region(layout, cell, layer, search)
        if region.is_empty() or not region.interacting(pya.Region(pya.Box(point, point).enlarged(1, 1))).is_empty():
            continue
        for direction in ("X", "Y"):
            box = _facing_edges(region, point, direction)
            if box is None:
                continue
            width = box.width() if direction == "X" else box.height()
            if width > reach:
                continue
            if best is None or (width, rank) < (best[0], best[1]):
                best = (width, rank, name, box, direction)
    return None if best is None else best[2:]


def _facing_edges(region, point, direction):
    """Box between the nearest metal edges on both sides of point (left/right for X, below/above for Y)."""
    along = (lambda p: p.y) if direction == "X" else (lambda p: p.x)
    across = (lambda p: p.x) if direction == "X" else (lambda p: p.y)
    lower, upper = None, None
    for edge in region.edges().each():
        if (across(edge.p1) != across(edge.p2)) or not min(along(edge.p1), along(edge.p2)) <= along(point) <= max(along(edge.p1), along(edge.p2)):
            continue
        position = across(edge.p1)
        if position <= across(point) and (lower is None or position > across(lower.p1)):
            lower = edge
        if position >= across(point) and (upper is None or position < across(upper.p1)):
            upper = edge
    if lower is None or upper is None or across(lower.p1) == across(upper.p1):
        return None
    lo = max(min(along(lower.p1), along(lower.p2)), min(along(upper.p1), along(upper.p2)))
    hi = min(max(along(lower.p1), along(lower.p2)), max(along(upper.p1), along(upper.p2)))
    if direction == "X":
        return pya.Box(across(lower.p1), lo, across(upper.p1), hi)
    return pya.Box(lo, across(lower.p1), hi, across(upper.p1))


def next_port_layer(layout, cell, datatype=0, stackup=None):
    """Lowest port layer (201..299, without the stackup's own layers, see export.port_layer_numbers) with no shapes
    in cell, or None if all are used."""
    used = set()
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer in PORT_LAYERS and info.datatype == datatype and not cell.bbox_per_layer(li).empty():
            used.add(info.layer)
    return next((layer for layer in port_layer_numbers(stackup) if layer not in used), None)
