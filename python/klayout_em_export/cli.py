"""Headless JSON interface for scripts and AI agents. Run with KLayout in batch mode (it has the Qt that the IHP PDK's
device library needs):

    klayout -zz -rd request=req.json -rd result=res.json -r <repo>/python/klayout_em_export/cli.py

tools/em_cli.py does this from any Python. The request is one JSON object:

    {"command": "...", "gds": "layout.gds", "cell": "TOP" (default: the top cell),
     "stackup": "stack.xml" (default: the layout's own, from its meta info),
     "technology": "ihp_sg13" | "generic" (default: from the layout, tech.for_layout),
     "pdk": ".../IHP-Open-PDK/ihp-sg13g2" (loads the SG13_dev device library; needed for PDK pcells),
     "klayout_technology": "sg13g2" (the layout's KLayout technology; default with "pdk": sg13g2),
     "output": "out.gds", "overwrite": false, ...command arguments}

The result is {"ok": true, ...} or {"ok": false, "error": "..."}. Coordinates are in µm. Commands that change the
layout write it to "output" (it may be "gds" only with "overwrite": true), with the stackup and ground marks as meta
info, so KLayout and the plug-in open it as if the steps were done by hand. The settings file
(~/.klayout_em_export.json) is never read or written.

Commands: status, add_via_port, add_inplane_port, set_port, remove_port, boundary_ports, set_region, mark_ground,
devices, export, export_thermal. See README, "Headless use".
"""
import json
import os
import sys
import traceback

import pya

# run as a script by KLayout: make the package importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from klayout_em_export import __version__, tech                           # noqa: E402
from klayout_em_export.boundary import create_ports, find_crossings      # noqa: E402
from klayout_em_export.connectivity import check_ground                  # noqa: E402
from klayout_em_export.devices import replace, unreplace                 # noqa: E402
from klayout_em_export.export import marker_box                          # noqa: E402
from klayout_em_export.locate import (drawn_metals, edge_at, gap_at, metals_at, next_port_layer,  # noqa: E402
                                      via_layers)
from klayout_em_export.pipeline import (EM_REGION, META_GROUND, META_STACKUP, NoUndo, export_checks,  # noqa: E402
                                        export_em, layout_devices, region_ports)
from klayout_em_export.ports import PROP_KEY, PortSettings, port_problems, is_complete            # noqa: E402
from klayout_em_export.stackup import Stackup                            # noqa: E402
from klayout_em_export.thermal import export_thermal                      # noqa: E402

class RequestError(Exception):
    """A problem with the request: reported as the error, without a traceback."""


# ---------- loading ----------

def _pdk_klayout_dir(path):
    """The libs.tech/klayout folder of an IHP PDK given as that folder, the ihp-sg13g2 folder or the PDK root."""
    for candidate in (path, os.path.join(path, "libs.tech", "klayout"),
                      os.path.join(path, "ihp-sg13g2", "libs.tech", "klayout")):
        if os.path.isfile(os.path.join(candidate, "tech", "sg13g2.lyt")):
            return candidate
    raise RequestError(f"no IHP PDK at {path} (expected libs.tech/klayout/tech/sg13g2.lyt)")


def load_pdk(path):
    """Register the sg13g2 technology and the SG13_dev device library (as klayout_em_export_tests/pdk_env.py)."""
    klayout_dir = _pdk_klayout_dir(path)
    python_dir = os.path.join(klayout_dir, "python")
    for p in (os.path.join(python_dir, "pycell4klayout-api", "source", "python"), python_dir):
        if p not in sys.path:
            sys.path.insert(0, p)
    if not pya.Technology.has_technology("sg13g2"):
        pya.Technology.create_technology("sg13g2").load(os.path.join(klayout_dir, "tech", "sg13g2.lyt"))
    if pya.Library.library_by_name("SG13_dev", "sg13g2") is None:
        import cni.dlo
        cni.dlo.PCellWrapper.coerce_parameters = lambda self, layout, v: v    # no Tcl callbacks in batch
        import sg13g2_pycell_lib  # noqa: F401  registers SG13_dev


