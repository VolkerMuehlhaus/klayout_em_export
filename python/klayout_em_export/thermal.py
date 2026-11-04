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
from .export import PORT_LAYERS, export_flat
from .lvs import assign_names, read_lvs_devices
from .pipeline import EM_REGION, _clip, layout_devices
from .ports import settings_of

FIRST_LAYER = 201           # marker layers: the region outline, then one per heat source, skipping stackup layers
MAP_FORMAT = 1
MAP_NOTE = ("layer = marker layer of the heat source in the exported GDS and the .tsimcfg; device = the layout "
            "device (pcell name@x,y in dbu of its cell); instance = its name in the schematic (from LVS), if known, "
            "lvs_name = the same as in the LVS database (no element letters, upper case). "
            "area_um2 = heat area; heat_area_from: shapes (the PDK's heat shapes), rule (none drawn, e.g. an older "
            "PDK: the same rectangles from the device's layers) or bbox (the device's bounding box: a larger area, a "
            "lower peak temperature); from_pdk = not bbox. "
            "outline_layer: the region outline, for boundaries chosen in setupThermal.")


def _stackup_numbers(stackup):
    """The layer numbers the stackup uses: drawn, derived and boundary layers."""
    return {l.layer for l in stackup.layers} | set(stackup.gds_layers()) | set(stackup.derived)


def marker_layers(stackup, count, start=FIRST_LAYER, avoid=()):
    """count layer numbers from start on that the stackup does not use (also not as derived or boundary layer), nor
    avoid (the user's own thermal markers in the layout)."""
    used = _stackup_numbers(stackup) | set(avoid)
    layers, number = [], start
    while len(layers) < count:
        if number not in used:
            layers.append(number)
        number += 1
    return layers


def layout_thermal_config(layout_file, exclude=()):
    """(path, data) of the layout's own setupThermal file: the newest .tsimcfg next to layout_file whose GdsFile is
    that file, not one of exclude (the export's own); (None, None) if there is none."""
    if not layout_file:
        return None, None
    key = os.path.normcase(os.path.abspath(layout_file))
    folder = os.path.dirname(key)
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    found = []
    for name in os.listdir(folder) if os.path.isdir(folder) else ():
        path = os.path.join(folder, name)
        if not name.lower().endswith(".tsimcfg") or os.path.normcase(path) in skip:
            continue
        data = _read_json(path)
        gds = (data or {}).get("saved_values", {}).get("GdsFile") if isinstance(data, dict) else None
        if gds and os.path.normcase(os.path.abspath(gds)) == key and isinstance(data.get("thermal"), list):
            found.append((os.path.getmtime(path), path, data))
    if not found:
        return None, None
    _, path, data = max(found)
    return path, data


def user_markers(layout, cell, stackup, box=None, layout_file=None, exclude=()):
    """The thermal markers already drawn in the layout, which the export keeps on their layers: ({layer: Region in
    dbu of the cell}, the layout's setupThermal file or None). A marker layer is a layer that the layout's own
    setupThermal file uses (a heat source or boundary row, any layer number), or a layer of the EM port range 201..299
    with shapes that have no EM port settings. Stackup layers and EM port shapes (with settings) are never markers;
    only datatype 0 and the shapes touching box (DBox in µm, None: whole cell) count."""
    config_path, config = layout_thermal_config(layout_file, exclude)
    configured = {t.get("source_layernum") for t in (config or {}).get("thermal", [])}
    stackup_layers = _stackup_numbers(stackup)
    clip = _clip(layout, box)
    markers = {}
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.datatype != 0 or info.layer in stackup_layers or \
                (info.layer not in configured and info.layer not in PORT_LAYERS):
            continue
        region = pya.Region()
        it = cell.begin_shapes_rec(li) if clip is None else cell.begin_shapes_rec_touching(li, clip)
        while not it.at_end():
            shape = it.shape()
            if (shape.is_polygon() or shape.is_box() or shape.is_path()) and settings_of(shape) is None:
                region.insert(shape.polygon.transformed(it.trans()))
            it.next()
        if clip is not None:
            region &= pya.Region(clip)
        if not region.is_empty():
            markers[info.layer] = region
    return markers, config_path if config is not None and set(markers) & configured else None


def marker_rows(markers, previous_cfg, layout_config, previous_markers=()):
    """(rows, any from the layout's file): the setupThermal rows (heat sources, boundaries) of the user's markers.
    A marker that the previous export already kept as the user's (previous_markers, from its map) takes its row from
    the export's previous .tsimcfg, which holds the user's changes since; else, or without a usable row there, from
    the layout's own setupThermal file. Not usable: a boundary without a target layer, i.e. the export's own
    placeholder, which an export from before the markers were kept wrote on what was its region outline then."""
    previous = {t.get("source_layernum"): t for t in (previous_cfg or {}).get("thermal", [])
                if t.get("type") == "source" or t.get("target_layername")}
    own = {t.get("source_layernum"): t for t in (layout_config or {}).get("thermal", [])}
    rows, from_layout = [], False
    for layer in sorted(markers):
        if layer in previous_markers and layer in previous:
            rows.append(dict(previous[layer]))
        elif layer in own:
            rows.append(dict(own[layer]))
            from_layout = True
    return rows, from_layout


