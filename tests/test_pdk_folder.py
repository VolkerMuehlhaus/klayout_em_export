# Batch test (KLayout -z -nc -rx -r): Create Circuit's IHP PDK folder. Any level leads to the folder with libs.tech
# (IHP-Open-PDK, ihp-sg13g2, a folder inside it); the dialog finds it from KLayout's technology or PDK_ROOT / PDK.
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pya  # noqa: F401
from klayout_em_export.circuit import find_pdk
from klayout_em_export.tech import ihp_sg13_circuit as ihp, generic_circuit

failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


root = os.path.join(tempfile.mkdtemp(), "IHP-Open-PDK")
pdk = os.path.join(root, "ihp-sg13g2")
os.makedirs(os.path.join(pdk, "libs.tech", "ngspice", "models"))
os.makedirs(os.path.join(pdk, "libs.ref"))
check(ihp.pdk_folder(pdk) == pdk, "the ihp-sg13g2 folder itself")
check(ihp.pdk_folder(root) == pdk, "IHP-Open-PDK: its ihp-sg13g2 folder")
check(ihp.pdk_folder(os.path.join(pdk, "libs.tech", "ngspice")) == pdk, "a folder inside the PDK: the PDK folder above it")
check(ihp.pdk_folder(tempfile.mkdtemp()) is None and ihp.pdk_folder("") is None, "a folder without a PDK: none")
check(generic_circuit.pdk_folder("") is None and find_pdk(generic_circuit) == ("", ""), "no PDK for the generic technology")

# no KLayout technology here (an empty KLayout home): found through PDK_ROOT / PDK
os.environ["PDK_ROOT"], os.environ["PDK"] = root, "ihp-sg13g2"
found, how = find_pdk(ihp, "sg13g2")
check((os.path.normcase(found), how) == (os.path.normcase(pdk), "PDK_ROOT") or how.startswith("KLayout"),
      f"found: {found} ({how})")
print("FAIL: " + "; ".join(failures) if failures else "all passed")
