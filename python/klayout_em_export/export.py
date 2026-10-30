"""Export part of a layout as one flat cell with only the layers the EM model reads."""
import pya

PORT_LAYERS = range(201, 300)   # gds2palace port polygons, layer numbers 201..299


class ExportResult:
    def __init__(self, gds_path, cellname, box):
        self.gds_path = gds_path
        self.cellname = cellname
        self.box = box              # DBox in um, or None for the whole cell
        self.kept = {}              # (layer, datatype) -> polygon count in the output
        self.dropped = {}           # (layer, datatype) -> shape count left out (not in the stackup, or other purpose)

    def report(self):
        lines = [f"wrote {self.gds_path} (cell {self.cellname})",
                 "region: " + (f"{self.box}" if self.box else "whole cell")]
        lines.append("kept:    " + ", ".join(f"{l}/{d} ({n})" for (l, d), n in sorted(self.kept.items())))
        if self.dropped:
            lines.append("dropped: " + ", ".join(f"{l}/{d} ({n})" for (l, d), n in sorted(self.dropped.items())))
        return "\n".join(lines)


def marker_box(layout, cell, marker):
    """Bounding box (DBox, um) of the shapes on the marker layer (layer, datatype) in cell, or None."""
    li = layout.find_layer(*marker)
    if li is None:
        return None
    region = pya.Region(cell.begin_shapes_rec(li))
    return None if region.is_empty() else region.bbox().to_dtype(layout.dbu)


def _copy_port_shape(layout, shape, trans, target, target_layout):
    """Copy a port shape unchanged: a via port is a zero-width line, which a Region would drop. User properties
    (the port settings) are copied too; inserting into another layout does not carry them."""
    new = target.insert(shape, trans)
    if shape.prop_id:
        new.prop_id = target_layout.properties_id(layout.properties(shape.prop_id))


def _copy_port_shapes(layout, cell, li, box, target, target_layout):
    it = cell.begin_shapes_rec(li) if box is None else cell.begin_shapes_rec_touching(li, box)
    count = 0
    while not it.at_end():
        if not it.shape().is_text():
            _copy_port_shape(layout, it.shape(), it.trans(), target, target_layout)
            count += 1
        it.next()
    return count


def _is_kept(key, keep, purposes):
    layer, datatype = key
    return (layer in keep or layer in PORT_LAYERS) and datatype in purposes


def export_flat(layout, cell, stackup, gds_path, box=None, purposes=(0,), cellname=None, selection=None,
                port_layers=None, remove=None):
    """Write cell, flattened and clipped to box (DBox in um, None = whole cell), to gds_path. With a selection
    (selection.Selection), only its shapes are written, uncut, and box is ignored.

    Kept: the stackup's GDS layers (derived layers by their sources) and the port layers 201..299, only for the
    given purposes (datatypes). Everything else is reported in result.dropped. Metal is merged per layer and cut
    at the box edge; port shapes are copied unchanged if they touch the box. port_layers {layout port layer:
    exported layer} renumbers the ports (ports.export_numbering). remove {GDS layer: Region} is cut out of those
    layers (the replaced devices' own shapes below Metal1, devices.device_shapes).
    """
    port_layers = port_layers or {}
    remove = remove or {}
    keep = set(stackup.gds_layers())
    clip = None if box is None or selection is not None else box.to_itype(layout.dbu)
    result = ExportResult(gds_path, cellname or cell.name, None if selection is not None else box)

    em = pya.Layout()
    em.dbu = layout.dbu
    top = em.create_cell(result.cellname)
    if selection is not None:
        for key, region in selection.regions.items():
            if not _is_kept(key, keep, purposes):
                result.dropped[key] = region.count()
                continue
            merged = ((region - remove[key[0]]) if key[0] in remove else region).merged()
            top.shapes(em.layer(*key)).insert(merged)
            result.kept[key] = merged.count()
        for key, shape, trans in selection.ports:
            if not _is_kept(key, keep, purposes):
                result.dropped[key] = result.dropped.get(key, 0) + 1
                continue
            out = (port_layers.get(key[0], key[0]), key[1])
            _copy_port_shape(layout, shape, trans, top.shapes(em.layer(*out)), em)
            result.kept[out] = result.kept.get(out, 0) + 1
        em.write(gds_path)
        return result
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        key = (info.layer, info.datatype)
        is_port = info.layer in PORT_LAYERS
        if not _is_kept(key, keep, purposes):
            it = cell.begin_shapes_rec(li) if clip is None else cell.begin_shapes_rec_touching(li, clip)
            count = sum(1 for _ in it.each())
            if count:
                result.dropped[key] = count
            continue
        if is_port:
            key = (port_layers.get(info.layer, info.layer), info.datatype)
        target = em.layer(*key)
        if is_port:
            count = _copy_port_shapes(layout, cell, li, clip, top.shapes(target), em)
        else:
            region = pya.Region(cell.begin_shapes_rec(li) if clip is None else cell.begin_shapes_rec_touching(li, clip))
            if clip is not None:
                region &= pya.Region(clip)
            if info.layer in remove:
                region -= remove[info.layer]
            region.merge()
            top.shapes(target).insert(region)
            count = region.count()
        if count:
            result.kept[key] = count
    em.write(gds_path)
    return result
