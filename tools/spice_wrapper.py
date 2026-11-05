"""Circuit wrapper for an EM export with replaced devices: the EM model plus the PDK device models at the ports that
replaced them, as a subcircuit for ngspice, VACASK, Xyce or Spectre.

    python tools/spice_wrapper.py <export>_portmap.json <model>.sNp [-o <file>]
        [--simulator ngspice|vacask|xyce|spectre] [--em fit|snp] [--pdk <PDK folder, e.g. IHP-Open-PDK/ihp-sg13g2>]

The EM model goes in either way:
  fit   a lumped-element equivalent circuit made by snp2le (universal mode: vector fitted, passive), written next to
        the output as <name>_le.cir (ngspice, Xyce) or <name>_le.inc (VACASK). Needs a Python with snp2le
       . ngspice and VACASK can only use this.
  snp   the .sNp file itself, read by the simulator: Xyce (YLIN element) and Spectre (nport element).
Default: fit for ngspice and VACASK, snp for Xyce and Spectre.

Use the gds2palace result with its DC point (<model>_dc.sNp, from a sweep started at 0 Hz: gds2palace then simulates
10 MHz and 20 MHz and extrapolates 0 Hz from them); snp2le pins the equivalent circuit to that point.

The subcircuit's pins are the ports that belong to no device (pads, bias inputs, ...). Each device terminal is wired
straight to its port's pin of the EM model. In the EM model a device's ports end on the device's own floating
REF_FOR_TRANSISTOR patch, while the EM model references every port to ground: wiring the device directly grounds that
patch. This adds the patch's capacitance (a few fF per transistor) and changes the result slightly (cascode test:
S21 0.06 dB at 10 GHz, 0.4 dB at 200 GHz), against a much simpler netlist.

The export sets each via port's direction so that every via port has its signal metal on the same end (port map:
direction, signal_layer); a port map without them is from an older export, whose ports may be reversed: export again.

DC paths: a port measures a voltage difference, so the EM model does not fix the absolute potential of a device
whose ports end on its floating REF patch. The port map names each port's net (traced through the layout's vias at
the export); ports on one net are tied together, and to ground on the ground net, by 1 mH inductors: a short at DC,
open at GHz. The wires' DC resistance is not modelled. Without a 0 Hz point in the .sNp the EM model's DC is a guess
(it leaks tens of kOhm between nets): then every port also gets a 1 uF DC block, which keeps the EM model out of the
DC solution. The device's substrate/bulk pin, not part of the EM model, goes to ground (nmos, npn, resistors) or to
the source (pmos).

Model libraries (with --pdk, active lines, else commented): ngspice and Xyce from the PDK's libs.tech/ngspice or
libs.tech/xyce; VACASK includes the PDK's libraries by name, found through the PDK's .vacaskrc.toml (copy it next to
the testbench); Spectre gets commented include lines to adapt to your PDK.

The device models, their terminal order and the model libraries come from the technology named in the port map
(python/klayout_em_export/tech/<technology>_circuit.py; port maps without it are IHP SG13G2/SG13CMOS5L).
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from klayout_em_export import tech as technologies               # noqa: E402  (plain Python, no pya)


EM_DEFAULT = {"ngspice": "fit", "vacask": "fit", "xyce": "snp", "spectre": "snp"}
EM_ALLOWED = {"ngspice": ("fit",), "vacask": ("fit",), "xyce": ("snp", "fit"), "spectre": ("snp",)}
EXTENSION = {"ngspice": ".cir", "vacask": ".inc", "xyce": ".cir", "spectre": ".scs"}
VACASK_PRIMITIVES = ("resistor", "capacitor", "inductor", "vsource", "vccs", "cccs", "vcvs", "ccvs")
VACASK_MODULES = ("resistor", "capacitor", "inductor")      # loaded from VACASK's modules, the others are built in


def has_dc_point(snp):
    """True if the Touchstone file's first frequency is 0 Hz."""
    for line in open(snp):
        line = line.split("!")[0].strip()
        if line and not line.startswith("#") and not line.startswith("["):
            return float(line.split()[0]) == 0.0
    return False


def touchstone_ports(snp):
    m = re.search(r"\.s(\d+)p$", snp.lower())
    return int(m.group(1)) if m else None