def open_layout(request):
    gds = request.get("gds")
    if not gds or not os.path.isfile(gds):
        raise RequestError(f"no layout file: {gds!r}")
    if request.get("pdk"):
        load_pdk(request["pdk"])
    layout = pya.Layout()
    # the PDK library binds its pcells only when the layout has its technology before reading. Only on request
    # ("pdk" or "klayout_technology"), not because KLayout happens to know the technology: the same request gives
    # the same result on every machine (tech.for_layout also uses the technology name).
    if request.get("pdk") or request.get("klayout_technology"):
        layout.technology_name = request.get("klayout_technology", "sg13g2")
    layout.read(gds)
    name = request.get("cell")
    tops = [c.name for c in layout.top_cells()]
    if not name and len(tops) != 1:
        raise RequestError(f"{gds} has {len(tops)} top cells: give 'cell' (one of {', '.join(tops)})")
    cell = layout.cell(name or tops[0])
    if cell is None:
        raise RequestError(f"no cell {name!r} in {gds}")
    return layout, cell


def stackup_of(request, layout):
    path = request.get("stackup") or layout.meta_info_value(META_STACKUP)
    if not path:
        raise RequestError("no stackup: give 'stackup' (the layout has none in its meta info)")
    if not os.path.isfile(path):
        raise RequestError(f"stackup not found: {path}")
    if request.get("stackup"):
        layout.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, path, "stackup for EM export", True))
    return Stackup(path)


def technology_of(request, layout):
    name = request.get("technology")
    try:
        technology, reason = tech.for_layout(layout, name)
    except ValueError as e:
        raise RequestError(str(e))
    return technology, "given in the request" if name else reason


def ground_seeds(layout):
    try:
        return [(int(l), pya.Point(int(x), int(y))) for l, x, y in json.loads(layout.meta_info_value(META_GROUND) or "[]")]
    except (TypeError, ValueError):
        return []


def save(request, layout, result):
    out = request.get("output")
    if not out:
        raise RequestError("this command changes the layout: give 'output' (a new file, or the input with "
                           "'overwrite': true)")
    if os.path.abspath(out) == os.path.abspath(request["gds"]) and not request.get("overwrite"):
        raise RequestError("'output' is the input layout: set 'overwrite': true to replace it")
    layout.write(out)
    result["output"] = out
    return result


# ---------- conversions ----------

def _um(layout, value):
    return round(value / layout.dbu)


def _point(layout, request):
    try:
        return pya.Point(_um(layout, float(request["x"])), _um(layout, float(request["y"])))
    except (KeyError, TypeError, ValueError):
        raise RequestError("give 'x' and 'y' in µm")


def _box(layout, values):
    try:
        x1, y1, x2, y2 = (float(v) for v in values)
    except (TypeError, ValueError):
        raise RequestError("a box is [x1, y1, x2, y2] in µm")
    return pya.DBox(x1, y1, x2, y2)


def _dbox(layout, box):
    d = box.to_dtype(layout.dbu)
    return [round(d.left, 4), round(d.bottom, 4), round(d.right, 4), round(d.top, 4)]


def _port_box(port):
    """Bounding box of the port's shapes in the cell (dbu)."""
    box = pya.Box()
    for shape, trans, _ in port.items:
        box += shape.bbox().transformed(trans)
    return box


def _metal_layer(stackup, name):
    layers = dict(drawn_metals(stackup))
    if name not in layers:
        raise RequestError(f"{name!r} is not a drawn metal of the stackup ({', '.join(layers)})")
    return layers[name]


def _region_box(request, layout, cell):
    """DBox of the request's 'box', else the EM region box (layer 800/0), else None (whole cell)."""
    if request.get("box"):
        return _box(layout, request["box"])
    return marker_box(layout, cell, EM_REGION)      # DBox or None


