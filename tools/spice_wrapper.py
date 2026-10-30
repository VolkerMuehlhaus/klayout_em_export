"""ngspice circuit wrapper for an EM export with replaced devices: the EM model as a lumped-element equivalent
circuit (snp2le, vector fitted, passive) plus the PDK device models at the ports that replaced them.

    python tools/spice_wrapper.py <export>_portmap.json <model>.sNp [-o wrapper.cir] [--pdk <IHP-Open-PDK/ihp-sg13g2>]

Run it in a Python with snp2le (e.g. d:\\venv\\palace). Use the gds2palace result with its DC point (<model>_dc.sNp,
from a sweep started at 0 Hz: gds2palace then simulates 10 MHz and 20 MHz and extrapolates 0 Hz from them); snp2le
pins the equivalent circuit to that point. It writes, next to the output:
  <name>_le.cir        the EM model's equivalent circuit (snp2le universal mode), subcircuit with one pin per port
  <name>.cir           subcircuit <name> whose pins are the ports that belong to no device (pads, bias inputs, ...),
                       the EM model and one PDK device instance per replaced device

Each device terminal is wired straight to its port's pin of the equivalent circuit. In the EM model a device's ports
end on the device's own floating REF_FOR_TRANSISTOR patch, while the equivalent circuit references every port to
ground: wiring the device directly grounds that patch. This adds the patch's capacitance (a few fF per transistor) and
changes the result slightly (cascode test: S21 0.06 dB at 10 GHz, 0.4 dB at 200 GHz), against a much simpler netlist.

The export sets each via port's direction so that the signal metal is the positive terminal (port map: direction,
signal_layer); a port map without them is from an older export, whose ports may be reversed: export again.

DC paths: a port measures a voltage difference, so the EM model does not fix the absolute potential of a device
whose ports end on its floating REF patch. The port map names each port's net (traced through the layout's vias at
the export); ports on one net are tied together, and to ground on the ground net, by 1 mH inductors: a short at DC,
open at GHz. The wires' DC resistance is not modelled. Without a 0 Hz point in the .sNp the equivalent circuit's DC
is a guess of the fit (it leaks tens of kOhm between nets): then every port also gets a 1 uF DC block, which keeps
the equivalent circuit out of the DC solution. The device's substrate/bulk pin, not part of the EM model, goes to
ground (nmos, npn, resistors) or to the source (pmos).
"""
import argparse
import json
import os
import re
import subprocess
import sys

# pcell -> (ngspice subcircuit or None for the pcell's 'model' parameter, kind)
DEVICES = {
    "npn13G2": ("npn13G2", "hbt"), "npn13G2L": ("npn13G2l", "hbt"), "npn13G2V": ("npn13G2v", "hbt"),
    "nmos": (None, "mos"), "pmos": (None, "mos"), "nmosHV": (None, "moshv"), "pmosHV": (None, "moshv"),
    "rfnmos": (None, "mos"), "rfpmos": (None, "mos"), "rfnmosHV": (None, "moshv"), "rfpmosHV": (None, "moshv"),
    "rsil": ("rsil", "res"), "rppd": ("rppd", "res"), "rhigh": ("rhigh", "res"),
}
LIBRARIES = {"hbt": ("cornerHBT.lib", "hbt_typ"), "mos": ("cornerMOSlv.lib", "mos_tt"),
             "moshv": ("cornerMOShv.lib", "mos_tt"), "res": ("cornerRES.lib", "res_typ")}
PARAMS = {"hbt": ("Nx", "Ny", "le", "we"), "mos": ("w", "l", "ng"), "moshv": ("w", "l", "ng"), "res": ("w", "l", "b")}


def has_dc_point(snp):
    """True if the Touchstone file's first frequency is 0 Hz."""
    for line in open(snp):
        line = line.split("!")[0].strip()
        if line and not line.startswith("#") and not line.startswith("["):
            return float(line.split()[0]) == 0.0
    return False


def equivalent_circuit(snp, out):
    """Run snp2le (universal mode) and return the subcircuit name of the equivalent circuit it wrote."""
    result = subprocess.run([sys.executable, "-m", "snp2le", "-b", "convert", snp, "--mode", "universal", "-o", out],
                            capture_output=True, text=True)
    report = [l for l in (result.stdout + result.stderr).splitlines() if "[" in l or "note" in l]
    print("\n".join(report))
    if result.returncode != 0 or not os.path.isfile(out):
        sys.exit(f"snp2le failed:\n{result.stdout}\n{result.stderr}")
    for line in open(out):
        if line.upper().startswith(".SUBCKT"):
            return line.split()[1], len(line.split()) - 2
    sys.exit(f"no .SUBCKT in {out}")


def label_value(label):
    """Resistance from a static resistor cell's label, e.g. 'rhigh r=2.997k' -> '2.997k'."""
    m = re.search(r"r\s*=\s*([0-9.]+\s*[a-zA-Z]*)", label or "")
    return m.group(1).replace(" ", "") if m else None