def equivalent_circuit(snp, out, fmt):
    """Run snp2le (universal mode) and return (subcircuit name, pin count) of the equivalent circuit it wrote."""
    result = subprocess.run([sys.executable, "-m", "snp2le", "-b", "convert", snp, "--mode", "universal",
                             "--format", fmt, "-o", out], capture_output=True, text=True)
    report = [l for l in (result.stdout + result.stderr).splitlines() if "[" in l or "note" in l]
    print("\n".join(report))
    if result.returncode != 0 or not os.path.isfile(out):
        sys.exit(f"snp2le failed:\n{result.stdout}\n{result.stderr}")
    for line in open(out):
        words = line.replace("(", " ( ").split()
        if words and words[0].lower() in (".subckt", "subckt"):
            pins = [w for w in words[2:] if w not in "()"]
            return words[1], len(pins)
    sys.exit(f"no subcircuit in {out}")


def vacask_private_models(path):
    """Rename the primitive models of snp2le's VACASK model to em_<type> (declared by the wrapper, so they cannot
    clash with the testbench's own declarations), and its ground GND to 0 (ground inside VACASK subcircuits)."""
    text = open(path).read()
    text = re.sub(r"^(\s*\S+\s*\([^)]*\)\s*)(" + "|".join(VACASK_PRIMITIVES) + r")\b", r"\1em_\2", text, flags=re.M)
    text = re.sub(r"\bGND\b", "0", text)
    open(path, "w").write(text)
    used = sorted(set(re.findall(r"\bem_(" + "|".join(VACASK_PRIMITIVES) + r")\b", text)))
    return used


def xyce_compatible(path):
    """snp2le's ngspice model marks its resistors noisy=0, which Xyce does not know: remove it (Xyce then adds those
    resistors' thermal noise, so the model is not noiseless in a noise analysis)."""
    text = open(path).read()
    open(path, "w").write(re.sub(r"\s+noisy=0\b", "", text, flags=re.I))


class Circuit:
    """The wrapper independent of the simulator: pins, the EM model's pin nodes and the elements around it."""

    def __init__(self, name):
        self.name = name
        self.pins = []              # subcircuit pins (external ports)
        self.em_nodes = []          # node at each pin of the EM model, in port order
        # ("comment", text) | ("device", name, model, [nodes], {params}) | (R|L|C, name, a, b, value)
        self.items = []
        self.kinds = set()          # PDK library kinds used (hbt, mos, ...)
        self.tech = None            # the technology's circuit module (tech/<technology>_circuit.py)
        self.notes = []
        self.header = []            # (port number, layout port) of the pins


def build(portmap, em_pins, dc_blocks, name):
    """Circuit from the port map. em_pins: the EM model's pin count (= simulated ports)."""
    ports = {r["port"]: r for r in portmap["ports"] if r["in_simcfg"]}
    if len(ports) != em_pins:
        sys.exit(f"the port map has {len(ports)} simulated ports, the EM model {em_pins} pins")
    c = Circuit(name)
    try:
        c.tech = tech = technologies.load_circuit(portmap.get("technology") or technologies.PORTMAP_DEFAULT)
    except ValueError as e:
        sys.exit(f"port map: {e}")
    node = {n: (f"n{n}" if "device" in r else f"port{n}") for n, r in ports.items()}
    c.pins = [node[n] for n in sorted(ports) if "device" not in ports[n]]
    c.header = [(node[n], n, ports[n]["layout_port"]) for n in sorted(ports) if "device" not in ports[n]]
    if any(r["settings"] and "signal_layer" not in r for r in ports.values()):
        c.notes.append("the port map has no signal layers (older export): via ports may be reversed, export again")
    terminals = {}                              # device id -> {terminal: node}
    for n, r in ports.items():
        if "device" in r:
            terminals.setdefault(r["device"], {})[r["terminal"]] = node[n]

    for k, (device_id, term) in enumerate(sorted(terminals.items()), start=1):
        info = portmap.get("devices", {}).get(device_id, {})
        pcell = info.get("pcell") or tech.pcell_of(device_id)
        ports_of = ", ".join(f"{r['terminal']} port {n}" for n, r in sorted(ports.items())
                             if r.get("device") == device_id)
        c.items.append(("comment", f"{pcell} {device_id} ({ports_of})"))
        items, notes, kind = tech.instantiate(k, device_id, pcell, info.get("params", {}), term)
        c.items += items
        c.notes += notes
        if kind is not None:
            c.kinds.add(kind)

    # DC paths of the wiring: 1 mH between the ports of one net, to ground on the ground net
    nets = {}
    for n, r in ports.items():
        if r.get("net") is not None:
            nets.setdefault((r["net"], r.get("ground_net", False)), []).append(node[n])
    c.items.append(("comment", "DC paths of the wiring (open at RF)"))
    for (net, ground), members in sorted(nets.items()):
        chain = (["0"] if ground else []) + members
        c.items += [("L", f"Ldc{net}_{i}", a, b, "1m") for i, (a, b) in enumerate(zip(chain, chain[1:]))]
    if not nets:
        c.notes.append("the port map has no nets: no DC paths, the devices get no defined bias (export again)")

    if dc_blocks:
        c.notes.append("no 0 Hz point in the .sNp: the EM model is connected through 1 uF DC blocks")
        c.em_nodes = [f"e{n}" for n in sorted(ports)]
        c.items += [("C", f"Cdc{n}", node[n], f"e{n}", "1u") for n in sorted(ports)]
    else:
        c.em_nodes = [node[n] for n in sorted(ports)]
    return c


