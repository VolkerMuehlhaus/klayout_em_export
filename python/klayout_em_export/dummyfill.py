"""Dummy metal fill removed from the layout (EM > Remove Dummy Fill), once, in one undo step: it clutters the view and,
on the drawing datatype, adds floating metal to the EM model.

Process independent: the fill is told by what it is, not by datatype or cell names. A shape is dummy fill when
- it is on a conductor or sheet layer of the stackup (any datatype). Never on a via layer of the stackup (any
  datatype): vias and via arrays are repeated, isolated shapes too, and are never removed;
- it floats: merged over the hierarchy with the drawn metal of its layer (datatype 0, the geometry the stackup and
  the export use) and the other shapes of its own datatype, its polygon touches no via of the stackup's via layers
  above or below that metal, no text, no port shape, and no device or PDK cell. Other datatypes are left out of
  this merge: markers (IHP's no-fill area 23, ...) are no metal, and fill tiles abut them. Drawn metal (datatype 0)
  is EM model geometry, so it is judged more carefully: a drawn polygon touching a shape of any other datatype
  (a marker, a pin) stays;
- it repeats: every drawn shape of that floating polygon has a bounding-box size found at least MINCOUNT times
  among the shapes of the floating polygons (judged per drawn shape, as abutting fill tiles merge into large
  blocks; a floating shield or test structure with one shape of its own size stays).
Shapes are deleted where they are, in the cell and in its plain subcells placed nowhere else (density.plain_cells),
where every placement of a shape is fill; cells left empty (fill cells) are deleted with their placements. Shapes
with properties (the plug-in's REF patches and ports) are never deleted.
"""
import pya

from .density import plain_cells
from .export import PORT_LAYERS

MINCOUNT = 20


def _flat(layout, cell, layer_numbers, merged=True):
    """A copy of all shapes of the given layer numbers (all datatypes) in cell and its subcells, merged, or (merged
    False) one polygon per shape."""
    region = pya.Region()
    region.merged_semantics = merged
    for li in layout.layer_indexes():
        if layout.get_info(li).layer in layer_numbers:
            region.insert(cell.begin_shapes_rec(li))
    return region.merged() if merged else region


def _flat_datatypes(layout, cell, layer, datatypes, merged=True):
    """As _flat, for one layer number and the given datatypes only."""
    region = pya.Region()
    region.merged_semantics = merged
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer == layer and info.datatype in datatypes:
            region.insert(cell.begin_shapes_rec(li))
    return region.merged() if merged else region


def _texts(layout, cell, layer):
    """Small boxes at the texts on a layer number (all datatypes): a labelled shape is no fill."""
    region = pya.Region()
    for li in layout.layer_indexes():
        if layout.get_info(li).layer != layer:
            continue
        it = cell.begin_shapes_rec(li)
        while not it.at_end():
            if it.shape().is_text():
                p = it.trans() * it.shape().text.trans.disp
                region.insert(pya.Box(p.x - 1, p.y - 1, p.x + 1, p.y + 1))
            it.next()
    return region


def _blocked(layout, cell, stackup):
    """Region where nothing is fill: the bounding boxes of devices and PDK cells, and the port shapes."""
    from .tech import for_layout
    tech = for_layout(layout)[0]
    ctx = tech.context(layout, stackup)
    region = pya.Region()
    blocking = {}                   # cell index -> device or PDK cell (decided once per cell, not per placement)
    it = cell.begin_instances_rec()
    while not it.at_end():
        c = it.inst_cell()
        if c.cell_index() not in blocking:
            name = tech.identify(c, ctx)[0]
            blocking[c.cell_index()] = c.is_proxy() or bool(name and tech.is_device(name))
        if blocking[c.cell_index()]:
            region.insert(c.bbox().transformed(it.trans() * it.inst_trans()))
        it.next()
    for li in layout.layer_indexes():
        if layout.get_info(li).layer in PORT_LAYERS:
            # grown by 1 dbu: a via port is a zero-width line, which a Region drops
            it = cell.begin_shapes_rec(li)
            while not it.at_end():
                region.insert(it.shape().bbox().transformed(it.trans()).enlarged(1, 1))
                it.next()
    return region


