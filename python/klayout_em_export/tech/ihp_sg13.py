"""IHP SG13G2 and SG13CMOS5L: the PDK devices that can be replaced by ports, and where their terminals are.

Both processes share the device library (SG13_dev), its pcells (SG13CMOS5L has no npn), the layer numbers used here
and the model libraries, so one technology covers both; KLayout's technology name tells them apart (sg13g2,
sg13cmos5l), which only matters for the stackup.

Supported: SG13_dev pcells with named pins, i.e. pin shapes (datatype 2 on a metal layer) and a TEXT label with the
terminal name inside each: npn13G2, npn13G2L, npn13G2V (C, B on Metal1; E on Metal2) and the rf MOSFETs (S, D, G,
TIE); nmos/pmos (unnamed or no pins: terminals from the geometry); the resistors rsil, rppd, rhigh (two unnamed
Metal1 pins). Static device cells are recognized by name: exported from Cadence (<pcell name>_CDNS_<number>), or
a pcell saved without its pcell context (<pcell name>$<number>, e.g. by a fill tool). They have no parameters: an
npn's come from its 'Ae=Nx*Ny*we*le' label, a resistor's value from its label (see ihp_sg13_circuit).
"""
import re

import pya

NAME = "ihp_sg13"
LABEL = "IHP SG13G2 / SG13CMOS5L"
KLAYOUT_TECHNOLOGIES = ("sg13g2", "sg13cmos5l")
DEVICE_PCELLS = {"npn13G2", "npn13G2L", "npn13G2V", "rfnmos", "rfpmos", "rfnmosHV", "rfpmosHV"}   # named pins
MOSFET_PCELLS = {"nmos", "pmos", "nmosHV", "pmosHV"}    # unnamed (nmos) or no (pmos) pins: terminals from geometry
RESISTOR_PCELLS = {"rsil", "rppd", "rhigh"}             # two unnamed Metal1 pins (PLUS, MINUS); replaced on request
PCELL_PARAMETERS = ("model", "Nx", "Ny", "le", "we", "w", "l", "ng", "b")   # kept for the circuit wrapper
STATIC_SUFFIX = "_CDNS_"            # a device cell exported from Cadence: <pcell name>_CDNS_<number>, no pcell context
AE_LABEL = re.compile(r"Ae=(\d+)\*(\d+)\*([0-9.]+)\*([0-9.]+)")     # npn label: Ae=Nx*Ny*we*le (we, le in um)
POLY_LAYER = 5                      # SG13G2 GatPoly.drawing (datatype 0)
CONT_NAME = "Cont"
LIBRARY = "SG13_dev"
PIN_DATATYPE = 2                    # SG13G2 pin purpose, e.g. Metal1.pin = 8/2
TEXT_LAYER = (63, 0)                # SG13G2 TEXT.drawing: the pin names
DEVICE_LEVEL = {"Activ"}            # diffusion, below Metal1: not traced as wiring (see connectivity.py)
# where the PDK's pcells mark the heat a device dissipates (sg13g2_pycell_lib/ihp/thermal.py): rectangles over each
# MOS gate finger and npn emitter (HeatTrans) and over each resistor body stripe (HeatRes)
HEAT_LAYERS = ((51, 0), (52, 0))    # HeatTrans.drawing, HeatRes.drawing
# PDK versions before the heat shapes (e.g. March 2025) and static cells from such a PDK do not draw them: the same
# rectangles from the device's own layers, as the pcells derive them (npn*_code.py, rsil/rppd/rhigh_code.py)
EMWIND_LAYER = (33, 0)              # EmWind.drawing: npn emitter window; HeatTrans = each window grown by 0.05 µm
EMWIND_HEAT_GROW = 0.05             # µm
POLYRES_LAYER = (128, 0)            # PolyRes.drawing: resistor body; HeatRes = the same rectangles
ACTIV_LAYER = (1, 0)                # Activ.drawing: a MOS gate is GatPoly over Activ
HEAT_TARGET = "Activ"               # stackup layer whose z range holds the heat sources (thermal export)
LVS_MOS_CLASSES = {"nmos": "sg13_lv_nmos", "pmos": "sg13_lv_pmos", "nmosHV": "sg13_hv_nmos", "pmosHV": "sg13_hv_pmos",
                   "rfnmos": "sg13_lv_nmos", "rfpmos": "sg13_lv_pmos", "rfnmosHV": "sg13_hv_nmos",
                   "rfpmosHV": "sg13_hv_pmos"}      # pcell -> device class of IHP's LVS deck (lvs.py)
