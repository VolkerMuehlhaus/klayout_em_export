"""Write a setupEM settings file (*.simcfg) for an exported layout.

A new file gets only the files, the cell and the ports; setupEM fills every other setting from its own preferences,
as it does for older settings files. An existing setupEM file is updated instead: the export sets the files, the
cell, the purpose and the ports, and keeps everything else (frequencies, mesh, ...) as last saved in setupEM. The
ports always come from the layout, where they are defined.
"""
import json
import os


def port_entry(portnumber, source_layernum, direction, target_layername=None, from_layername=None,
               to_layername=None, port_Z0=50.0, voltage=1.0):
    """One port as setupEM stores it. Via ports (direction Z or -Z) use from/to layers, in-plane ports a target."""
    via = "Z" in direction.upper()
    return {"portnumber": int(portnumber), "source_layernum": int(source_layernum),
            "target_layername": None if via else target_layername,
            "from_layername": from_layername if via else None,
            "to_layername": to_layername if via else None,
            "direction": direction, "port_Z0": float(port_Z0), "voltage": float(voltage)}


def own_setup_files(layout_file, suffixes=(".simcfg", ".tsimcfg"), exclude=()):
    """[(path, data)] of the user's own setupEM / setupThermal files for a layout, newest first: the files with one
    of the suffixes next to layout_file whose GdsFile is that file, not one of exclude (the export's own)."""
    if not layout_file:
        return []
    key = os.path.normcase(os.path.abspath(layout_file))
    folder = os.path.dirname(key)
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    found = []
    for name in os.listdir(folder) if os.path.isdir(folder) else ():
        path = os.path.join(folder, name)
        if not name.lower().endswith(tuple(suffixes)) or os.path.normcase(path) in skip:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            gds = data["saved_values"]["GdsFile"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if gds and os.path.normcase(os.path.abspath(gds)) == key:
            found.append((os.path.getmtime(path), path, data))
    return [(path, data) for _, path, data in sorted(found, key=lambda f: f[0], reverse=True)]


def merged_purposes(*datas):
    """The purposes (datatypes) of setupEM / setupThermal file data together, e.g. (0, 4, 35) for CuPillar shapes on
    41/35; (0,) if none of them has any."""
    purposes = set()
    for data in datas:
        purpose = ((data or {}).get("saved_values") or {}).get("purpose")
        if isinstance(purpose, list) and all(isinstance(p, int) for p in purpose):
            purposes |= set(purpose)
    return tuple(sorted(purposes)) or (0,)


def em_export_purposes(simcfg_path, layout_file):
    """(purposes, source file names) for the EM export: the purposes of the export's previous .simcfg (where setupEM
    keeps the user's choice) and of the user's own setupEM / setupThermal files for the layout together, (0,) without
    any; the names of the user's files that gave some."""
    own = own_setup_files(layout_file)
    sources = [os.path.basename(path) for path, data in own if (data.get("saved_values") or {}).get("purpose")]
    return merged_purposes(_existing(simcfg_path), *(data for _, data in own)), sources


def _existing(path):
    """The setupEM data in path, or None if there is no such file (or it is not a setupEM settings file)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("application") != "setupEM" or \
            not isinstance(data.get("saved_values"), dict):
        return None
    return data


def write_simcfg(path, gds_file, stackup_file, cellname, ports=(), purpose=(0,)):
    """Write or update path. Returns True if an existing setupEM file was updated (its other settings kept)."""
    data = _existing(path)
    updated = data is not None
    if data is None:
        data = {"application": "setupEM", "data_format": "1.0", "saved_values": {"unit": 1e-06}}
    data["saved_values"].update({
        "purpose": list(purpose),
        "GdsFile": os.path.abspath(gds_file).replace("\\", "/"),
        "SubstrateFile": os.path.abspath(stackup_file).replace("\\", "/"),
        "cellname": cellname,
    })
    data["ports"] = list(ports)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    return updated
