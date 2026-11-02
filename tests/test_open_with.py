# Batch test (KLayout -z -nc -rx -r, imports gui.py, so it needs pya): opening an export in setupEM or EMStudio.
# The command line per program, the remembered choice, and which stale model scripts are still reported when the
# export opens EMStudio (which updates <name>.py next to the .simcfg on import), and native_path for the output path
# shown in the export dialog. Reads and writes no settings file.
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from klayout_em_export.gui import TOOLS, launch_command, native_path, open_with, quick_exit_text, updated_on_open

failed = []


def check(ok, text):
    print(("ok    " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


check(TOOLS == ("setupEM", "EMStudio"), f"programs {TOOLS}")
check(launch_command("setupEM", "/venv/bin/setupEM", "/w/x_em.simcfg") == ["/venv/bin/setupEM", "-simcfg",
                                                                          "/w/x_em.simcfg"],
      "setupEM gets -simcfg <file>")
check(launch_command("EMStudio", "/opt/EMStudio/EMStudio", "/w/x_em.simcfg") == ["/opt/EMStudio/EMStudio",
                                                                                "/w/x_em.simcfg"],
      "EMStudio gets the file itself")

check(open_with({}) == "setupEM", "default: setupEM (as before EMStudio support)")
check(open_with({"open_with": "EMStudio"}) == "EMStudio", "remembered choice: EMStudio")
check(open_with({"open_with": "something else"}) == "setupEM", "unknown value: setupEM")

folder = os.path.join(os.sep, "w")
simcfg = os.path.join(folder, "x_em.simcfg")
own_model = (os.path.join(folder, "x_em.py"), ["port 2: direction Z -> -Z"])
other = (os.path.join(folder, "older_model.py"), ["port 3 is gone"])
stale = [own_model, other]
check(updated_on_open(stale, simcfg, "EMStudio") == [other],
      "opened in EMStudio: <name>.py is updated on import, only the other script is reported")
check(updated_on_open(stale, simcfg, "setupEM") == stale, "opened in setupEM: both reported")
check(updated_on_open(stale, simcfg, None) == stale, "not opened: both reported")

# KLayout's Python joins with "/" also on Windows: D:\\...\\guide/cascode_em.gds
check(native_path("D:\\work\\guide/cascode_em.gds") == "D:\\work\\guide\\cascode_em.gds", "mixed Windows path")
check(native_path("D:/work/guide/cascode_em.gds") == "D:\\work\\guide\\cascode_em.gds", "Windows path with /")
check(native_path("\\\\server\\share/x_em.gds") == "\\\\server\\share\\x_em.gds", "UNC path")
check(native_path("/home/user/guide/cascode_em.gds") == "/home/user/guide/cascode_em.gds", "Linux path unchanged")
check(native_path("/home/user/odd\\name/x_em.gds") == "/home/user/odd\\name/x_em.gds",
      "Linux path with a backslash in a name unchanged")
check(native_path("") == "", "empty")

# a program that ends at once with an error code is reported; one still running, or ended without error, is not
check(quick_exit_text("EMStudio", 1) == "EMStudio ended at once (exit code 1): this EMStudio cannot open a .simcfg",
      f"ended at once: {quick_exit_text('EMStudio', 1)}")
check(quick_exit_text("EMStudio", None) is None and quick_exit_text("setupEM", 0) is None,
      "still running, or ended without error: no message")

print("all ok" if not failed else f"FAILED: {'; '.join(failed)}")
sys.exit(1 if failed else 0)
