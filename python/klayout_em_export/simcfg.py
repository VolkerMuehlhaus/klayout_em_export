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