def fill_layers(stackup):
    """Layer numbers searched for fill: the stackup's conductors and sheets, without vias and derived layers."""
    vias = {l.layer for l in stackup.layers if l.kind == "via"}
    return sorted({l.layer for l in stackup.layers if l.is_metal and l.layer not in stackup.derived} - vias
                  - set(PORT_LAYERS))


def find_fill(layout, cell, stackup, mincount=MINCOUNT):
    """{(layer, datatype): Region of the dummy fill polygons (merged)} in cell and its subcells. Each datatype is
    judged with the drawn metal (datatype 0) of its layer, not with the other datatypes (markers); drawn metal alone,
    and kept where it touches a shape of another datatype."""
    neighbors = stackup.via_neighbors()             # {via layer: (metals below, metals above)}
    blocked = _blocked(layout, cell, stackup)
    out = {}
    for layer in fill_layers(stackup):
        datatypes = sorted({layout.get_info(li).datatype for li in layout.layer_indexes()
                            if layout.get_info(li).layer == layer})
        if not datatypes:
            continue
        vias = [v for v, (below, above) in neighbors.items() if layer in [l.layer for l in below + above]]
        contact = _flat(layout, cell, set(vias)) if vias else pya.Region()
        texts = _texts(layout, cell, layer)
        for datatype in datatypes:
            # fill on other datatypes: with the drawn metal only, not with the markers. Drawn metal (datatype 0) is EM
            # model geometry, so be careful: a drawn polygon touching a shape of any other datatype stays
            with_drawn = {0} if datatype == 0 else {0, datatype}
            metal = _flat_datatypes(layout, cell, layer, with_drawn)
            if metal.is_empty():
                continue
            floating = metal.not_interacting(contact & metal.sized(1)) if not contact.is_empty() else metal
            floating = floating.not_interacting(texts).not_interacting(blocked)
            if datatype == 0 and len(datatypes) > 1 and not floating.is_empty():
                others = _flat_datatypes(layout, cell, layer, set(datatypes) - {0}, merged=False)
                floating = floating.not_interacting(others & floating.sized(1))
            if floating.is_empty():
                continue
            # repeated: judged on the drawn shapes, not the merged ones (abutting fill tiles merge into large
            # blocks). A floating block is fill only if every shape in it has a size found mincount times or more
            shapes = _flat_datatypes(layout, cell, layer, with_drawn, merged=False).interacting(floating)
            sizes = {}
            for polygon in shapes.each():
                box = polygon.bbox()
                sizes[(box.width(), box.height())] = sizes.get((box.width(), box.height()), 0) + 1
            rare = pya.Region()
            for polygon in shapes.each():
                box = polygon.bbox()
                if sizes[(box.width(), box.height())] < mincount:
                    rare.insert(polygon)
            fill = floating.not_interacting(rare) if not rare.is_empty() else floating
            if not fill.is_empty():
                out[(layer, datatype)] = fill
    return out


def _fill_cell_shapes(layout, c, fill):
    """[(layer, datatype, Polygon)] of a cell that holds only fill candidates (shapes on fill layers, no properties,
    no texts, no subcells), else None."""
    if c.child_cells():
        return None
    out = []
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        for shape in c.shapes(li).each():
            if (info.layer, info.datatype) not in fill or shape.prop_id != 0 or shape.is_text() or not (
                    shape.is_box() or shape.is_polygon() or shape.is_path() or shape.is_simple_polygon()):
                return None
            out.append((info.layer, info.datatype, shape.polygon))
    return out or None