def write_spice(c, simulator, em, em_file, em_name, pdk):
    """ngspice or Xyce netlist."""
    out = [f"* {c.name}: EM model with PDK devices for {simulator}, "
           "generated by klayout_em_export tools/spice_wrapper.py",
           "* pins: " + ", ".join(f"{node} = export port {n} (layout port {lp})" for node, n, lp in c.header)]
    if em == "fit":
        out += ["* the EM model's equivalent circuit (snp2le):", f".include {os.path.basename(em_file)}"]
    else:
        out += ["* the EM model: its S-parameters, read by Xyce's YLIN element",
                f".model {c.name}_em LIN TSTONEFILE={em_file}"]
    out.append(f"* PDK model libraries ({simulator}):")
    for kind in sorted(c.kinds):
        lib, section = c.tech.LIBRARIES[kind]
        out.append(("" if pdk else "* ") + f".lib {c.tech.lib_path(pdk, simulator, lib)} {section}")
    out += [f"* notes: {n}" for n in c.notes]
    out += ["", f".subckt {c.name} {' '.join(c.pins)}"]
    if em == "fit":
        out.append(f"XEM {' '.join(c.em_nodes)} {em_name}")
    else:
        out.append(f"YLIN YEM {' '.join(f'{n} 0' for n in c.em_nodes)} {c.name}_em")
    for item in c.items:
        if item[0] == "comment":
            out.append(f"* {item[1]}")
        elif item[0] == "device":
            _, inst, model, nodes, params = item
            out.append(f"{inst} {' '.join(nodes)} {model} " + " ".join(f"{k}={v}" for k, v in params.items()))
        else:
            out.append(f"{item[1]} {item[2]} {item[3]} {item[4]}")
    out += [f".ends {c.name}", ""]
    return "\n".join(out)


def write_spectre(c, em_file):
    """Spectre netlist: the .sNp through an nport element; the PDK includes are left to the user."""
    out = ["simulator lang=spectre",
           f"// {c.name}: EM model with PDK devices for Spectre, generated by klayout_em_export tools/spice_wrapper.py",
           "// pins: " + ", ".join(f"{node} = export port {n} (layout port {lp})" for node, n, lp in c.header),
           f"// {c.tech.SPECTRE_NOTE}"]
    for kind in sorted(c.kinds):
        lib, section = c.tech.LIBRARIES[kind]
        out.append(f'// include "<your PDK>/{lib}" section={section}')
    out += [f"// notes: {n}" for n in c.notes]
    out += ["", f"subckt {c.name} ({' '.join(c.pins)})",
            f"  EM ({' '.join(f'{n} 0' for n in c.em_nodes)}) nport file=\"{em_file}\""]
    names = {"R": ("resistor", "r"), "L": ("inductor", "l"), "C": ("capacitor", "c")}
    for item in c.items:
        if item[0] == "comment":
            out.append(f"  // {item[1]}")
        elif item[0] == "device":
            _, inst, model, nodes, params = item
            out.append(f"  {inst} ({' '.join(nodes)}) {model} " + " ".join(f"{k}={v}" for k, v in params.items()))
        else:
            master, param = names[item[0]]
            out.append(f"  {item[1]} ({item[2]} {item[3]}) {master} {param}={item[4]}")
    out += [f"ends {c.name}", ""]
    return "\n".join(out)


