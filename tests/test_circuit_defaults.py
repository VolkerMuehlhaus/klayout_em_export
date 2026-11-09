# Batch test (KLayout -z -nc -rx -r): Create Circuit's preset EM result. From the port map, the export's .simcfg says
# where setupEM puts the model; the best result is preset: calibrated with 0 Hz, then 0 Hz, then calibrated, then raw.
import json
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pya  # noqa: F401
from klayout_em_export.circuit import default_snp

failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


folder = tempfile.mkdtemp()
base = os.path.join(folder, "amp_em")
portmap = base + "_portmap.json"
open(portmap, "w").write("{}")
check(default_snp(portmap) == ("", ""), "no .simcfg, no model folder: nothing preset")
json.dump({"application": "setupEM", "saved_values": {}}, open(base + ".simcfg", "w"))
out = os.path.join(folder, "palace_model", "amp_em_data", "output", "amp_em")
os.makedirs(out)
for kind in ("", "_deembedded", "_dc", "_dc_deembedded"):
    open(os.path.join(out, f"amp_em{kind}.s3p"), "w").write("")
    path, found = default_snp(portmap)
    check(found == kind and path.endswith(f"amp_em{kind}.s3p"), f"with {kind or 'the raw result'} written: {found!r}")
# the model named by setupEM's script (written_with) in another folder
other = os.path.join(folder, "models")
out2 = os.path.join(other, "palace_model", "amp_v2_data", "output", "amp_v2")
os.makedirs(out2)
open(os.path.join(out2, "amp_v2_dc.s3p"), "w").write("")
json.dump({"application": "setupEM", "saved_values": {"sim_path": other}, "written_with": "amp_v2.py"},
          open(base + ".simcfg", "w"))
path, found = default_snp(portmap)
check(found == "_dc" and path.endswith("amp_v2_dc.s3p"), f"the script's model in its sim_path: {path}")
check(default_snp("") == ("", "") and default_snp(os.path.join(folder, "x.json")) == ("", ""), "no port map: nothing")
# the dialog: the EM result preset, the output named after it, the hint says which result it is
from klayout_em_export.circuit import CircuitDialog
dialog = CircuitDialog(portmap)
check(dialog.snp.text.endswith("amp_v2_dc.s3p") and "with 0 Hz" in dialog.snp_hint.text,
      f"the dialog presets the result: {dialog.snp.text} | {dialog.snp_hint.text}")
check(dialog.output.text.startswith(dialog.snp.text[:-4]), f"the output is named after it: {dialog.output.text}")
# the Python setupEM runs in: from its entry script, a wrapper that activates a venv, or next to setupEM(.exe)
from klayout_em_export.circuit import has_snp2le, python_of
venv = os.path.join(tempfile.mkdtemp(), "palace")
bin_dir = os.path.join(venv, "Scripts" if os.name == "nt" else "bin")
os.makedirs(bin_dir)
py = os.path.join(bin_dir, "python.exe" if os.name == "nt" else "python3")
open(py, "w").write("")
entry = os.path.join(bin_dir, "setupEM")
open(entry, "w").write(f"#!{py}" + chr(10) + "import sys" + chr(10))
check(python_of(entry) == py, f"a Python entry script: its interpreter {python_of(entry)}")
wrapper = os.path.join(tempfile.mkdtemp(), "setupEM")
open(wrapper, "w").write(chr(10).join(["#!/bin/bash", f"source {venv}/{os.path.basename(bin_dir)}/activate", "setupEM $1 $2", ""]))
check(os.path.normcase(python_of(wrapper)) == os.path.normcase(py), f"a wrapper that activates a venv: {python_of(wrapper)}")
exe = os.path.join(bin_dir, "setupEM.exe")
open(exe, "wb").write(bytes([77, 90, 0, 98]))
check(python_of(exe) == py, f"a program next to the venv's Python: {python_of(exe)}")
check(python_of("") == "" and has_snp2le(py) is None, "nothing found, and no site-packages to look into")
site = os.path.join(venv, "Lib", "site-packages") if os.name == "nt" else os.path.join(venv, "lib", "python3.12", "site-packages")
os.makedirs(site)
check(has_snp2le(py) is False, "site-packages without snp2le")
os.makedirs(os.path.join(site, "snp2le"))
check(has_snp2le(py) is True, "snp2le installed")
print("FAIL: " + "; ".join(failures) if failures else "all passed")