def _remove_fill_placements(layout, cell, owners, fill):
    """Delete the placements in cell of fill cells (cells of fill candidates only, e.g. a fill tool's tile cells)
    whose placed shapes are all fill: a tile cell is often placed thousands of times, a few of them touching a via
    or a label, so its shape cannot go but most placements can. Arrays are split into single placements first.
    Returns {(layer, datatype): shapes deleted}."""
    removed = {}
    for ci in list(owners):
        c = layout.cell(ci)
        shapes = _fill_cell_shapes(layout, c, fill)
        if shapes is None:
            continue
        instances = [inst for inst in cell.each_inst() if inst.cell_index == ci]
        if not instances:
            continue
        for inst in instances:
            if inst.is_regular_array():
                inst.explode()
        instances = [inst for inst in cell.each_inst() if inst.cell_index == ci]
        placed = {}                 # (layer, datatype) -> Region of all placed shapes (one polygon each)
        keys = []                   # per instance: [key of its placed polygon]
        for inst in instances:
            mine = []
            for layer, datatype, polygon in shapes:
                if (layer, datatype) not in placed:
                    placed[(layer, datatype)] = pya.Region()
                    placed[(layer, datatype)].merged_semantics = False
                moved = polygon.transformed(inst.cplx_trans)
                placed[(layer, datatype)].insert(moved)
                mine.append(str(moved))
            keys.append(mine)
        hits = {}
        for key, region in placed.items():
            for polygon in region.interacting(fill[key]).each():
                hits[str(polygon)] = hits.get(str(polygon), 0) + 1
        doomed = []
        for inst, mine in zip(instances, keys):
            if all(hits.get(k, 0) > 0 for k in mine):
                for k in mine:
                    hits[k] -= 1
                doomed.append(inst)
        for inst in doomed:
            inst.delete()
        for layer, datatype, _ in shapes:
            removed[(layer, datatype)] = removed.get((layer, datatype), 0) + len(doomed)
    return removed


def remove_dummy_fill(layout, cell, stackup):
    """Delete the dummy fill (find_fill) in cell and its plain subcells placed only under cell. Returns ({(layer,
    datatype): shapes deleted, counted per placement}, cells deleted). Run it inside an undo transaction."""
    fill = find_fill(layout, cell, stackup)
    owners = dict(plain_cells(layout, cell, stackup))
    may_go = set(owners)            # cells that may be deleted once empty (a tile cell loses all its placements)
    removed = _remove_fill_placements(layout, cell, owners, fill)
    owners = {ci: p for ci, p in plain_cells(layout, cell, stackup).items() if ci in owners}  # placements left
    owners[cell.cell_index()] = [pya.ICplxTrans()]
    for ci, placements in owners.items():
        c = layout.cell(ci)
        for li in layout.layer_indexes():
            info = layout.get_info(li)
            if (info.layer, info.datatype) not in fill or c.shapes(li).is_empty():
                continue
            # all placements of all candidate shapes in one region (not merged: one polygon each), tested at once;
            # a shape is fill if every one of its placements is
            candidates, placed = [], pya.Region()
            placed.merged_semantics = False
            for shape in c.shapes(li).each():
                if shape.prop_id != 0 or shape.is_text() or not (shape.is_box() or shape.is_polygon() or
                                                                   shape.is_path() or shape.is_simple_polygon()):
                    continue
                copies = [str(shape.polygon.transformed(trans)) for trans in placements]
                candidates.append((shape, copies))
                for trans in placements:
                    placed.insert(shape.polygon.transformed(trans))
            if not candidates:
                continue
            hit = {}
            for polygon in placed.interacting(fill[(info.layer, info.datatype)]).each():
                hit[str(polygon)] = hit.get(str(polygon), 0) + 1
            doomed = []
            for shape, copies in candidates:
                if all(hit.get(k, 0) > 0 for k in copies):
                    for k in copies:
                        hit[k] -= 1
                    doomed.append(shape)
            for shape in doomed:
                c.shapes(li).erase(shape)
            if doomed:
                key = (info.layer, info.datatype)
                removed[key] = removed.get(key, 0) + len(doomed) * len(placements)
    # cells left empty or unplaced: deleted with their placements, until none is left
    deleted, found = 0, True
    while found:
        found = False
        for ci in sorted(may_go):
            # empty, or no longer placed (all placements were fill): it would show up as a new top cell
            if layout.is_valid_cell_index(ci) and (layout.cell(ci).is_empty() or layout.cell(ci).is_top()):
                layout.delete_cell(ci)
                may_go.discard(ci)
                deleted += 1
                found = True
    return removed, deleted