def wrapper(portmap, le_name, le_pins, le_file, name, pdk, dc_blocks):
    ports = {r["port"]: r for r in portmap["ports"] if r["in_simcfg"]}
    if len(ports) != le_pins:
        sys.exit(f"the port map has {len(ports)} simulated ports, the equivalent circuit {le_pins} pins")
    node = {n: (f"n{n}" if "device" in r else f"port{n}") for n, r in ports.items()}
    external = [n for n in sorted(ports) if "device" not in ports[n]]
    terminals = {}                              # device id -> {terminal: node}
    for n, r in ports.items():
        if "device" in r:
            terminals.setdefault(r["device"], {})[r["terminal"]] = node[n]

    lines, kinds, notes = [], set(), []
    if any(r["settings"] and "signal_layer" not in r for r in ports.values()):
        notes.append("the port map has no signal layers (older export): via ports may be reversed, export again")
    for k, (device_id, term) in enumerate(sorted(terminals.items()), start=1):
        info = portmap.get("devices", {}).get(device_id, {})
        pcell = info.get("pcell") or device_id.split("@")[0].split("_CDNS_")[0].split("$")[0]
        params = info.get("params", {})
        subckt, kind = DEVICES.get(pcell, (None, None))
        ports_of = ", ".join(f"{t} port {n}" for n, r in sorted(ports.items()) if r.get("device") == device_id
                             for t in [r["terminal"]])
        lines.append(f"* {pcell} {device_id} ({ports_of})")
        if kind is None:
            notes.append(f"{device_id}: unknown device type {pcell}, not instantiated")
            lines.append("*   not instantiated: unknown device type")
            continue
        if kind == "res" and not any(p in params for p in ("w", "l")):
            value = label_value(params.get("label"))
            if value is None:
                notes.append(f"{device_id}: no parameters and no value label, not instantiated")
                lines.append("*   not instantiated: no parameters, no value label")
                continue
            # a static cell from Cadence has no pcell parameters: an ideal resistor of the labelled value
            lines.append(f"*   static cell without parameters: ideal resistor from its label '{params.get('label')}'")
            lines.append(f"R{k} {term['PLUS']} {term['MINUS']} {value}")
            notes.append(f"{device_id}: ideal resistor {value} (from its label; no temperature, no parasitics)")
            continue
        kinds.add(kind)
        values = " ".join(f"{p}={params[p]}" for p in PARAMS[kind] if p in params and params[p] not in ("", "None"))
        if kind == "hbt":
            lines.append(f"X{k} {term['C']} {term['B']} {term['E']} 0 {subckt} {values}")
        elif kind in ("mos", "moshv"):
            model = params.get("model") or ("sg13_lv_pmos" if "p" in pcell else "sg13_lv_nmos")
            bulk = term.get("TIE") or (term["S"] if "pmos" in pcell else "0")
            lines.append(f"X{k} {term['D']} {term['G']} {term['S']} {bulk} {model} {values}")
            if "TIE" not in term:
                notes.append(f"{device_id}: bulk to {'its source' if 'pmos' in pcell else 'ground'} (no bulk port)")
        else:
            lines.append(f"X{k} {term['PLUS']} {term['MINUS']} 0 {subckt} {values}")

    # DC paths of the wiring: 1 mH between the ports of one net, to ground on the ground net
    nets = {}
    for n, r in ports.items():
        if r.get("net") is not None:
            nets.setdefault((r["net"], r.get("ground_net", False)), []).append(node[n])
    dc = []
    for (net, ground), members in sorted(nets.items()):
        chain = (["0"] if ground else []) + members
        dc += [f"Ldc{net}_{i} {a} {b} 1m" for i, (a, b) in enumerate(zip(chain, chain[1:]))]
    if not nets:
        notes.append("the port map has no nets: no DC paths, the devices get no defined bias (export again)")
    lines += ["* DC paths of the wiring (open at RF)"] + dc

    if dc_blocks:
        notes.append("no 0 Hz point in the .sNp: the equivalent circuit is connected through 1 uF DC blocks")
        em = [f"XEM {' '.join(f'e{n}' for n in sorted(ports))} {le_name}"]
        em += [f"Cdc{n} {node[n]} e{n} 1u" for n in sorted(ports)]
    else:
        em = [f"XEM {' '.join(node[n] for n in sorted(ports))} {le_name}"]
    head = [f"* {name}: EM model with PDK devices, generated by klayout_em_export tools/spice_wrapper.py",
            f"* pins: " + ", ".join(f"{node[n]} = export port {n} (layout port {ports[n]['layout_port']})"
                                   for n in external),
            "* include the EM model's equivalent circuit and the PDK model libraries (ngspice):",
            f".include {os.path.basename(le_file)}"]
    for kind in sorted(kinds):
        lib, section = LIBRARIES[kind]
        path = os.path.join(pdk, "libs.tech", "ngspice", "models", lib).replace("\\", "/") if pdk else \
            f"<IHP-Open-PDK>/ihp-sg13g2/libs.tech/ngspice/models/{lib}"
        head.append(("" if pdk else "* ") + f".lib {path} {section}")
    head += [f"* notes: {n}" for n in notes]
    return "\n".join(head + ["", f".subckt {name} {' '.join(node[n] for n in external)}"] + em + lines +
                     [f".ends {name}", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("portmap")
    parser.add_argument("snp", help="the EM result, preferably <model>_dc.sNp (with its 0 Hz point)")
    parser.add_argument("-o", "--output", help="wrapper file (default: <snp name>_wrapper.cir next to the .snp)")
    parser.add_argument("--pdk", help="IHP-Open-PDK ihp-sg13g2 folder: writes active .lib lines")
    args = parser.parse_args()
    out = args.output or os.path.splitext(args.snp)[0] + "_wrapper.cir"
    name = re.sub(r"\W", "_", os.path.splitext(os.path.basename(out))[0])
    le_file = os.path.join(os.path.dirname(os.path.abspath(out)), name + "_le.cir")
    le_name, le_pins = equivalent_circuit(args.snp, le_file)
    text = wrapper(json.load(open(args.portmap)), le_name, le_pins, le_file, name, args.pdk,
                   dc_blocks=not has_dc_point(args.snp))
    open(out, "w").write(text)
    print("wrote", out, "and", le_file)


if __name__ == "__main__":
    main()
