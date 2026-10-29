"""The selected shapes (not their bounding box), flattened into the current cell, for "selected shapes only" export.

Selected instances contribute all their shapes. With a stackup, the selection is completed by the vias that
connect two selected metals, and by the port shapes that touch selected metal: both are easy to miss when
selecting, and without them the model has open circuits or no ports.
"""
import pya

from .export import PORT_LAYERS
from .locate import drawn_metals


class Selection:
    def __init__(self, layout, cell):
        self.layout, self.cell = layout, cell
        self.regions = {}           # (layer, datatype) -> Region in cell coordinates
        self.ports = []             # ((layer, datatype), shape, ICplxTrans into cell) of port shapes (201..299)
        self.added_vias = {}        # via layer -> count added by complete()
        self.added_ports = 0

    def is_empty(self):
        return not self.regions and not self.ports

    def add_shape(self, shape, li, trans):
        if shape.is_text():
            return
        info = self.layout.get_info(li)
        if info.layer in PORT_LAYERS:
            self.ports.append(((info.layer, info.datatype), shape, trans))
        else:
            region = self.regions.setdefault((info.layer, info.datatype), pya.Region())
            region.insert(shape.polygon.transformed(trans))

    def add_cell(self, cell, trans):
        """All shapes of cell (recursively), cell placed with trans."""
        for li in self.layout.layer_indexes():
            it = cell.begin_shapes_rec(li)
            while not it.at_end():
                self.add_shape(it.shape(), li, trans * it.trans())
                it.next()

    @classmethod
    def from_view(cls, view, cv):
        """The view's selection in the active cellview. For a selected instance, obj.trans() already includes
        the instance's own transformation."""
        selection = cls(cv.layout(), cv.cell)
        for obj in view.each_object_selected():
            if obj.cv_index != view.active_cellview_index:
                continue
            if obj.is_cell_inst():
                selection.add_cell(obj.inst().cell, obj.trans())
            else:
                selection.add_shape(obj.shape, obj.layer, obj.trans())
        return selection

    def bbox(self):
        box = pya.Box()
        for region in self.regions.values():
            box += region.bbox()
        for _, shape, trans in self.ports:
            box += shape.bbox().transformed(trans)
        return box

    def completed(self, stackup, datatype=0):
        """A copy with the connecting vias and the touching port shapes added."""
        out = Selection(self.layout, self.cell)
        out.regions = {key: region.dup() for key, region in self.regions.items()}
        out.ports = list(self.ports)
        metal_layers = [layer for _, layer in drawn_metals(stackup)]
        metals = [self.regions[(l, datatype)] for l in metal_layers if (l, datatype) in self.regions]
        if not metals:
            return out
        all_metal = pya.Region()
        for region in metals:
            all_metal += region
        search = all_metal.bbox()

        # vias that land on at least two selected metal layers
        for via in (l for l in stackup.layers if l.kind == "via" and l.layer not in stackup.derived):
            li = self.layout.find_layer(via.layer, datatype)
            if li is None:
                continue
            candidates = pya.Region(self.cell.begin_shapes_rec_touching(li, search))
            connecting = pya.Region()
            for i in range(len(metals)):
                for j in range(i + 1, len(metals)):
                    connecting += candidates.interacting(metals[i]).interacting(metals[j])
            connecting.merge()
            selected = out.regions.get((via.layer, datatype), pya.Region())
            new = connecting - selected
            if not new.is_empty():
                out.regions[(via.layer, datatype)] = (selected + connecting).merged()
                out.added_vias[via.layer] = new.count()

        # port shapes touching selected metal (zero-width lines: test with a box grown by 1 dbu)
        have = {(key, shape.bbox().transformed(trans).to_s()) for key, shape, trans in out.ports}
        for li in self.layout.layer_indexes():
            info = self.layout.get_info(li)
            if info.layer not in PORT_LAYERS or info.datatype != datatype:
                continue
            it = self.cell.begin_shapes_rec_touching(li, search)
            while not it.at_end():
                shape, trans = it.shape(), it.trans()
                box = shape.bbox().transformed(trans)
                key = (info.layer, info.datatype)
                if (not shape.is_text() and (key, box.to_s()) not in have
                        and not all_metal.interacting(pya.Region(box.enlarged(1, 1))).is_empty()):
                    out.ports.append((key, shape, trans))
                    have.add((key, box.to_s()))
                    out.added_ports += 1
                it.next()
        return out
