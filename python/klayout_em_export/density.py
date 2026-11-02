"""Density holes: the repeated openings that metal density rules put into wide metal (cheesing), filled in the
layout on request (EM > Fill Density Holes in Ground Planes), once, before ports and export.

To the EM fields, a ground plane with a thousand small slots is a solid plane, but every slot is a hole with its own
edges: slow to mesh and slow to trace. The fill is added, not cut: one shape per hole, in the cell itself, on the
metal layer, tagged with GDS property FILL_KEY; nothing else in the layout changes (hierarchy, subcells, other
layers). The fill breaks the density rules, so it comes out again before tape-out (EM > Remove Density Hole Fill).

The rule is that of gds_prepare_for_EM (gds_simplify_for_em.ground_plane_holes, with shapely there), here with
KLayout's regions; keep both in sync:

- per metal layer, merged over the hierarchy: holes drawn inside tiles and gaps left between side-by-side tiles
  become alike;
- a merged shape is a ground plane if its outline (holes filled) covers at least GROUND_AREA_FRACTION of the cell
  and at least GROUND_FILL of its own bounding box (solid, not a network of lines);
- the holes of the ground planes are grouped by bounding-box size: a size with at least MINCOUNT holes is cheesing
  and is filled; holes of the other sizes belong to the circuit and stay, as do holes in shapes that are no ground
  plane.
"""
import pya

from .connectivity import wiring

GROUND_AREA_FRACTION = 0.10
GROUND_FILL = 0.60
MINCOUNT = 20
FILL_KEY = 203                      # GDS property on the fill shapes
FILL_VALUE = "density_fill"


class Holes:
    def __init__(self):
        self.planes = 0             # ground planes found
        self.fill = []              # the holes to fill (cheesing), Polygons
        self.kept = 0               # holes in ground planes kept (sizes found fewer than MINCOUNT times)


def density_holes(region, area, mincount=MINCOUNT):
    """Holes of region (merged here) that are density holes, measured against area (of the cell, dbu^2)."""
    found = Holes()
    by_size = {}                    # (width, height) -> [hole Polygon]
    for polygon in region.merged().each():
        if not polygon.holes():
            continue
        outline = pya.Polygon(list(polygon.each_point_hull()))
        if outline.area() < GROUND_AREA_FRACTION * area or outline.area() < GROUND_FILL * outline.bbox().area():
            continue
        found.planes += 1
        for i in range(polygon.holes()):
            hole = pya.Polygon(list(polygon.each_point_hole(i)))
            box = hole.bbox()
            by_size.setdefault((box.width(), box.height()), []).append(hole)
    for holes in by_size.values():
        if len(holes) >= mincount:
            found.fill += holes
        else:
            found.kept += len(holes)
    return found


def fill_density_holes(layout, cell, stackup):
    """Add a fill shape (tagged FILL_KEY) for each density hole of the traced metals (connectivity.wiring) in cell.
    Returns {metal name: Holes}. Run it inside an undo transaction."""
    area = cell.bbox().area()
    prop = layout.properties_id([[FILL_KEY, FILL_VALUE]])   # set at insertion, not by set_property afterwards
    out = {}
    for layer, name in wiring(stackup)[0].items():
        li = layout.find_layer(layer, 0)
        if li is None:
            continue
        found = density_holes(pya.Region(cell.begin_shapes_rec(li)), area)
        shapes = cell.shapes(li)
        for hole in found.fill:
            shapes.insert(hole, prop)
        out[name] = found
    return out


def remove_density_fill(layout, cell):
    """Delete the fill shapes (FILL_KEY) that fill_density_holes added to cell. Returns their number."""
    prop = layout.properties_id([[FILL_KEY, FILL_VALUE]])   # the same id as at insertion, in this layout
    removed = 0
    for li in layout.layer_indexes():
        shapes = cell.shapes(li)
        fill = [s for s in shapes.each() if s.prop_id == prop]
        for s in fill:
            shapes.erase(s)
        removed += len(fill)
    return removed
