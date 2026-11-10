# Link prototype: driving the plug-in from another program

Tried in November 2026 and dropped for setupEM. A record of what was built and learned, for anyone designing a
similar link. Nothing here is part of the plug-in.

## What was built

- **`klayout_remote`** (separate repo): a small generic KLayout package. It runs a TCP server on 127.0.0.1 with a token,
  and takes one JSON object per line: `hello`, `load_module` (the client sends a Python package, cached by hash) and
  `call` (a function by name, on the GUI thread, in one undo step), plus selection and layout events and a generic pick
  tool.
- **`remote.py`** in this repo: the plug-in's steps as functions for the link, and a test that runs the guide's steps
  over the link and compares the port map with the guide's export (branch `remote-link`, last commit `bca72e6`).
- **The plug-in without its panel, menu and tool.** The batch tests gave the same results (branch `remove-panel`,
  last commit `384c63c`).
- **A KLayout tab in setupEM** that showed the panel's steps and started KLayout if none ran (setupEM branch
  `klayout-link`, last commit `d7058ae`).

The three branches were deleted on 2026-11-10; their code is not kept.

## Why it was dropped

It worked, but in use it felt wrong: switching windows all the time, two port lists (ports in the layout, and the copy
in setupEM's Ports tab after an export) and opening the layout from setupEM. So KLayout and the panel stay the place for
layout work, and setupEM only receives the export (setupEM branch `klayout-handover`).

## What was learned

Tested on KLayout 0.29.4 (Windows) and 0.30.12 (Linux), in batch mode and with a window.

- `pya.QTcpServer` works in both versions. Requests are served while a modal dialog is open, so the server has to
  report "busy" itself. No firewall prompt was seen on Windows.
- A read-only call must not open an undo step: an empty step clears the redo list.
- Editing needs KLayout in editable mode (`-e`). A viewer-mode KLayout raises "No undo/redo support on non-editable
  shape lists", so the link reports the mode in `hello`.
- Code run over the link can crash KLayout (see the pitfalls in [AGENTS.md](../AGENTS.md)), and the user's layout with
  it. The client must notice the dropped connection and say so.
- Startup takes long sometimes (about 23 s under Wayland on one Linux machine, 3 s with X11): wait for a ready signal,
  no fixed timeout.
- In KLayout's Qt binding `QTimer.singleShot` is a property: use a timer object.
- Automated tests need their own KLayout home with the startup tips hidden. On Windows there is no working offscreen
  Qt platform for KLayout, so the window is moved off screen.

Open when it was dropped: long jobs block KLayout's GUI thread (Remove Dummy Fill takes about 60 s on a large layout),
so a link would need progress reports or background jobs; and how users install and update the KLayout side.
