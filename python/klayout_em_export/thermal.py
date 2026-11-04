"""Thermal export: the region as a model for setupThermal / gds2palace's Elmer thermal mode.

The PDK devices stay as drawn, since their metal, contacts and vias conduct heat. Each device in the region gets one
heat source: its heat area (the technology's heat_area, for IHP the PDK's HeatTrans/HeatRes shapes) on a marker
layer of its own, in the z range of the technology's HEAT_TARGET stackup layer. One power per device: gds2palace
spreads a source's power over all its polygons by volume, so a device's fingers share it by area.

Boundaries (constant temperatures) are chosen in setupThermal, since no default fits every assembly. The export
writes the region outline on the first marker layer, as geometry a boundary can use, and a constant-temperature row on
it without a target layer: a placeholder that setupThermal lists and refuses to mesh until the target is chosen.

Writes <name>.gds, <name>.tsimcfg (setupThermal) and <name>_thermalmap.json: which device each heat source layer
belongs to, for the powers from a circuit simulation and the temperatures back. With an LVS database, each heat
source gets the name of its schematic instance (lvs.py). An export again keeps setupThermal's own settings, the
boundaries, and the power and instance name of every device that is still in the region.
"""
import json
import os

import pya

from .devices import REF_NAME
from .export import export_flat
from .lvs import assign_names, read_lvs_devices
from .pipeline import _clip, layout_devices

FIRST_LAYER = 201           # marker layers: the region outline, then one per heat source, skipping stackup layers
MAP_FORMAT = 1
MAP_NOTE = ("layer = marker layer of the heat source in the exported GDS and the .tsimcfg; device = the layout "
            "device (pcell name@x,y in dbu of its cell); instance = its name in the schematic (from LVS), if known, "
            "lvs_name = the same as in the LVS database (no element letters, upper case). "
            "area_um2 = heat area; heat_area_from: shapes (the PDK's heat shapes), rule (none drawn, e.g. an older "
            "PDK: the same rectangles from the device's layers) or bbox (the device's bounding box: a larger area, a "
            "lower peak temperature); from_pdk = not bbox. "
            "outline_layer: the region outline, for boundaries chosen in setupThermal.")


def marker_layers(stackup, count, start=FIRST_LAYER):
    """count layer numbers from start on that the stackup does not use (also not as derived or boundary layer)."""
    used = {l.layer for l in stackup.layers} | set(stackup.gds_layers()) | set(stackup.derived)
    layers, number = [], start
    while len(layers) < count:
        if number not in used:
            layers.append(number)
        number += 1
    return layers


def heat_target(stackup, technology):
    """Name of the stackup layer that holds the heat sources, or None for a technology without devices.
    Raises ValueError if the stackup lacks it or it has no thickness (a heat source is a volume)."""
    name = getattr(technology, "HEAT_TARGET", None)
    if name is None:
        return None
    layer = stackup.layer(name)
    if layer is None:
        raise ValueError(f"the stackup {os.path.basename(stackup.path)} has no layer {name}, which holds the heat "
                         "sources of the devices: choose a stackup with it")
    z = stackup.z_range(layer)
    if z is not None and z[2] <= z[1]:
        raise ValueError(f"{name} has no thickness in the stackup {os.path.basename(stackup.path)}: a heat source is "
                         "a volume and takes the thickness of its layer")
    return name


class HeatSource:
    def __init__(self, device, area, how, cut):
        self.device = device
        self.area = area            # Region in dbu of the exported cell
        self.how = how              # the technology's heat_area: 'shapes', 'rule' or 'bbox' (the device's bounding box)
        self.cut = cut              # partly outside the region: only the part inside is exported

    @property
    def from_pdk(self):
        return self.how != "bbox"


def heat_sources(layout, cell, stackup, technology, box=None):
    """The heat sources of the devices in cell whose heat area touches box (DBox in µm, None: whole cell)."""
    devices = layout_devices(layout, cell, stackup, technology)[0]
    clip = _clip(layout, box)
    sources = []
    for device in sorted(devices, key=lambda d: (d.bbox.left, d.bbox.bottom, d.pcell)):
        area, how = technology.heat_area(layout, device)
        cut = False
        if clip is not None:
            inside = area & pya.Region(clip)
            if inside.is_empty():
                continue
            cut = inside.area() < area.area()
            area = inside
        sources.append(HeatSource(device, area, how, cut))
    return sources


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _previous(base):
    """From an earlier export to the same name: ({device id: power}, {device id: (instance, lvs_name)}, LVS database
    path, settings file data)."""
    old_map = _read_json(base + "_thermalmap.json") or {}
    old_cfg = _read_json(base + ".tsimcfg")
    if not isinstance(old_cfg, dict) or old_cfg.get("application") != "setupThermal" or \
            not isinstance(old_cfg.get("saved_values"), dict):
        old_cfg = None
    power_of_layer = {t.get("source_layernum"): t.get("power") for t in (old_cfg or {}).get("thermal", [])
                      if "SOURCE" in str(t.get("type", "")).upper()}
    powers, instances = {}, {}
    for row in old_map.get("sources", []):
        if power_of_layer.get(row.get("layer")) is not None:
            powers[row["device"]] = power_of_layer[row["layer"]]
        if row.get("instance"):
            instances[row["device"]] = (row["instance"], row.get("lvs_name"))
    return powers, instances, old_map.get("lvsdb"), old_cfg


PLACEHOLDER_TEMP = 300.0     # K