def _port_shape(layout, cell, number):
    layer = 200 + int(number)
    li = layout.find_layer(layer, 0)
    shapes = [] if li is None else list(cell.shapes(li).each())
    if not shapes:
        raise RequestError(f"no port {number} (layer {layer}/0) in cell {cell.name}")
    return li, shapes


def _settings(request, base):
    """PortSettings from base, changed by the request's direction, from, to, target, z0, excited."""
    s = base or PortSettings()
    return PortSettings(request.get("direction", s.direction), request.get("from", s.from_layer),
                        request.get("to", s.to_layer), request.get("target", s.target),
                        float(request.get("z0", s.z0)), (1.0 if request["excited"] else 0.0)
                        if "excited" in request else s.voltage)


def _add_port(layout, cell, stackup, box, settings):
    layer = next_port_layer(layout, cell, stackup=stackup)
    if layer is None:
        raise RequestError("all port layers 201..299 are used in this cell")
    cell.shapes(layout.layer(layer, 0)).insert(box, layout.properties_id([[PROP_KEY, settings.encode()]]))
    return {"port": layer - 200, "layer": layer, "settings": settings.encode(), "box": _dbox(layout, box)}


# ---------- commands ----------

def cmd_status(request, layout, cell):
    stackup = stackup_of(request, layout)
    technology, reason = technology_of(request, layout)
    box = _region_box(request, layout, cell)
    seeds = ground_seeds(layout)
    ports = region_ports(layout, cell, stackup, box)
    devices, unknown = layout_devices(layout, cell, stackup, technology)
    check = check_ground(layout, cell, stackup, None if box is None else box.to_itype(layout.dbu), seeds, ports)
    return {
        "version": __version__, "cell": cell.name, "stackup": stackup.path,
        "metals": [n for n, _ in drawn_metals(stackup)],
        "technology": technology.NAME, "technology_reason": reason,
        "region": None if box is None else [box.left, box.bottom, box.right, box.top],
        "ground": {"summary": check.summary(), "marks": len(seeds)},
        "ports": [{"port": p.number, "layer": layer, "settings": p.settings.encode() if p.settings else None,
                   "complete": is_complete(p), "problems": port_problems(p, stackup), "box": _dbox(layout, _port_box(p))}
                  for layer, p in sorted(ports.items())],
        "devices": [{"id": d.id, "pcell": d.pcell, "replaced": d.replaced, "problems": list(d.problems)}
                    for d in devices],
        "unknown_devices": [{"cell": name, "count": n} for name, n in unknown],
        "export_checks": export_checks(layout, cell, stackup, ports, devices, seeds, box),
    }


def cmd_add_via_port(request, layout, cell):
    """A via port on the metal edge nearest to x, y (within 'tol' µm, default 0.5): from the clicked metal down to
    the next metal at the port, as the EM Port tool does. 'metal' limits the search to that metal; 'to' overrides
    the other end."""
    stackup = stackup_of(request, layout)
    layers = {_metal_layer(stackup, request["metal"])} if request.get("metal") else None
    found = edge_at(layout, cell, stackup, _point(layout, request), _um(layout, float(request.get("tol", 0.5))), layers)
    if found is None:
        raise RequestError("no horizontal or vertical metal edge there" + (f" on {request['metal']}"
                                                                         if request.get("metal") else ""))
    metal, edge = found
    here = metals_at(layout, cell, stackup, edge.bbox())
    from_layer, to_layer = via_layers(here, metal)
    settings = _settings(request, PortSettings("Z", from_layer, to_layer))
    result = _add_port(layout, cell, stackup, edge.bbox(), settings)
    result.update(metal=metal, metals_at_port=here)
    return save(request, layout, result)


