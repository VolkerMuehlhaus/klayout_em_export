"""Write a setupEM settings file (*.simcfg) for an exported layout.

Only the files, the cell and the ports are written. setupEM fills every other setting from its own preferences, as
it does for older settings files.
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


def write_simcfg(path, gds_file, stackup_file, cellname, ports=(), purpose=(0,)):
    data = {
        "application": "setupEM",
        "data_format": "1.0",
        "saved_values": {
            "unit": 1e-06,
            "purpose": list(purpose),
            "GdsFile": os.path.abspath(gds_file).replace("\\", "/"),
            "SubstrateFile": os.path.abspath(stackup_file).replace("\\", "/"),
            "cellname": cellname,
        },
        "ports": list(ports),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    return path