def left_out_layers(layout, cell, stackup, box=None, markers=(), purposes=(0,)):
    """[(layer, datatype)] with shapes in the region that the thermal export leaves out: not a stackup layer with one
    of the purposes (datatypes), apart from EM ports, the user's markers and the plug-in's own layers."""
    kept = set(stackup.gds_layers())                                # with one of the purposes
    skipped = set(markers) | set(PORT_LAYERS) | {EM_REGION[0]}      # any datatype
    ref = stackup.layer(REF_NAME)
    if ref is not None:
        skipped.add(ref.layer)
    clip = _clip(layout, box)
    left_out = []
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer in skipped or info.layer in kept and info.datatype in purposes:
            continue
        it = cell.begin_shapes_rec(li) if clip is None else cell.begin_shapes_rec_touching(li, clip)
        if not it.at_end():
            left_out.append((info.layer, info.datatype))
    return sorted(left_out)


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
    path, settings file data, the layers it kept as the user's markers)."""
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
    return powers, instances, old_map.get("lvsdb"), old_cfg, set(old_map.get("user_markers") or ())


PLACEHOLDER_TEMP = 300.0     # K


def placeholder_boundary(layer):
    """The boundary row the export writes when there is none yet: the region outline at a constant temperature, with
    no target layer (the height of the fixed temperature), which only the user can choose."""
    return {"source_layernum": layer, "target_layername": "", "type": "constanttemp", "temp": PLACEHOLDER_TEMP}


def write_tsimcfg(path, gds_file, stackup_file, cellname, sources, previous_cfg=None, purpose=(0,),
                  outline_layer=None, user_rows=(), marker_layers=()):
    """Write path: the files, the cell, the purpose and the heat sources [(layer, target, power)]; from
    previous_cfg (an earlier setupThermal file) everything else, including the boundaries. user_rows: the rows of
    the user's own markers (marker_rows), written as they are; previous rows on the marker_layers are not kept.
    Without any boundary, a placeholder boundary on outline_layer (if given): constant temperature, no target layer
    yet."""
    data = previous_cfg or {"application": "setupThermal", "data_format": "1.0", "saved_values": {"unit": 1e-06}}
    data["saved_values"].update({
        "purpose": list(purpose),
        "GdsFile": os.path.abspath(gds_file).replace("\\", "/"),
        "SubstrateFile": os.path.abspath(stackup_file).replace("\\", "/"),
        "cellname": cellname,
    })
    user_layers = {t.get("source_layernum") for t in user_rows} | set(marker_layers)
    boundaries = [t for t in data.get("thermal", []) if "SOURCE" not in str(t.get("type", "")).upper()
                  and t.get("source_layernum") not in user_layers]
    rows = [{"source_layernum": layer, "target_layername": target, "type": "source", "power": power}
            for layer, target, power in sources] + list(user_rows) + boundaries
    if outline_layer is not None and not any("SOURCE" not in str(t.get("type", "")).upper() for t in rows):
        rows.append(placeholder_boundary(outline_layer))
    data["thermal"] = rows
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def export_thermal(layout, cell, stackup, gds_path, technology, box=None, lvsdb=None, layout_file=None):
    """Export the region (box, a DBox in µm, else the whole cell) to gds_path, with <name>.tsimcfg and
    <name>_thermalmap.json next to it. lvsdb: an LVS database of the layout, for the schematic instance names (lvs.py);
    without it, the names of an earlier export are kept. layout_file: the layout's file, for its own setupThermal file
    (user_markers). The user's own thermal markers stay on their layers, with their rows. Returns a dict: gds, tsimcfg,
    thermalmap, cellname, sources (count), bounding_box (device ids with their bounding box as heat area), from_rule
    (device ids without PDK heat shapes, whose heat area comes from the PDK's rule), cut (device ids partly outside
    the region), kept_settings, lvs (None without lvsdb, else named (count), unnamed, conflicts, outside, notes),
    markers ({layer: 'source', 'constanttemp' or None for a marker without a row}), markers_from (the layout's
    setupThermal file the rows came from, or None), left_out ([(layer, datatype)] not in the stackup), report.
    Raises ValueError if the stackup has no usable layer for the heat sources or lvsdb is unusable."""
    target = heat_target(stackup, technology)
    sources = heat_sources(layout, cell, stackup, technology, box)
    base = os.path.splitext(gds_path)[0]
    powers, instances, old_lvsdb, old_cfg, old_markers = _previous(base)
    markers, markers_from = user_markers(layout, cell, stackup, box, layout_file, exclude=(base + ".tsimcfg",))
    user_rows, from_layout = marker_rows(markers, old_cfg, _read_json(markers_from) if markers_from else None,
                                         old_markers)
    if not from_layout:
        markers_from = None         # no row came from the layout's own setupThermal file
    purposes = export_purposes(old_cfg, layout_thermal_config(layout_file, (base + ".tsimcfg",))[1])
    left_out = left_out_layers(layout, cell, stackup, box, markers, purposes)
    lvs_report = None
    if lvsdb:
        lvs_devices, notes = read_lvs_devices(lvsdb, layout, cell)
        instances, lvs_report = assign_names(sources, lvs_devices, technology, layout.dbu)
        lvs_report.update(named=len(instances), notes=notes)
    else:
        lvsdb = old_lvsdb
    layers = marker_layers(stackup, len(sources) + 1, avoid=markers)
    outline_layer, source_layers = layers[0], layers[1:]
    clip = _clip(layout, box)
    extra = {(outline_layer, 0): pya.Region(clip if clip is not None else cell.bbox())}
    for layer, source in zip(source_layers, sources):
        extra[(layer, 0)] = source.area
    for layer, region in markers.items():
        extra[(layer, 0)] = region
    ref = stackup.layer(REF_NAME)       # patches of an EM export's replaced devices: no part of a thermal model
    result = export_flat(layout, cell, stackup, gds_path, box=box, purposes=purposes, with_ports=False,
                         drop=(ref.layer,) if ref is not None else (), extra=extra)

    write_tsimcfg(base + ".tsimcfg", gds_path, stackup.path, result.cellname,
                  [(layer, target, float(powers.get(s.device.id, 0.0))) for layer, s in zip(source_layers, sources)],
                  previous_cfg=old_cfg, purpose=purposes, outline_layer=outline_layer, user_rows=user_rows,
                  marker_layers=markers)
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
                   "user_markers": sorted(markers), "sources": rows}
    with open(base + "_thermalmap.json", "w") as f:
        json.dump(thermal_map, f, indent=2)
    return {"gds": gds_path, "tsimcfg": base + ".tsimcfg", "thermalmap": base + "_thermalmap.json",
            "cellname": result.cellname, "sources": len(sources),
            "bounding_box": [s.device.id for s in sources if not s.from_pdk],
            "from_rule": [s.device.id for s in sources if s.how == "rule"],
            "cut": [s.device.id for s in sources if s.cut], "kept_settings": old_cfg is not None,
            "lvs": lvs_report, "markers": marker_kinds(markers, user_rows), "markers_from": markers_from,
            "left_out": left_out, "report": result.report()}