def cmd_add_inplane_port(request, layout, cell):
    """An in-plane port across the narrowest gap between two shapes of one metal around x, y (looking up to
    'reach' µm, default 20); 'metal' limits the search."""
    stackup = stackup_of(request, layout)
    layers = {_metal_layer(stackup, request["metal"])} if request.get("metal") else None
    found = gap_at(layout, cell, stackup, _point(layout, request), _um(layout, float(request.get("reach", 20))),
                   layers)
    if found is None:
        raise RequestError("no gap between two shapes of one metal there (the point must not be on metal)")
    metal, box, direction = found
    settings = _settings(request, PortSettings(direction, target=metal))
    result = _add_port(layout, cell, stackup, box, settings)
    result.update(metal=metal)
    return save(request, layout, result)


def cmd_set_port(request, layout, cell):
    """Change the settings of port 'port' (all shapes on its layer): direction, from, to, target, z0, excited."""
    stackup = stackup_of(request, layout)
    li, shapes = _port_shape(layout, cell, request.get("port", 0))
    settings = _settings(request, PortSettings.decode(shapes[0].property(PROP_KEY)))
    props = layout.properties_id([[PROP_KEY, settings.encode()]])
    for shape in shapes:
        box = shape.bbox()      # replace instead of set_property: KLayout 0.29 can move a shape on set_property
        cell.shapes(li).erase(shape)
        cell.shapes(li).insert(box, props)
    port = region_ports(layout, cell, stackup).get(200 + int(request["port"]))
    return save(request, layout, {"port": int(request["port"]), "settings": settings.encode(),
                                  "problems": port_problems(port, stackup) if port else []})


def cmd_remove_port(request, layout, cell):
    li, shapes = _port_shape(layout, cell, request.get("port", 0))
    cell.shapes(li).clear()
    return save(request, layout, {"port": int(request["port"]), "removed_shapes": len(shapes)})


def cmd_boundary_ports(request, layout, cell):
    """Signal metals crossing the region's edge ('box', else the EM region): listed, and with 'create': true, via
    ports at those that need one (to the ground metal at the cut), as Create Proposed Ports does."""
    stackup = stackup_of(request, layout)
    box = _region_box(request, layout, cell)
    if box is None:
        raise RequestError("no region: give 'box' or set the EM region (set_region)")
    clip = box.to_itype(layout.dbu)
    ground = check_ground(layout, cell, stackup, clip, ground_seeds(layout),
                          region_ports(layout, cell, stackup, box))
    crossings = find_crossings(layout, cell, stackup, clip, ground)
    created = create_ports(NoUndo(), cell, stackup, crossings, float(request.get("z0", 50))) if request.get("create") else []
    result = {"crossings": [{"side": c.side, "metal": c.name, "edge": _dbox(layout, c.edge.bbox()),
                             "status": c.status()} for c in crossings], "created": created}
    return save(request, layout, result) if created else result


def cmd_set_region(request, layout, cell):
    """The EM region box (layer 800/0): 'box' [x1, y1, x2, y2] µm, or null to remove it."""
    li = layout.layer(*EM_REGION)
    cell.shapes(li).clear()
    if request.get("box"):
        cell.shapes(li).insert(_box(layout, request["box"]).to_itype(layout.dbu))
    return save(request, layout, {"region": request.get("box")})


def cmd_mark_ground(request, layout, cell):
    """Ground marks: 'points' [[metal, x, y], ...] (a point inside a ground shape on that metal), added to the
    layout's marks; 'clear': true removes the marks first."""
    stackup = stackup_of(request, layout)
    seeds = [] if request.get("clear") else ground_seeds(layout)
    for item in request.get("points", []):
        try:
            name, x, y = item
        except (TypeError, ValueError):
            raise RequestError("a ground point is [metal, x, y] (µm)")
        seeds.append((_metal_layer(stackup, name), pya.Point(_um(layout, float(x)), _um(layout, float(y)))))
    layout.add_meta_info(pya.LayoutMetaInfo(META_GROUND, json.dumps([[l, p.x, p.y] for l, p in seeds]),
                                            "EM export: points in the marked ground shapes", True))
    check = check_ground(layout, cell, stackup, seeds=seeds, ports=region_ports(layout, cell, stackup))
    return save(request, layout, {"marks": len(seeds), "ground": check.summary()})