def write_vacask(c, em_file, em_name, primitives):
    """VACASK netlist: snp2le's VACASK model, the PDK's VACASK libraries (by name, through .vacaskrc.toml)."""
    out = [f"// {c.name}: EM model with PDK devices for VACASK, generated by klayout_em_export tools/spice_wrapper.py",
           "// pins: " + ", ".join(f"{node} = export port {n} (layout port {lp})" for node, n, lp in c.header),
           *[f"// {line}" if not line.startswith("include") else line for line in c.tech.VACASK_HEADER]]
    for kind in sorted(c.kinds):
        lib, section = c.tech.LIBRARIES[kind]
        out.append(f'include "{lib}" section={section}')
    out.append("// primitives of the EM model and of this wrapper, under names of their own")
    used = set(primitives) | {"resistor", "inductor", "capacitor"}
    out += [f'load "{p}.osdi"' for p in sorted(used & set(VACASK_MODULES))]   # VACASK's module path
    out += [f"model em_{p} {p}" for p in sorted(used)]
    out += [f"// notes: {n}" for n in c.notes]
    out += [f'include "{os.path.basename(em_file)}"', "", f"subckt {c.name}({' '.join(c.pins)})",
            f"  em ({' '.join(c.em_nodes)}) {em_name}"]
    names = {"R": ("em_resistor", "r"), "L": ("em_inductor", "l"), "C": ("em_capacitor", "c")}
    for item in c.items:
        if item[0] == "comment":
            out.append(f"  // {item[1]}")
        elif item[0] == "device":
            _, inst, model, nodes, params = item
            # the PDK's VACASK subcircuits name their parameters in lower case (nx, ny), and have no 'b'
            values = " ".join(f"{k.lower()}={v}" for k, v in params.items() if k != "b")
            out.append(f"  {inst.lower()} ({' '.join(nodes)}) {model} {values}")
        else:
            master, param = names[item[0]]
            out.append(f"  {item[1].lower()} ({item[2]} {item[3]}) {master} {param}={item[4]}")
    out += ["ends", ""]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("portmap")
    parser.add_argument("snp", help="the EM result, preferably <model>_dc.sNp (with its 0 Hz point)")
    parser.add_argument("-o", "--output", help="wrapper file (default: <snp name>_<simulator>.<ext> next to the .snp)")
    parser.add_argument("--simulator", choices=sorted(EM_DEFAULT), default="ngspice")
    parser.add_argument("--em", choices=("fit", "snp"), help="EM model: snp2le equivalent circuit or the .sNp file")
    parser.add_argument("--pdk", help="PDK folder (IHP: the ihp-sg13g2 or ihp-sg13cmos5l folder of IHP-Open-PDK): "
                                       "active .lib lines (ngspice, Xyce)")
    args = parser.parse_args()
    sim = args.simulator
    em = args.em or EM_DEFAULT[sim]
    if em not in EM_ALLOWED[sim]:
        sys.exit(f"{sim} cannot use the EM model as '{em}' (possible: {', '.join(EM_ALLOWED[sim])})")
    out = args.output or os.path.splitext(args.snp)[0] + f"_{sim}" + EXTENSION[sim]
    name = re.sub(r"\W", "_", os.path.splitext(os.path.basename(out))[0])
    portmap = json.load(open(args.portmap))
    dc_blocks = not has_dc_point(args.snp)
    folder = os.path.dirname(os.path.abspath(out))
    if em == "fit":
        fmt = "vacask" if sim == "vacask" else "ngspice"
        em_file = os.path.join(folder, name + ("_le.inc" if sim == "vacask" else "_le.cir"))
        em_name, em_pins = equivalent_circuit(args.snp, em_file, fmt)
        if sim == "xyce":
            xyce_compatible(em_file)
    else:
        em_file, em_name, em_pins = os.path.abspath(args.snp).replace("\\", "/"), None, touchstone_ports(args.snp)
    c = build(portmap, em_pins, dc_blocks, name)
    if sim == "vacask":
        text = write_vacask(c, em_file, em_name, vacask_private_models(em_file))
    elif sim == "spectre":
        text = write_spectre(c, em_file)
    else:
        text = write_spice(c, sim, em, em_file, em_name, args.pdk)
    open(out, "w").write(text)
    print("wrote", out, "and", em_file if em == "fit" else f"(uses {em_file})")


if __name__ == "__main__":
    main()
