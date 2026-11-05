"""Run the batch tests (test_*.py in this folder) in KLayout, one after the other, and print one table.

    python tests/run_all.py                 all tests
    python tests/run_all.py thermal panel   the tests whose name contains one of the words

Plain Python, outside KLayout. Each test runs as klayout_app -z -nc -rx -r <test> with an empty KLayout home (no
installed copy of the plug-in or a PDK technology gets in the way), the repo's python/ and tests/ folders on KLayout's
Python path, Qt offscreen, and an output folder of its own.
A test fails if KLayout ends with an error code or the output has a line starting with FAIL or ERROR, or a traceback.
A test whose only problem is a missing input file (a layout that is not in the repo, the PDK) is SKIP, not FAIL.

Environment (see testpaths.py for the data folders):
  KLAYOUT_EXE         the KLayout executable (default: KLAYOUT, klayout_app / klayout on PATH, the usual Windows folders)
  PORTMAP, SNP, PYTHON  inputs of test_circuit (an EM result of the cascode and a Python with snp2le); skipped without
Logs: <temp>/klayout_em_export_tests/run_all/<test>.log
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testpaths import REPO, STACKUP, TESTS_DIR, layout_file  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools"))
from em_cli import WINDOWS_KLAYOUT  # noqa: E402

TIMEOUT = 1800      # s per test
# inputs some tests take from the environment: {test: {variable: default, None: required, skip without}}
INPUTS = {"test_export": {"GDS": layout_file("OctaDiffTap_0n50_ports3.gds"), "STACKUP": STACKUP},
          "test_circuit": {"PORTMAP": None, "SNP": None, "PYTHON": None}}
FAILED = re.compile(r"^(FAIL|ERROR)\b|Traceback \(most recent call last\)", re.M)
MISSING = re.compile(r"FileNotFoundError|No such file or directory|does not exist|cannot open file|Unable to open")


def klayout_exe():
    for candidate in [os.environ.get("KLAYOUT_EXE"), os.environ.get("KLAYOUT"), shutil.which("klayout_app"),
                      shutil.which("klayout")] + WINDOWS_KLAYOUT:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def run(test, exe, root):
    """(status, seconds, note) of one test."""
    out = os.path.join(root, test)
    os.makedirs(out, exist_ok=True)
    home = os.path.join(root, "klayout_home")
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ, KLAYOUT_HOME=home, KLAYOUT_PATH=home, OUT=out,
               KLAYOUT_PYTHONPATH=os.pathsep.join([os.path.join(REPO, "python"), TESTS_DIR]))
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    for name, default in INPUTS.get(test, {}).items():
        if not env.get(name):
            if default is None:
                return "SKIP", 0.0, f"needs {name} (see run_all.py)"
            env[name] = default
    start = time.time()
    try:
        result = subprocess.run([exe, "-z", "-nc", "-rx", "-r", os.path.join(HERE, test + ".py")], env=env,
                                capture_output=True, text=True, errors="replace", timeout=TIMEOUT)
        output, code = result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired as e:
        output, code = (e.stdout or "") + (e.stderr or "") if isinstance(e.stdout, str) else "", "timeout"
    seconds = time.time() - start
    output = "\n".join(l for l in output.splitlines() if "already destroyed" not in l)
    with open(os.path.join(root, test + ".log"), "w", encoding="utf-8") as f:
        f.write(output)
    problems = [m.group(0) for m in FAILED.finditer(output)]
    if code == 0 and not problems:
        return "ok", seconds, (output.strip().splitlines() or [""])[-1][:70]
    first = next((l for l in output.splitlines() if FAILED.search(l)), f"exit code {code}")
    if MISSING.search(output) and not re.search(r"^FAIL\b", output, re.M):
        line = next((l for l in output.splitlines() if MISSING.search(l)), first)
        return "SKIP", seconds, "input missing: " + line.strip()[:60]
    return "FAIL", seconds, first.strip()[:70]


def main(words):
    exe = klayout_exe()
    if not exe:
        print("KLayout not found: set KLAYOUT_EXE")
        return 2
    tests = sorted(f[:-3] for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))
    if words:
        tests = [t for t in tests if any(w in t for w in words)]
    root = os.path.join(tempfile.gettempdir(), "klayout_em_export_tests", "run_all")
    os.makedirs(root, exist_ok=True)
    print(f"KLayout: {exe}\nlogs: {root}\n")
    results = []
    for test in tests:
        status, seconds, note = run(test, exe, root)
        results.append((test, status))
        print(f"{test:24s} {status:4s} {seconds:6.1f} s  {note}", flush=True)
    counts = {s: sum(1 for _, x in results if x == s) for s in ("ok", "FAIL", "SKIP")}
    print(f"\n{counts['ok']} ok, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
