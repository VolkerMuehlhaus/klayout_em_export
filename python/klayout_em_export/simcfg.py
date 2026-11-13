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


SIDES = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")     # order of settings['boundary']


def with_port_walls(boundary, sides):
    """settings['boundary'] (6 values, a single value or missing) with 'PORTWALL' on sides; the other sides as
    they were (missing: 'ABC', gds2palace's default)."""
    if isinstance(boundary, (list, tuple)) and len(boundary) == 6:
        values = list(boundary)
    else:
        values = [boundary if isinstance(boundary, str) and boundary else "ABC"] * 6
    for side in sides:
        values[SIDES.index(side)] = "PORTWALL"
    return values


def _most_common(values):
    return max(values, key=values.count) if values else None


def without_port_walls(saved, sides):
    """Take the port wall off sides (xmin, ...) in saved (setupEM saved_values), in place: a port wall without an
    in-plane port on it stops gds2palace ("port wall ... has no port"). The side gets the boundary, dielectric
    margin and air of the other sides (setupEM set 0 on a port wall: an absorbing boundary there would sit on the
    metal), and its port wall settings (extension, reference plane shift) are dropped."""
    boundary = saved.get("boundary")
    if not (isinstance(boundary, (list, tuple)) and len(boundary) == 6):
        return
    values = list(boundary)
    others = [values[i] for i, side in enumerate(SIDES) if values[i] != "PORTWALL"]
    for side in sides:
        values[SIDES.index(side)] = _most_common(others) or "ABC"
    saved["boundary"] = values
    walls = {side for side, value in zip(SIDES, values) if value == "PORTWALL"}
    for key, order in (("margin", SIDES[:4]), ("air_around", SIDES)):
        per_side = saved.get(key)
        if not (isinstance(per_side, list) and len(per_side) == len(order)):
            continue            # one value for all sides: setupEM did not change it for the port wall
        rest = [v for side, v in zip(order, per_side) if side not in walls and side not in sides]
        default = _most_common(rest)
        if default is not None:
            saved[key] = [default if side in sides else v for side, v in zip(order, per_side)]
    for key in ("port_wall_extension", "reference_plane_shift"):
        if isinstance(saved.get(key), dict):
            for side in sides:
                saved[key].pop(side, None)
            if not saved[key]:
                del saved[key]


def write_simcfg(path, gds_file, stackup_file, cellname, ports=(), purpose=(0,), port_walls=()):
    """Write or update path. port_walls: sides (xmin, ...) that get gds2palace's port wall; a side that has one in
    the existing file but is not in port_walls loses it (without_port_walls); the other sides keep their boundary.
    Returns True if an existing setupEM file was updated (its other settings kept)."""
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
    boundary = data["saved_values"].get("boundary")
    if isinstance(boundary, (list, tuple)) and len(boundary) == 6:
        stale = [side for side, value in zip(SIDES, boundary) if value == "PORTWALL" and side not in port_walls]
        without_port_walls(data["saved_values"], stale)
    if port_walls:
        data["saved_values"]["boundary"] = with_port_walls(data["saved_values"].get("boundary"), port_walls)
    data["ports"] = list(ports)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    return updated
