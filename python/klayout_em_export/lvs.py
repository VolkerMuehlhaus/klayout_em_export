"""Schematic instance names of the heat sources, from the LVS database (.lvsdb) of a KLayout LVS run.

The designer's circuit simulation gives the power per schematic instance; the thermal map needs it per heat source.
LVS links the two: its layout netlist has each device with its position, its cross-reference the schematic device
it matched. A layout device belongs to the heat source whose device box contains its position and whose LVS device
class fits (technology.lvs_classes): a substrate tap or a capacitor inside a transistor's box does not count.

KLayout's SPICE reader drops the element letter of a name and LVS works in upper case: Q1 is "1", Xcore.Q1 is
"CORE.1" in the database (lvs_name). The instance name is rebuilt from it: X for each subcircuit, the device's
element letter (technology.lvs_element) for the device, "XCORE.Q1". Powers can be given by either name.
"""
import os

import pya


class LvsDevice:
    def __init__(self, position, device_class, lvs_name, element):
        self.position = position            # DPoint in µm of the exported cell
        self.device_class = device_class    # layout device class, lower case (e.g. npn13g2, sg13_lv_nmos)
        self.lvs_name = lvs_name            # schematic name as in the database, with its subcircuit path: CORE.1
        self.element = element              # schematic class name (NPN13G2), for the element letter


def instance_name(lvs_name, letter):
    """The schematic name as written in the netlist, from the database's: X for each subcircuit, letter for the
    device. CORE.1 with Q -> XCORE.Q1."""
    parts = lvs_name.split(".")
    return ".".join(["X" + p for p in parts[:-1]] + [letter + parts[-1]])


def _paths_to(layout, top, cell):
    """ICplxTrans of every placement of cell in top (identity if cell is top), in dbu."""
    if top.cell_index() == cell.cell_index():
        return [pya.ICplxTrans()]
    callers = set(cell.caller_cells())
    found = []

    def walk(c, trans):
        for inst in c.each_inst():
            ci = inst.cell_index
            if ci != cell.cell_index() and ci not in callers:
                continue
            for t in inst.cell_inst.each_cplx_trans():
                if ci == cell.cell_index():
                    found.append(trans * t)
                else:
                    walk(layout.cell(ci), trans * t)
            if len(found) > 1:
                return

    walk(top, pya.ICplxTrans())
    return found


def read_lvs_devices(path, layout, cell):
    """The layout devices of the LVS database at path that matched a schematic device, with positions in the exported
    cell. Returns (devices, notes). Raises ValueError if the database is unusable for this layout."""
    lvs = pya.LayoutVsSchematic()
    try:
        lvs.read(path)
    except RuntimeError as e:
        raise ValueError(f"{os.path.basename(path)} is not a readable LVS database: {e}")
    netlist, xref = lvs.netlist(), lvs.xref()
    if netlist is None or xref is None or lvs.reference is None:
        raise ValueError(f"{os.path.basename(path)} has no comparison with a schematic (an extraction-only run?)")
    tops = list(netlist.each_circuit_top_down())
    if not tops:
        raise ValueError(f"{os.path.basename(path)} has no layout netlist")
    top = tops[0]
    top_cell = layout.cell(top.name)
    if top_cell is None:
        raise ValueError(f"LVS was run on the cell {top.name}, which is not in this layout")
    placements = _paths_to(layout, top_cell, cell)
    if not placements:
        raise ValueError(f"LVS was run on the cell {top.name}, which does not contain {cell.name}")
    if len(placements) > 1:
        raise ValueError(f"{cell.name} is placed more than once in {top.name}, the cell LVS was run on: the names "
                         f"are not unique. Run LVS on {cell.name} itself")
    to_cell = placements[0].to_itrans(layout.dbu).inverted()     # µm of the LVS top cell -> µm of the exported cell

    notes = []
    if xref.circuit_count() and not all(cp.status() == pya.NetlistCrossReference.Match
                                        for cp in xref.each_circuit_pair()):
        notes.append("LVS did not match: only devices that LVS paired with a schematic device get a name")
    devices = []

    def walk(circuit, trans, path):
        for d in circuit.each_device():
            other = xref.other_device_for(d)
            if other is None:
                continue
            name = ".".join(path + [other.expanded_name()])
            devices.append(LvsDevice(to_cell * (trans * d.trans) * pya.DPoint(), d.device_class().name.lower(),
                                     name, other.device_class().name))
        for sc in circuit.each_subcircuit():
            other = xref.other_subcircuit_for(sc)
            if other is not None and sc.circuit_ref() is not None:
                walk(sc.circuit_ref(), trans * sc.trans, path + [other.expanded_name()])

    walk(top, pya.DCplxTrans(), [])
    return devices, notes


def assign_names(sources, lvs_devices, technology, dbu):
    """Match lvs_devices to the heat sources (thermal.HeatSource). Returns ({device id: (instance, lvs_name)},
    report): report has 'unnamed' (device ids without an LVS device), 'conflicts' (device ids with LVS devices of
    different names) and 'outside' (LVS devices of a heat source class that lie in no heat source's device box)."""
    found = {}
    outside = 0
    for lvs_device in lvs_devices:
        p = pya.DPoint(lvs_device.position.x / dbu, lvs_device.position.y / dbu)
        candidates = [s for s in sources if s.device.bbox.contains(pya.Point(round(p.x), round(p.y))) and
                      lvs_device.device_class in technology.lvs_classes(s.device)]
        if not candidates:
            if any(lvs_device.device_class in technology.lvs_classes(s.device) for s in sources):
                outside += 1
            continue
        source = min(candidates, key=lambda s: s.device.bbox.area())    # nested boxes: the innermost device
        found.setdefault(source.device.id, set()).add(lvs_device.lvs_name)
    names, conflicts = {}, []
    for s in sources:
        lvs_names = found.get(s.device.id)
        if not lvs_names:
            continue
        if len(lvs_names) > 1:
            conflicts.append(s.device.id + ": " + ", ".join(sorted(lvs_names)))
            continue
        lvs_name = lvs_names.pop()
        names[s.device.id] = (instance_name(lvs_name, technology.lvs_element(s.device)), lvs_name)
    unnamed = [s.device.id for s in sources if s.device.id not in names and
               not any(c.startswith(s.device.id + ":") for c in conflicts)]
    return names, {"unnamed": unnamed, "conflicts": conflicts, "outside": outside}
