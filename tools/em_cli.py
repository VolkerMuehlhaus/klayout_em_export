"""Run a klayout_em_export command headless, from any Python (no KLayout package needed): writes the request,
starts KLayout in batch mode with python/klayout_em_export/cli.py and prints the JSON result.

    python tools/em_cli.py request.json            # or: ... < request.json, or: ... -  (stdin)
    python tools/em_cli.py status gds=layout.gds stackup=stack.xml
    python tools/em_cli.py add_via_port gds=a.gds x=33.7 y=-42.2 output=a_ports.gds

key=value arguments are JSON values where they parse as JSON (numbers, true/false, lists), else text. The request
format and the commands are in cli.py. Exit code 0 if the command succeeded ("ok": true), 1 if not.

KLayout: the KLAYOUT environment variable, else klayout / klayout_app on the PATH, else the usual Windows install
folders. It runs with -zz -nc -rx (no window, no configuration, no autorun macros), so the IHP PDK device library is
loaded from the request's "pdk" or, if that is missing, the KLAYOUT_EM_EXPORT_PDK environment variable.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "python", "klayout_em_export", "cli.py")
WINDOWS_KLAYOUT = [os.path.join(os.environ.get(v, ""), "KLayout", "klayout_app.exe")
                   for v in ("ProgramFiles", "ProgramFiles(x86)", "APPDATA")] + [r"D:\KLayout\klayout_app.exe"]


def find_klayout():
    for candidate in [os.environ.get("KLAYOUT"), shutil.which("klayout"), shutil.which("klayout_app")] + WINDOWS_KLAYOUT:
        if candidate and os.path.isfile(candidate):
            return candidate
    sys.exit(json.dumps({"ok": False, "error": "KLayout not found: set the KLAYOUT environment variable"}))


def _value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def parse_request(argv):
    if not argv or argv == ["-"]:
        return json.load(sys.stdin)
    if len(argv) == 1 and argv[0].endswith(".json"):
        with open(argv[0], encoding="utf-8") as f:
            return json.load(f)
    request = {"command": argv[0]}
    for item in argv[1:]:
        key, sep, value = item.partition("=")
        if not sep:
            sys.exit(json.dumps({"ok": False, "error": f"argument {item!r}: expected key=value"}))
        request[key] = _value(value)
    return request


def run(request, timeout=900):
    """The result dict of one request."""
    if not request.get("pdk") and os.environ.get("KLAYOUT_EM_EXPORT_PDK"):
        request = dict(request, pdk=os.environ["KLAYOUT_EM_EXPORT_PDK"])
    for key in ("gds", "stackup", "output", "out", "pdk"):      # cli.py runs in another working directory
        if isinstance(request.get(key), str) and request[key]:
            request[key] = os.path.abspath(os.path.expanduser(request[key]))
    with tempfile.TemporaryDirectory(prefix="em_cli_") as tmp:
        req_path, res_path = os.path.join(tmp, "request.json"), os.path.join(tmp, "result.json")
        with open(req_path, "w", encoding="utf-8") as f:
            json.dump(request, f)
        proc = subprocess.run([find_klayout(), "-zz", "-nc", "-rx", "-rd", f"request={req_path}",
                               "-rd", f"result={res_path}", "-r", os.path.abspath(CLI)],
                              capture_output=True, text=True, timeout=timeout, cwd=tmp)
        try:
            with open(res_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"ok": False, "error": "KLayout wrote no result", "exit_code": proc.returncode,
                    "output": (proc.stdout + proc.stderr)[-4000:]}


def main():
    result = run(parse_request(sys.argv[1:]))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
