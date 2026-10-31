# Batch test (KLayout -z -nc -rx -r): Create Circuit without the dialog - default output names, the Python next to
# setupEM, and tools/spice_wrapper.py run from KLayout for each simulator. Environment: PORTMAP, SNP (the cascode's
# port map and _dc.sNp), PYTHON (a Python with snp2le), OUT (output folder).
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from klayout_em_export import circuit

portmap, snp, python, out = (os.environ[k] for k in ("PORTMAP", "SNP", "PYTHON", "OUT"))
os.makedirs(out, exist_ok=True)
failed = []


def check(ok, text):
    print(("ok    " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


check(os.path.isfile(circuit.WRAPPER), f"wrapper found: {circuit.WRAPPER}")
check(circuit.default_output("a/b_dc.s15p", "xyce", "snp") == "a/b_dc_xyce_snp.cir", "default output name")
setupem = os.path.join(os.path.dirname(python), "setupEM.exe" if os.name == "nt" else "setupEM")
check(circuit.default_python({"setupEM": setupem}) == python, "the Python next to setupEM is the default")
for label, simulator, em in circuit.CHOICES:
    target = os.path.join(out, os.path.basename(circuit.default_output(snp, simulator, em)))
    ok, report = circuit.run_wrapper(python, portmap, snp, target, simulator, em, "")
    check(ok, f"{label}: {os.path.basename(target)}")
    if not ok:
        print(report)
ok, report = circuit.run_wrapper(python, portmap, snp + ".missing", os.path.join(out, "x.cir"), "ngspice", "fit", "")
check(not ok and report, "a missing .sNp gives an error report")
print("FAILED: " + "; ".join(failed) if failed else "all passed")