NO_DEVICES = "no PDK devices (SG13_dev pcells) in the cell"


def devices_in(layout):
    """Why the layout is of this technology, from its devices (anywhere in the layout), or None: a cell of the
    SG13_dev library (also when the library is not loaded) or a static device cell (see _static_name)."""
    for c in layout.each_cell():
        if c.qname().replace("<defunct>", "").startswith(LIBRARY + "."):
            return f"{LIBRARY} cells in the layout"
        name = _static_name(c.name)
        if name is not None and is_device(name):
            return f"static device cells ({c.name}) in the layout"
    return None


def context(layout, stackup):
    """What identify and terminals need, found once per search: the metal pin layers and the TEXT layer."""
    metal_layers = {l.layer for l in stackup.layers if l.is_metal}
    pin_layers = [li for li in layout.layer_indexes()
                  if layout.get_info(li).datatype == PIN_DATATYPE and layout.get_info(li).layer in metal_layers]
    return {"pin_layers": pin_layers, "text_li": layout.find_layer(*TEXT_LAYER)}


def identify(c, ctx):
    """(device name or None, parameters, problem or None) of cell c: a pcell of the PDK library or a static device
    cell. problem names a library cell that cannot be evaluated (PDK library not loaded)."""
    # a library proxy whose library was not bound when the layout was read: <defunct>SG13_dev.npn13G2(...)
    qname = c.qname().replace("<defunct>", "").split("(")[0]
    if qname.startswith(LIBRARY + "."):
        decl = c.pcell_declaration()
        if decl is None:
            return None, {}, qname + " (PDK library not loaded)"
        values = c.pcell_parameters_by_name()
        return decl.name(), {k: values[k] for k in PCELL_PARAMETERS if k in values}, None
    name = _static_name(c.name)
    if name is None:
        return None, {}, None
    # a static device cell: same pins as the pcell, parameters only in its labels
    text_li = ctx["text_li"]
    labels = [] if text_li is None else [s.text.string for s in c.shapes(text_li).each() if s.is_text()]
    if name in RESISTOR_PCELLS:
        return name, ({"label": labels[0]} if labels else {}), None
    for label in labels:
        m = AE_LABEL.search(label)
        if m:
            return name, {"Nx": int(m.group(1)), "Ny": int(m.group(2)), "we": m.group(3) + "u",
                          "le": m.group(4) + "u"}, None
    return name, {}, None


def _static_name(cell_name):
    """The device name of a static device cell: <name>_CDNS_<number> (Cadence), or <name>$<number> / <name> (a pcell
    saved without its pcell context); else None."""
    if STATIC_SUFFIX in cell_name:
        return cell_name.split(STATIC_SUFFIX)[0]
    name = re.sub(r"\$\d+$", "", cell_name)
    return name if is_device(name) else None


def is_device(name):
    return name in DEVICE_PCELLS or name in MOSFET_PCELLS or name in RESISTOR_PCELLS


def is_resistor(name):
    return name in RESISTOR_PCELLS


def terminals(layout, top, c, trans, device, ctx, m1_li, m1, stackup):
    """Fill device.terminals (and device.problems, device.gate_trace) for the device cell c at trans in top."""
    if not device.params and device.pcell not in RESISTOR_PCELLS:
        # a static cell without a parameter label: Create Circuit would put in the model with default size
        device.problems.append("no parameters: a static device cell (no pcell context) without a parameter label "
                               "(npn: 'Ae=Nx*Ny*we*le')")
    if device.pcell in MOSFET_PCELLS:
        _mosfet_terminals(layout, top, c, trans, device, m1_li, m1, stackup)
    elif device.pcell in RESISTOR_PCELLS:
        _resistor_terminals(layout, c, trans, device, ctx["pin_layers"], m1)
    else:
        _named_terminals(layout, c, trans, device, ctx["pin_layers"], ctx["text_li"])


def _size(value):
    """A pcell length for the panel: '0.9u' -> '0.9 µm'; numbers (pcell values in µm) as they are."""
    text = f"{value:g}" if isinstance(value, float) else str(value)
    return text[:-1] + " µm" if text.endswith("u") else text


