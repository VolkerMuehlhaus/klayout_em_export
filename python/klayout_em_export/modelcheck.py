"""Model scripts (setupEM or hand-written gds2palace *.py) that read an exported GDS, and whether their ports still
match the export.

A re-export writes the same GDS file again, and numbers the ports 1..N without gaps, so adding, removing or
replacing one port can renumber others. A model script made before still reads that file, with its old port list:
its port 3 may now sit on another layer, and the S-parameters no longer belong to the port map. This module finds
such scripts so the export can warn. Scripts are read with ast (never run): a script is for the GDS if one of its
string literals, taken relative to the script's folder, is that file; its ports are its simulation_port(...) calls
with literal keyword arguments.

Compared per port number: source layer, direction, from/to layer (via port) and target layer (in-plane port). Not
compared: excitation (voltage) and Z0, which are changed in scripts on purpose.
"""
import ast
import glob
import os

KEYS = ("source_layernum", "direction", "from_layername", "to_layername", "target_layername")


def _same_file(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _norm(key, value):
    if key == "direction" and isinstance(value, str):
        return value.upper()
    if key == "source_layernum" and value is not None:
        return int(value)
    return value or None


def port_signature(entry):
    """(source layer, direction, from, to, target) of one port: a .simcfg port entry or simulation_port keywords."""
    return tuple(_norm(k, entry.get(k)) for k in KEYS)


def script_info(path, gds_path):
    """{port number: signature} of a script that reads gds_path, None if the script is not for that GDS (or cannot
    be parsed)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    if os.path.basename(gds_path) not in text:          # cheap test before parsing
        return None
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    folder = os.path.dirname(os.path.abspath(path))
    reads_gds = any(isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.lower().endswith(".gds")
                    and _same_file(os.path.join(folder, n.value), gds_path) for n in ast.walk(tree))
    if not reads_gds:
        return None
    ports = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if name != "simulation_port":
            continue
        args = {}
        for keyword in node.keywords:
            try:
                args[keyword.arg] = ast.literal_eval(keyword.value)
            except ValueError:
                args[keyword.arg] = "?"               # not a literal: compared as unknown
        if isinstance(args.get("portnumber"), int):
            ports[args["portnumber"]] = port_signature(args)
    return ports


def differences(script_ports, export_ports):
    """Readable differences between {number: signature} of a script and of the export, [] if they match."""
    out = []
    missing = sorted(set(export_ports) - set(script_ports))
    extra = sorted(set(script_ports) - set(export_ports))
    if missing:
        out.append("not in the script: port " + ", ".join(map(str, missing)))
    if extra:
        out.append("no longer exported: port " + ", ".join(map(str, extra)))
    for number in sorted(set(script_ports) & set(export_ports)):
        old, new = script_ports[number], export_ports[number]
        if old != new:
            out.append(f"port {number}: was {describe(old)}, now {describe(new)}")
    return out


def describe(signature):
    """'via TopMetal2 -> Metal5 (Z) on layer 201' or 'in-plane X on Metal5, layer 203'."""
    layer, direction, frm, to, target = signature
    if direction and "Z" in str(direction):
        return f"via {frm} -> {to} ({direction}) on layer {layer}"
    return f"in-plane {direction} on {target}, layer {layer}"


def stale_scripts(gds_path, port_list, folders):
    """[(script path, [differences])] of the model scripts in folders that read gds_path and whose ports differ from
    port_list (the export's .simcfg port entries)."""
    export_ports = {int(p["portnumber"]): port_signature(p) for p in port_list}
    seen, out = set(), []
    for folder in folders:
        if not folder or not os.path.isdir(folder):
            continue
        for path in sorted(glob.glob(os.path.join(folder, "*.py"))):
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                continue
            seen.add(key)
            ports = script_info(path, gds_path)
            if ports is None:
                continue
            diff = differences(ports, export_ports)
            if diff:
                out.append((path, diff))
    return out
