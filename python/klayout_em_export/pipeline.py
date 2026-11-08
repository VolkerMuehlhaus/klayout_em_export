"""The workflow without the GUI: the export, its checks and the panel's state, as data. pya and the standard library
only, so gui.py, the batch tests and the headless CLI (cli.py) share one implementation.

Nothing here reads or writes the settings file (~/.klayout_em_export.json) or the layout's meta info: the caller
passes the stackup, the ground marks (seeds) and the technology."""
import json
import os

from .connectivity import check_ground, port_nets
from .devices import device_shapes, find_devices, mark_replaced, orphaned_tags, unconnected_terminals
from .boundary import port_wall_sides
from .export import export_flat
from .ports import (check_ports, collect_ports, export_directions, export_numbering, export_port_numbers,
                    is_complete, port_map, ports_of, simcfg_ports)
from .simcfg import em_export_purposes, write_simcfg

EM_REGION = (800, 0)      # marker layer: a box on it keeps the export region in the layout
# persisted layout meta info, saved with the layout (gui.py also mirrors it into the settings file)
META_STACKUP = "klayout_em_export.stackup"
META_OUTPUT = "klayout_em_export.output"
META_GROUND = "klayout_em_export.ground"    # JSON [[GDS layer, x, y], ...] in dbu: points in marked ground shapes


class NoUndo:
    """Stand-in for a LayoutView where none is (batch, CLI): devices.replace/unreplace and boundary.create_ports
    only need transaction, commit and add_missing_layers. A standalone LayoutView crashes on transaction in batch."""

    def transaction(self, text):
        pass

    def commit(self):
        pass

    def add_missing_layers(self):
        pass


def _clip(layout, box):
    """box (DBox in µm, or None) in dbu."""
    return None if box is None else box.to_itype(layout.dbu)


def layout_devices(layout, cell, stackup, technology):
    """(devices, unknown) of cell for the technology module, with the replaced ones marked."""
    devices, unknown = find_devices(layout, cell, stackup, technology)
    return mark_replaced(layout, cell, devices), unknown


def region_ports(layout, cell, stackup, box=None, selection=None):
    """{layer: Port} of the export region: the ports of a completed selection, else those inside box (DBox, µm), else
    all of cell."""
    if selection is not None:
        return ports_of(layout, cell, selection.ports, stackup=stackup)
    return collect_ports(layout, cell, _clip(layout, box), stackup=stackup)


def export_checks(layout, cell, stackup, ports, devices, seeds=(), box=None):
    """What the export dialog reports before the export, as data:
    problems: port problems, shorts, unconnected device terminals, orphaned device ports (texts);
    left_out: layout port numbers without complete settings (exported as shapes, not in the .simcfg);
    renumbered: [(exported number, layout number)] if the export renumbers, else [];
    numbering_error: why the export is not possible (too many ports), else None."""
    problems = check_ports(ports, stackup)
    check = check_ground(layout, cell, stackup, _clip(layout, box), seeds, ports)
    problems += [f"port {n}: both ends are on the same net (short circuit)" for n in check.shorted]
    problems += [f"{t} of {d.pcell} {d.id.split('@')[0]} is not connected to any wiring"
                 for d, t in unconnected_terminals(layout, devices, check)]
    problems += [f"ports of {i.split('@')[0]}: that device is no longer there (moved or deleted); Undo Replace, "
                 "then Replace All" for i in sorted(orphaned_tags(layout, cell, devices))]
    result = {"problems": problems, "left_out": [ports[layer].number for layer in sorted(ports)
                                                 if not is_complete(ports[layer])],
              "renumbered": [], "numbering_error": None}
    try:
        numbering = export_numbering(ports, stackup)
    except ValueError as e:
        result["numbering_error"] = str(e)
    else:
        numbers = export_port_numbers(numbering)
        pairs = sorted((numbers[old], ports[old].number) for old in numbering)
        if any(new != old for new, old in pairs):
            result["renumbered"] = pairs
    return result


def export_em(layout, cell, stackup, gds_path, technology, box=None, selection=None, seeds=(), layout_file=None):
    """Export the region (selection: a completed selection.Selection, else box, a DBox in µm, else the whole cell)
    to gds_path, with <name>.simcfg and <name>_portmap.json next to it. technology: the tech module (its NAME goes
    into the port map, Create Circuit reads it). Returns a dict: gds, simcfg, portmap, cellname, ports (in the
    region), simcfg_ports (complete ones, in the .simcfg), kept_settings (setupEM's own settings kept),
    port_list (the .simcfg ports), purposes (the datatypes kept, em_export_purposes: the previous .simcfg's and those of
    the user's own setup files for layout_file), report (what export_flat kept and dropped).
    Raises ValueError if the ports can't be numbered (export_numbering)."""
    ports = region_ports(layout, cell, stackup, box, selection)
    numbering = export_numbering(ports, stackup)     # ports 1..N without gaps, see export_numbering
    devices = layout_devices(layout, cell, stackup, technology)[0]
    remove = device_shapes(layout, devices, stackup)    # replaced devices: their shapes below the pins
    base = os.path.splitext(gds_path)[0]
    purposes = em_export_purposes(base + ".simcfg", layout_file)[0]
    if selection is not None:
        result = export_flat(layout, cell, stackup, gds_path, selection=selection, purposes=purposes,
                             port_layers=numbering, remove=remove)
    else:
        result = export_flat(layout, cell, stackup, gds_path, box=box, purposes=purposes, port_layers=numbering,
                             remove=remove)
    nets = port_nets(ports, check_ground(layout, cell, stackup, _clip(layout, box), seeds, ports))
    directions = export_directions(ports, nets, stackup)    # every via port: signal metal on the same end
    port_list = simcfg_ports(ports, numbering, directions)
    # in-plane ports on the region's edge: those sides are port walls (ports made with Create Proposed Ports as
    # port walls, or drawn by hand there)
    region = (selection.bbox() if selection is not None else box.to_itype(layout.dbu) if box is not None
              else cell.bbox())
    walls = port_wall_sides(ports, region)
    kept = write_simcfg(base + ".simcfg", gds_path, stackup.path, result.cellname, ports=port_list, purpose=purposes,
                        port_walls=walls)
    with open(base + "_portmap.json", "w") as f:
        json.dump(port_map(ports, numbering, devices, nets, directions, technology.NAME), f, indent=2)
    return {"gds": gds_path, "simcfg": base + ".simcfg", "portmap": base + "_portmap.json",
            "cellname": result.cellname, "ports": len(ports), "simcfg_ports": len(port_list),
            "kept_settings": kept, "port_list": port_list, "purposes": list(purposes), "report": result.report(),
            "port_walls": walls}