def _device_shapes(layout, c, layer):
    li = layout.find_layer(*layer)
    return pya.Region() if li is None else pya.Region(c.begin_shapes_rec(li))


def _heat_rule(layout, c, device):
    """The PDK's heat rectangles derived from the device cell's own layers (in the cell), or an empty Region:
    npn: each emitter window grown by 0.05 µm; resistor: its body on PolyRes; nmos/pmos(HV): each gate finger, the
    GatPoly line across Activ with its end caps. Only for the pcells that draw heat shapes in newer PDKs: the rf
    MOSFETs draw none in any version, so there is no PDK rule to follow (they get their bounding box)."""
    if device.pcell.startswith("npn"):
        grow = int(round(EMWIND_HEAT_GROW / layout.dbu))
        return _device_shapes(layout, c, EMWIND_LAYER).sized(grow, grow, 2)
    if device.pcell in RESISTOR_PCELLS:
        return _device_shapes(layout, c, POLYRES_LAYER)
    if device.pcell in MOSFET_PCELLS:
        return _device_shapes(layout, c, (POLY_LAYER, 0)).interacting(_device_shapes(layout, c, ACTIV_LAYER))
    return pya.Region()


def heat_area(layout, device):
    """(Region in the searched cell, how) of the heat a device dissipates. how: 'shapes' (the PDK's heat shapes on
    HEAT_LAYERS), 'rule' (no heat shapes, e.g. a PDK version before them: the same rectangles from the device's own
    layers, _heat_rule) or 'bbox' (neither: the device's bounding box, a larger area and a lower peak temperature)."""
    c = layout.cell(device.cell_index)
    area = pya.Region()
    for layer in HEAT_LAYERS:
        area += _device_shapes(layout, c, layer)
    how = "shapes"
    if area.is_empty():
        area, how = _heat_rule(layout, c, device), "rule"
    if area.is_empty():
        return pya.Region(device.bbox), "bbox"
    return area.transformed(device.trans).merged(), how


def lvs_classes(device):
    """The device classes IHP's KLayout LVS deck extracts for this device (lower case): the pcell name, for a MOSFET
    the base model (the deck maps rfnmos & co. to it)."""
    return {device.pcell.lower(), LVS_MOS_CLASSES.get(device.pcell, device.pcell).lower()}


def lvs_element(device):
    """The SPICE element letter of the device in a schematic netlist that the LVS deck reads."""
    return "M" if device.pcell in LVS_MOS_CLASSES else "R" if device.pcell in RESISTOR_PCELLS else "Q"


def describe(device):
    """The panel's Value column: the device's size, or for a static resistor cell its labelled resistance."""
    p = device.params
    if "label" in p:
        from .ihp_sg13_circuit import label_value
        value = label_value(p["label"])
        return f"{value}Ω" if value else p["label"]
    parts = [f"{k}={p[k]}" for k in ("Nx", "Ny") if k in p and not (k == "Ny" and str(p[k]) == "1")]
    parts += [f"{k} {_size(p[k])}" for k in ("le", "we", "w", "l") if k in p]
    parts += [f"{k}={p[k]}" for k in ("ng", "b") if k in p and str(p[k]) not in ("0", "1")]
    return ", ".join(parts)


def resistor_note(device):
    """Panel text for a resistor that is not replaced: how far off its sheet in the EM model is."""
    low = "a few %" if device.pcell == "rsil" else "about 10 %"     # Palace, tests/resistor_palace
    return (f"sheet resistor of the drawn size in the EM model, R {low} too low (no PDK width offset and contact "
            "end resistance)")


def _named_terminals(layout, c, trans, device, pin_layers, text_li):
    """Named pins: a pin shape on a metal pin layer, named by the TEXT label nearest to its center inside it."""
    labels = []
    if text_li is not None:
        for s in c.shapes(text_li).each():
            if s.is_text():
                labels.append((s.text.string, trans * pya.Point(s.text.x, s.text.y)))
    pins = []
    for li in pin_layers:
        for s in c.shapes(li).each():
            if not s.is_text():
                pins.append((layout.get_info(li).layer, s.bbox().transformed(trans)))
    for layer, box in pins:
        # the label nearest to the pin center (other texts, e.g. the device name, may fall into a pin box too)
        names = [n for n, p in sorted(labels, key=lambda item: item[1].distance(box.center())) if box.contains(p)]
        if not names:
            device.problems.append(f"pin on layer {layer} at {box.to_dtype(layout.dbu)} has no name")
            continue
        device.terminals[names[0]] = (layer, [box])
    if len(device.terminals) < 2:
        device.problems.append("fewer than two named pins")