def marker_preview(layout, cell, stackup, box, layout_file, gds_path):
    """What an export to gds_path would keep and leave out, for the dialog and the panel: (markers {layer: kind, see
    marker_kinds}, where their rows come from (text), left_out [(layer, datatype)])."""
    base = os.path.splitext(gds_path)[0] if gds_path else None
    old_cfg, old_markers = _previous(base)[3:] if base else (None, set())
    exclude = (base + ".tsimcfg",) if base else ()
    markers, markers_from = user_markers(layout, cell, stackup, box, layout_file, exclude)
    rows, from_layout = marker_rows(markers, old_cfg, _read_json(markers_from) if markers_from else None,
                                    old_markers)
    purposes = export_purposes(old_cfg, layout_thermal_config(layout_file, exclude)[1])
    origin = (os.path.basename(markers_from) if from_layout and markers_from else
              "the earlier export" if rows else None)
    return marker_kinds(markers, rows), origin, left_out_layers(layout, cell, stackup, box, markers, purposes)


def describe_markers(kinds, origin):
    """One line about the user's markers that the export keeps, e.g. '201 (heat source), 203 (boundary), rows from
    x.tsimcfg'."""
    words = {"source": "heat source", "constanttemp": "boundary", None: "no row yet, define it in setupThermal"}
    text = ", ".join(f"{layer} ({words[kind]})" for layer, kind in kinds.items())
    return text + (f", rows from {origin}" if origin and any(kinds.values()) else "")


def export_purposes(previous_cfg, layout_config):
    """The datatypes the export keeps: the purposes of the export's previous .tsimcfg and of the layout's own
    setupThermal file together (e.g. [0, 35, 4] for CuPillar shapes on 41/35), (0,) without either. Together, since an
    earlier export may have written only [0] before the layout's purposes were taken over."""
    purposes = set()
    for data in (previous_cfg, layout_config):
        purpose = ((data or {}).get("saved_values") or {}).get("purpose")
        if isinstance(purpose, list) and all(isinstance(p, int) for p in purpose):
            purposes |= set(purpose)
    return tuple(sorted(purposes)) or (0,)


def marker_kinds(markers, rows):
    """{marker layer: 'source', 'constanttemp' or None (no row yet: to be defined in setupThermal)}."""
    kind = {t.get("source_layernum"): "source" if "SOURCE" in str(t.get("type", "")).upper() else "constanttemp"
            for t in rows}
    return {layer: kind.get(layer) for layer in sorted(markers)}