def cmd_devices(request, layout, cell):
    """'action': list (default), replace (with 'resistors': true also the resistors) or unreplace."""
    stackup = stackup_of(request, layout)
    technology = technology_of(request, layout)[0]
    action = request.get("action", "list")
    result = {"technology": technology.NAME}
    if action == "replace":
        try:
            result["replaced"] = replace(NoUndo(), cell, stackup, layout_devices(layout, cell, stackup, technology)[0],
                                         bool(request.get("resistors", True)))
        except ValueError as e:
            raise RequestError(str(e))
    elif action == "unreplace":
        result["removed_shapes"] = unreplace(NoUndo(), cell)
    elif action != "list":
        raise RequestError(f"unknown devices action {action!r} (list, replace, unreplace)")
    devices, unknown = layout_devices(layout, cell, stackup, technology)
    result["devices"] = [{"id": d.id, "pcell": d.pcell, "replaced": d.replaced, "resistor": d.is_resistor,
                          "problems": list(d.problems)} for d in devices]
    result["unknown_devices"] = [{"cell": name, "count": n} for name, n in unknown]
    return save(request, layout, result) if action != "list" else result


def cmd_export(request, layout, cell):
    """Export the region ('box', else the EM region, else the whole cell; 'whole': true ignores the EM region) to
    'out' (.gds), with the .simcfg and _portmap.json next to it."""
    stackup = stackup_of(request, layout)
    technology = technology_of(request, layout)[0]
    out = request.get("out")
    if not out or not out.lower().endswith(".gds"):
        raise RequestError("give 'out', the EM layout to write (.gds)")
    if os.path.abspath(out) == os.path.abspath(request["gds"]):
        raise RequestError("'out' is the layout itself")
    box = None if request.get("whole") else _region_box(request, layout, cell)
    seeds = ground_seeds(layout)
    ports = region_ports(layout, cell, stackup, box)
    checks = export_checks(layout, cell, stackup, ports, layout_devices(layout, cell, stackup, technology)[0],
                           seeds, box)
    if checks["numbering_error"]:
        raise RequestError(checks["numbering_error"])
    result = export_em(layout, cell, stackup, out, technology, box=box, seeds=seeds)
    result.pop("port_list")
    result["checks"] = checks
    return result


def cmd_export_thermal(request, layout, cell):
    """Thermal export (thermal.py) of the region ('box', else the EM region, else the whole cell; 'whole': true
    ignores the EM region) to 'out' (.gds), with the .tsimcfg and _thermalmap.json next to it."""
    stackup = stackup_of(request, layout)
    technology = technology_of(request, layout)[0]
    out = request.get("out")
    if not out or not out.lower().endswith(".gds"):
        raise RequestError("give 'out', the thermal layout to write (.gds)")
    if os.path.abspath(out) == os.path.abspath(request["gds"]):
        raise RequestError("'out' is the layout itself")
    box = None if request.get("whole") else _region_box(request, layout, cell)
    try:
        return export_thermal(layout, cell, stackup, out, technology, box=box)
    except ValueError as e:
        raise RequestError(str(e))


COMMANDS = {name[4:]: f for name, f in globals().items() if name.startswith("cmd_")}


def run(request):
    command = request.get("command")
    if command not in COMMANDS:
        raise RequestError(f"unknown command {command!r} ({', '.join(sorted(COMMANDS))})")
    layout, cell = open_layout(request)
    result = COMMANDS[command](request, layout, cell)
    result["ok"] = True
    return result


def main(request_path, result_path):
    try:
        with open(request_path, encoding="utf-8") as f:
            result = run(json.load(f))
    except RequestError as e:
        result = {"ok": False, "error": str(e)}
    except Exception as e:      # report, don't hang KLayout
        result = {"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)


# KLayout passes -rd values as global variables
if "request" in globals() and "result" in globals():
    main(globals()["request"], globals()["result"])