def _resistor_terminals(layout, c, trans, device, pin_layers, m1):
    """rsil, rppd, rhigh: two Metal1 pins without names, one per contact head. PLUS is the one with the lower
    coordinate along the resistor in the cell's own coordinates (the pcell draws PLUS at the bottom contact area).
    A resistor of several segments has more pins and is not replaced."""
    pins = [s.bbox() for li in pin_layers if layout.get_info(li).layer == m1 for s in c.shapes(li).each()
            if not s.is_text()]
    if len(pins) != 2:
        device.problems.append(f"{len(pins)} Metal1 pins, expected 2 (a resistor of several segments?)")
        return
    a, b = pins
    along_y = abs(a.center().y - b.center().y) >= abs(a.center().x - b.center().x)
    plus, minus = sorted(pins, key=lambda box: box.center().y if along_y else box.center().x)
    device.terminals["PLUS"] = (m1, [plus.transformed(trans)])
    device.terminals["MINUS"] = (m1, [minus.transformed(trans)])


def _mosfet_terminals(layout, top, c, trans, device, m1_li, m1, stackup):
    """nmos/pmos (feasibility tests T3-T5): source and drain are the device's Metal1 strips along the gate fingers,
    alternating S, D, S, ... from the left in the cell's own coordinates (the nmos pins mark only the first finger,
    the pmos has none). The gate pin is poly: the gate port goes on your Metal1 gate contact(s), found by tracing the
    poly from the first gate finger through Cont; that poly and those contacts are removed at the export (their
    resistance belongs to the device side). One port per terminal; several fingers = several elements."""
    strips = [] if m1_li is None else sorted(
        (p.bbox() for p in pya.Region(c.begin_shapes_rec(m1_li)).merged().each() if p.bbox().height() > p.bbox().width()),
        key=lambda b: b.left)
    if len(strips) < 2:
        device.problems.append("fewer than two Metal1 source/drain strips")
        return
    device.terminals["S"] = (m1, [b.transformed(trans) for b in strips[0::2]])
    device.terminals["D"] = (m1, [b.transformed(trans) for b in strips[1::2]])

    cont = next((l.layer for l in stackup.layers if l.name == CONT_NAME), None)
    poly_li = layout.find_layer(POLY_LAYER, 0)
    cont_li = None if cont is None else layout.find_layer(cont, 0)
    poly = [] if poly_li is None else sorted(
        (p.dup() for p in pya.Region(c.begin_shapes_rec(poly_li)).merged().each()), key=lambda p: p.bbox().left)
    if not poly or cont_li is None:
        device.problems.append("no gate poly or no Cont layer")
        return
    start = trans * poly[0].decompose_trapezoids()[0].bbox().center()     # inside the first gate finger
    connectivity = pya.NetTracerConnectivity()
    connectivity.connection(f"{POLY_LAYER}/0", f"{cont}/0")              # stops at Cont: not along your Metal1 wiring
    tracer = pya.NetTracer()
    tracer.trace(connectivity, layout, top, start, poly_li)
    traced = {POLY_LAYER: pya.Region(), cont: pya.Region()}
    for element in tracer.each_element():
        info = layout.get_info(element.layer())
        if info.layer in traced and not element.shape().is_text():
            traced[info.layer].insert(element.shape().polygon.transformed(element.trans()))
    contacts = traced[cont].merged()
    if contacts.is_empty():
        device.problems.append("gate poly has no contact")
        return
    pads = pya.Region(top.begin_shapes_rec_touching(m1_li, contacts.bbox())).merged().interacting(contacts)
    if pads.is_empty():
        device.problems.append("no Metal1 on the gate contacts")
        return
    device.terminals["G"] = (m1, [p.bbox() for p in pads.each()])
    device.gate_trace = {layer: region.merged() for layer, region in traced.items()}
