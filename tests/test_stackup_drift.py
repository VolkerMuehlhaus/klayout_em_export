# Plain Python test (also runs in KLayout batch): the plug-in's stackup z positions against gds2palace's own reader.
# stackup.py is a small parser of its own, because KLayout's Python cannot import gds2palace; this test fails when the
# two disagree, e.g. after a change of the stackup format.
# Environment (optional): GDS2PALACE = the gds2palace repo (see testpaths.py),
#                         GDS2PALACE_READER = path of util_stackup_reader.py,
#                         STACKUP_DIRS = folders with stackup XML files, separated by os.pathsep.
# Defaults: the gds2palace repo, and the sibling repo EMStudio if it is there.
# A layer whose position the plug-in cannot resolve (a variable) is reported, not a failure, if it touches no other
# layer (the reader's orphan layers, e.g. LBE, BACKSIDEGND): Stackup.unresolved() lists it and the panel warns.
# Failures: a layer with a different z than the reader, and an unresolved metal or via that touches other layers.
import contextlib
import glob
import importlib.util
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from klayout_em_export.stackup import Stackup
from testpaths import GDS2PALACE

SIBLINGS = os.path.join(HERE, "..", "..")
TOLERANCE = 1e-3                    # um

reader_path = os.environ.get("GDS2PALACE_READER", os.path.join(
    GDS2PALACE, "workflow", "gds2palace", "util_stackup_reader.py"))
dirs = os.environ.get("STACKUP_DIRS")
dirs = dirs.split(os.pathsep) if dirs else [os.path.join(GDS2PALACE, "XML_stackup"),
                                            os.path.join(SIBLINGS, "EMStudio", "examples")]
if not os.path.isfile(reader_path):
    raise FileNotFoundError(f"No such file: {reader_path} (set GDS2PALACE)")
spec = importlib.util.spec_from_file_location("util_stackup_reader", reader_path)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def stackup_files():
    for folder in dirs:
        for path in sorted(glob.glob(os.path.join(folder, "**", "*.xml"), recursive=True)):
            if os.sep + "build" + os.sep in path:
                continue
            with open(path, errors="ignore") as f:
                if "<Stackup" in f.read(4000):
                    yield path


def compare(path):
    """(problems, unresolved layer names, number of layers compared) of one file."""
    plug = Stackup(path)
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            _, _, metals = reader.read_substrate(path)
        except SystemExit:
            return None, [], 0                  # the reader rejects the file: nothing to compare with
    ref = {m.name: (m.zmin, m.zmax) for m in metals.metals}
    orphans = {getattr(m, "name", m) for m in metals.orphan_layers}    # touch no other layer: never wiring
    groups = {}                                 # anchor -> [(name, plug zmin, zmax, reader zmin, zmax)]
    unresolved = []
    for layer in plug.layers:
        if layer.name not in ref:
            continue
        z = plug.z_range(layer)
        if z is None:
            unresolved.append(layer.name)
            continue
        groups.setdefault(z[0], []).append((layer.name, z[1], z[2], *ref[layer.name]))
    problems = []
    for anchor, rows in groups.items():
        # the "bottom" anchor is the stackup's absolute z; a variable thickness starts an anchor of its own, where
        # only heights relative to the first layer are comparable
        shift_plug, shift_ref = (0.0, 0.0) if anchor == "bottom" else (rows[0][1], rows[0][3])
        for name, pmin, pmax, rmin, rmax in rows:
            if abs((pmin - shift_plug) - (rmin - shift_ref)) > TOLERANCE or \
                    abs((pmax - shift_plug) - (rmax - shift_ref)) > TOLERANCE:
                problems.append(f"{name}: plug-in z {pmin:.3f}..{pmax:.3f}, reader {rmin:.3f}..{rmax:.3f}"
                                f" (anchor {anchor})")
    # every unresolved metal or via must be reported by Stackup.unresolved(): that is what the panel shows
    missing = [n for n in unresolved if plug.layer(n).kind in ("conductor", "sheet", "via")
               and plug.layer(n).layer not in plug.derived and n not in plug.unresolved()]
    problems += [f"{n}: unresolved but not reported by Stackup.unresolved()" for n in missing]
    # an unresolved metal or via that touches another layer may be wiring: nets and ground would be incomplete
    problems += [f"{n}: unresolved, but it touches other layers (wiring?)" for n in plug.unresolved()
                 if n in ref and n not in orphans]
    return problems, unresolved, sum(len(rows) for rows in groups.values())


failed, count = 0, 0
for path in stackup_files():
    count += 1
    problems, unresolved, compared = compare(path)
    name = os.path.relpath(path, SIBLINGS)
    if problems is None:
        print(f"skip  {name}: rejected by the gds2palace reader")
    elif problems:
        failed += 1
        print(f"FAIL  {name}")
        for p in problems:
            print("        " + p)
    else:
        note = f", not resolved by the plug-in: {', '.join(unresolved)}" if unresolved else ""
        print(f"ok    {name} ({compared} layers{note})")
print(f"{count} stackup file(s), {failed} failed")
if count == 0:
    sys.exit("no stackup files found; set STACKUP_DIRS")
sys.exit(1 if failed else 0)
