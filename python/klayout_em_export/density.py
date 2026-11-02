"""Density holes filled and metal merged, in the layout (EM > Fill Density Holes and Merge Metal), once, before ports
and export: fewer edges to mesh and fewer polygons for the checks.

Density rules put many small openings into wide metal (cheesing). To the EM fields such metal is solid, but every
opening is a hole with its own edges. Per metal layer of the stackup (conductors and sheets; not the vias, which
gds2palace corrects as arrays, nor derived layers), merged over the whole hierarchy, the holes of all shapes are
grouped by bounding-box size: a size found at least MINCOUNT times is cheesing and is filled, holes of other sizes
belong to the circuit and stay. This is gds_prepare_for_EM's rule (gds_simplify_for_em.ground_plane_holes) without
its ground-plane test: any shape counts. Keep the hole grouping of both in sync.

Then the layer's shapes in the cell itself are replaced by their merge with the fill, so the cell has fewer polygons,
not more. The metal of repeated plain subcells (via stacks, MIM capacitors placed several times; plain_cells) is
moved into the cell and merged too: their pads overlap the lines they connect. So is the metal of a plain subcell
placed once where it holds filled holes (a cheesed ground plane in a cell of its own), so the fill merges with it. Their vias, texts and other layers
stay in the subcell (gds2palace sees the via arrays). Other subcells stay as they are: devices (recognition needs
them), PDK pcells, cells placed once (seal ring) and cells also placed outside the cell. Shapes with properties (REF
patches of replaced devices) and texts are kept as they are. One undo step (Edit > Undo); once the layout is saved
and closed, the change stays: such a layout must not go to tape-out, the fill breaks the density rules.
"""
import pya

MINCOUNT = 20


class Result:
    def __init__(self):
        self.filled = 0             # holes filled
        self.kept = 0               # holes of sizes found fewer than MINCOUNT times
        self.before = 0             # polygons of the layer in the cell with its subcells (what is meshed), before
        self.after = 0              # and after


def density_holes(region, mincount=MINCOUNT):
    """(holes to fill [Polygon], number of holes kept): the holes of region (merged here) whose bounding-box size is
    found at least mincount times."""
    by_size = {}                    # (width, height) -> [hole Polygon]
    for polygon in region.merged().each():
        for i in range(polygon.holes()):
            hole = pya.Polygon(list(polygon.each_point_hole(i)))
            box = hole.bbox()
            by_size.setdefault((box.width(), box.height()), []).append(hole)
    fill, kept = [], 0
    for holes in by_size.values():
        if len(holes) >= mincount:
            fill += holes
        else:
            kept += len(holes)
    return fill, kept


def merged_layers(stackup):
    """GDS layers that are filled and merged: the stackup's conductors and sheets, without vias and derived layers."""
    return sorted({l.layer for l in stackup.layers if l.is_metal and l.layer not in stackup.derived})


def _geometry(shape):
    """A copy of a kept shape's geometry, valid after the layer's shapes are cleared."""
    for test, get in ((shape.is_text, "text"), (shape.is_box, "box"), (shape.is_path, "path"),
                      (shape.is_simple_polygon, "simple_polygon"), (shape.is_polygon, "polygon"),
                      (shape.is_edge, "edge")):
        if test():
            return getattr(shape, get).dup()
    return None


def _split(shapes):
    """(Region of the plain polygons, boxes and paths of shapes; [(geometry, prop_id)] of the others: texts, shapes
    with properties, edges), from one layer of one cell."""
    plain, keep = pya.Region(), []
    for shape in shapes.each():
        if shape.prop_id == 0 and not shape.is_text() and (shape.is_box() or shape.is_path() or shape.is_polygon()
                                                            or shape.is_simple_polygon()):
            plain.insert(shape.polygon)
        else:
            keep.append((_geometry(shape), shape.prop_id))
    return plain, keep


def _replace(shapes, region, keep):
    """Set one layer of one cell to region plus the kept shapes."""
    shapes.clear()
    shapes.insert(region)
    for geometry, prop_id in keep:
        if geometry is not None:
            shapes.insert(geometry, prop_id) if prop_id else shapes.insert(geometry)


def plain_cells(layout, cell, stackup):
    """{cell index: [ICplxTrans into cell, one per placement]} of the subcells whose metal may be merged into cell:
    no PDK cell (pcell or library proxy: KLayout regenerates those), no device (tech.identify), and placed nowhere
    else: all their parents are cell or such cells, so moving their metal changes no other cell. fill_and_merge moves
    the metal of those placed at least twice (array elements count), and of those placed once where it touches the
    fill (a cheesed plane in its own cell)."""
    from .tech import for_layout
    tech = for_layout(layout)[0]
    ctx = tech.context(layout, stackup)
    placements = {}
    it = cell.begin_instances_rec()
    while not it.at_end():
        placements.setdefault(it.inst_cell().cell_index(), []).append(it.trans() * it.inst_trans())
        it.next()
    inside = set(placements)
    owned, changed = set(), True        # cells placed only under cell
    while changed:
        changed = False
        for ci in inside - owned:
            if all(p == cell.cell_index() or p in owned for p in layout.cell(ci).each_parent_cell()):
                owned.add(ci)
                changed = True
    out = {}
    for ci in owned:
        c = layout.cell(ci)
        name = tech.identify(c, ctx)[0]
        if not c.is_proxy() and not (name and tech.is_device(name)):
            out[ci] = placements[ci]
    return out


def fill_and_merge(layout, cell, stackup):
    """Fill the density holes (found over the hierarchy), move the metal of plain subcells (plain_cells: placed at least
    twice, or once and touching the fill) into cell, and merge each metal layer of cell. Returns ({layer name: Result}
    for the layers changed, number of subcells whose metal was moved). Run it inside an undo transaction."""
    names = {l.layer: l.name for l in stackup.layers}
    plain_subcells = plain_cells(layout, cell, stackup)
    moved_cells = set()
    out = {}
    for layer in merged_layers(stackup):
        li = layout.find_layer(layer, 0)
        if li is None:
            continue
        result = Result()
        fill, result.kept = density_holes(pya.Region(cell.begin_shapes_rec(li)))
        result.filled = len(fill)
        flat_before = pya.Region(cell.begin_shapes_rec(li)).count()
        own, keep = _split(cell.shapes(li))
        moved = pya.Region()
        fill_region = pya.Region(fill)
        for ci, transformations in plain_subcells.items():
            sub = layout.cell(ci).shapes(li)
            plain, sub_keep = _split(sub)
            if plain.is_empty():
                continue
            placed = pya.Region()
            for trans in transformations:
                placed += plain.transformed(trans)
            if len(transformations) < 2 and placed.interacting(fill_region).is_empty():
                continue                # placed once, and no filled hole in its metal: stays a cell
            moved += placed
            _replace(sub, pya.Region(), sub_keep)
            moved_cells.add(ci)
        if own.is_empty() and moved.is_empty() and not fill:
            continue
        _replace(cell.shapes(li), (own + moved + fill_region).merged(), keep)
        result.before = flat_before
        result.after = pya.Region(cell.begin_shapes_rec(li)).count()
        out[names.get(layer, str(layer))] = result
    return out, len(moved_cells)
