"""IHP SG13G2 in the circuit wrapper (tools/spice_wrapper.py): the PDK model of each device, its terminals' order
and the model libraries of IHP-Open-PDK. Plain Python: the wrapper runs outside KLayout.
"""
import os
import re

NAME = "ihp_sg13g2"
PDK_LABEL = "IHP PDK"
PDK_HINT = "Optional: the ihp-sg13g2 folder of IHP-Open-PDK, for the model library paths."
PDK_BROWSE_TITLE = "IHP-Open-PDK ihp-sg13g2 folder"
PDK_HELP = "IHP-Open-PDK ihp-sg13g2 folder: active .lib lines (ngspice, Xyce)"
STATIC_SUFFIX = "_CDNS_"            # a device cell exported from Cadence: <pcell name>_CDNS_<number>

# pcell -> (subcircuit or None for the pcell's 'model' parameter, kind)
DEVICES = {
    "npn13G2": ("npn13G2", "hbt"), "npn13G2L": ("npn13G2l", "hbt"), "npn13G2V": ("npn13G2v", "hbt"),
    "nmos": (None, "mos"), "pmos": (None, "mos"), "nmosHV": (None, "moshv"), "pmosHV": (None, "moshv"),
    "rfnmos": (None, "mos"), "rfpmos": (None, "mos"), "rfnmosHV": (None, "moshv"), "rfpmosHV": (None, "moshv"),
    "rsil": ("rsil", "res"), "rppd": ("rppd", "res"), "rhigh": ("rhigh", "res"),
}
LIBRARIES = {"hbt": ("cornerHBT.lib", "hbt_typ"), "mos": ("cornerMOSlv.lib", "mos_tt"),
             "moshv": ("cornerMOShv.lib", "mos_tt"), "res": ("cornerRES.lib", "res_typ")}
PARAMS = {"hbt": ("Nx", "Ny", "le", "we"), "mos": ("w", "l", "ng"), "moshv": ("w", "l", "ng"), "res": ("w", "l", "b")}
SPECTRE_NOTE = "PDK model libraries: include those of your SG13G2 PDK installation, for example"
VACASK_HEADER = ("needs the IHP PDK converted for VACASK and its .vacaskrc.toml (next to the testbench or in your home)",
                 'include "sg13g2_vacask_common.lib"')


def pcell_of(device_id):
    """Device type from a device id (<cell name>@x,y) when the port map does not name it."""
    return device_id.split("@")[0].split(STATIC_SUFFIX)[0].split("$")[0]


def lib_path(pdk, simulator, lib):
    if not pdk:
        return f"<IHP-Open-PDK>/ihp-sg13g2/libs.tech/{simulator}/models/{lib}"
    return os.path.join(pdk, "libs.tech", simulator, "models", lib).replace("\\", "/")


def label_value(label):
    """Resistance from a static resistor cell's label, e.g. 'rhigh r=2.997k' -> '2.997k'."""
    m = re.search(r"r\s*=\s*([0-9.]+\s*[a-zA-Z]*)", label or "")
    return m.group(1).replace(" ", "") if m else None


def instantiate(k, device_id, pcell, params, term):
    """(items, notes, library kind or None) of one device: the wrapper's items (see spice_wrapper.Circuit) that put
    the device's PDK model between its terminal nodes term {terminal: node}. k numbers the instance."""
    subckt, kind = DEVICES.get(pcell, (None, None))
    if kind is None:
        return ([("comment", "  not instantiated: unknown device type")],
                [f"{device_id}: unknown device type {pcell}, not instantiated"], None)
    if kind == "res" and not any(p in params for p in ("w", "l")):
        value = label_value(params.get("label"))
        if value is None:
            return ([("comment", "  not instantiated: no parameters, no value label")],
                    [f"{device_id}: no parameters and no value label, not instantiated"], None)
        # a static cell from Cadence has no pcell parameters: an ideal resistor of the labelled value
        return ([("comment", f"  static cell without parameters: ideal resistor from its label '{params.get('label')}'"),
                 ("R", f"R{k}", term["PLUS"], term["MINUS"], value)],
                [f"{device_id}: ideal resistor {value} (from its label; no temperature, no parasitics)"], None)
    values = {p: params[p] for p in PARAMS[kind] if p in params and params[p] not in ("", "None")}
    notes = []
    if kind == "hbt":
        item = ("device", f"X{k}", subckt, [term["C"], term["B"], term["E"], "0"], values)
    elif kind in ("mos", "moshv"):
        model = params.get("model") or ("sg13_lv_pmos" if "p" in pcell else "sg13_lv_nmos")
        bulk = term.get("TIE") or (term["S"] if "pmos" in pcell else "0")
        item = ("device", f"X{k}", model, [term["D"], term["G"], term["S"], bulk], values)
        if "TIE" not in term:
            notes.append(f"{device_id}: bulk to {'its source' if 'pmos' in pcell else 'ground'} (no bulk port)")
    else:
        item = ("device", f"X{k}", subckt, [term["PLUS"], term["MINUS"], "0"], values)
    return [item], notes, kind