def placeholder_boundary(layer):
    """The boundary row the export writes when there is none yet: the region outline at a constant temperature, with
    no target layer (the height of the fixed temperature), which only the user can choose."""
    return {"source_layernum": layer, "target_layername": "", "type": "constanttemp", "temp": PLACEHOLDER_TEMP}


def write_tsimcfg(path, gds_file, stackup_file, cellname, sources, previous_cfg=None, purpose=(0,),
                  outline_layer=None):
    """Write path: the files, the cell, the purpose and the heat sources [(layer, target, power)]; from
    previous_cfg (an earlier setupThermal file) everything else, including the boundaries. Without boundaries there,
    a placeholder boundary on outline_layer (if given): constant temperature, no target layer yet."""
    data = previous_cfg or {"application": "setupThermal", "data_format": "1.0", "saved_values": {"unit": 1e-06}}
    data["saved_values"].update({
        "purpose": list(purpose),
        "GdsFile": os.path.abspath(gds_file).replace("\\", "/"),
        "SubstrateFile": os.path.abspath(stackup_file).replace("\\", "/"),
        "cellname": cellname,
    })
    boundaries = [t for t in data.get("thermal", []) if "SOURCE" not in str(t.get("type", "")).upper()]
    if not boundaries and outline_layer is not None:
        boundaries = [placeholder_boundary(outline_layer)]
    data["thermal"] = [{"source_layernum": layer, "target_layername": target, "type": "source", "power": power}
                       for layer, target, power in sources] + boundaries
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def export_thermal(layout, cell, stackup, gds_path, technology, box=None, lvsdb=None):
    """Export the region (box, a DBox in µm, else the whole cell) to gds_path, with <name>.tsimcfg and
    <name>_thermalmap.json next to it. lvsdb: an LVS database of the layout, for the schematic instance names (lvs.py);
    without it, the names of an earlier export are kept. Returns a dict: gds, tsimcfg, thermalmap, cellname, sources
    (count), bounding_box (device ids with their bounding box as heat area), from_rule (device ids without PDK heat
    shapes, whose heat area comes from the PDK's rule), cut (device ids partly outside the region), kept_settings,
    lvs (None without lvsdb, else named (count), unnamed, conflicts, outside, notes), report.
    Raises ValueError if the stackup has no usable layer for the heat sources or lvsdb is unusable."""
    target = heat_target(stackup, technology)
    sources = heat_sources(layout, cell, stackup, technology, box)
    base = os.path.splitext(gds_path)[0]
    powers, instances, old_lvsdb, old_cfg = _previous(base)
    lvs_report = None
    if lvsdb:
        lvs_devices, notes = read_lvs_devices(lvsdb, layout, cell)
        instances, lvs_report = assign_names(sources, lvs_devices, technology, layout.dbu)
        lvs_report.update(named=len(instances), notes=notes)
    else:
        lvsdb = old_lvsdb
    layers = marker_layers(stackup, len(sources) + 1)
    outline_layer, source_layers = layers[0], layers[1:]
    clip = _clip(layout, box)
    extra = {(outline_layer, 0): pya.Region(clip if clip is not None else cell.bbox())}
    for layer, source in zip(source_layers, sources):
        extra[(layer, 0)] = source.area
    ref = stackup.layer(REF_NAME)       # patches of an EM export's replaced devices: no part of a thermal model
    result = export_flat(layout, cell, stackup, gds_path, box=box, with_ports=False,
                         drop=(ref.layer,) if ref is not None else (), extra=extra)

    write_tsimcfg(base + ".tsimcfg", gds_path, stackup.path, result.cellname,
                  [(layer, target, float(powers.get(s.device.id, 0.0))) for layer, s in zip(source_layers, sources)],
                  previous_cfg=old_cfg, outline_layer=outline_layer)
    um2 = layout.dbu ** 2
    rows = [{"layer": layer, "device": s.device.id, "pcell": s.device.pcell,
             "params": {k: str(v) for k, v in s.device.params.items()},
             "bbox_um": [round(v * layout.dbu, 4) for v in (s.device.bbox.left, s.device.bbox.bottom,
                                                            s.device.bbox.right, s.device.bbox.top)],
             "area_um2": round(s.area.area() * um2, 6), "polygons": s.area.count(), "heat_area_from": s.how,
             "from_pdk": s.from_pdk,
             "cut_by_region": s.cut, "instance": instances.get(s.device.id, (None, None))[0],
             "lvs_name": instances.get(s.device.id, (None, None))[1]}
            for layer, s in zip(source_layers, sources)]
    thermal_map = {"note": MAP_NOTE, "format": MAP_FORMAT, "technology": technology.NAME,
                   "gds": os.path.basename(gds_path), "cellname": result.cellname, "target_layer": target,
                   "outline_layer": outline_layer, "lvsdb": lvsdb and os.path.abspath(lvsdb).replace("\\", "/"),
                   "sources": rows}
    with open(base + "_thermalmap.json", "w") as f:
        json.dump(thermal_map, f, indent=2)
    return {"gds": gds_path, "tsimcfg": base + ".tsimcfg", "thermalmap": base + "_thermalmap.json",
            "cellname": result.cellname, "sources": len(sources),
            "bounding_box": [s.device.id for s in sources if not s.from_pdk],
            "from_rule": [s.device.id for s in sources if s.how == "rule"],
            "cut": [s.device.id for s in sources if s.cut], "kept_settings": old_cfg is not None,
            "lvs": lvs_report, "report": result.report()}
