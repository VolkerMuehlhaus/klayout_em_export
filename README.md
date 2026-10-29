# klayout_em_export

KLayout plug-in that exports part of a layout for EM simulation with
[gds2palace](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2) and hands it to setupEM. Work in progress.

## Installation (development)

Link the repo into KLayout's package folder, then restart KLayout (Windows, PowerShell):

```powershell
New-Item -ItemType Junction -Path "$HOME\KLayout\salt\klayout_em_export" -Target <path to this repo>
```

KLayout adds `python/` to its module path and runs `pymacros/em_export_menu.lym` at startup.

## Usage: Tools > EM Export

- **Export Region for EM...**: the region is the bounding box of the selected shapes. If nothing is selected, it is
  the box on the EM region layer **800/0** of the current cell. If there is none either, the whole cell is exported
  after asking.
  - Asks for the gds2palace stackup XML and the output file (default `<layout>_em.gds`).
  - Writes the flat GDS and a `.simcfg` next to it, shows what was kept and dropped, and offers to open setupEM.
- **Mark EM Region from Selection**: draws the bounding box of the selected shapes on layer 800/0, replacing an
  earlier box. Saved with the layout, it gives the same region on the next export.
- **EM Port** tool (toolbar): click a metal edge to create a via port, a zero-width line along that edge; Shift+click
  into the gap between two shapes of one metal to create an in-plane port, a box that bridges the gap. The edge or
  gap under the cursor is highlighted first. The shape goes on the next free port layer, then the port dialog
  opens; Cancel removes the shape again.
- **Port Settings...**: for the selected port shapes (layers 201..299, datatype 0; from the EM Port tool or drawn
  with KLayout's own tools): direction, from/to layer (via port, Z/-Z) or target layer (in-plane port), Z0 and
  excitation.
  - Shows the stackup it uses (Change... to pick another) and which stackup metals are drawn at the port. Only those
    are offered, unless "offer all stackup metals" is ticked. New via ports default to from = lowest, to = highest
    metal at the port.
  - A via port is a line (path of width 0) or a thin box; an in-plane port is a box that bridges the gap.
  - The settings are stored on the shape as GDS property 200, e.g. `port:dir=-Z;from=Metal3;to=TopMetal2;z0=50;v=1`,
    so they are saved with the layout. Port number = layer - 200.
  - The export writes them into the `.simcfg`. Ports without settings, with layer names that are not in the stackup,
    or with layers that are not drawn at the port are still listed there and reported, to be completed in setupEM.
- **Port Overview**: all ports of the current cell with their settings and problems.
- The last stackup and the setupEM program are remembered in `~/.klayout_em_export.json`. If `setupEM` is not on
  the `PATH` that KLayout sees, the plug-in asks once for the program (e.g. `<venv>\Scripts\setupEM.exe`).

## Modules

- `stackup.py`: reads a gds2palace stackup XML. It finds the GDS layers the EM model reads, with derived layers (such
  as the SG13G2 resistors) replaced by their source layers. It also lists the metal names for port dialogs.
- `export.py`: writes one flat cell with only those layers and the port layers 201..299, optionally clipped to a box.
  Metal is merged per layer. Port shapes are copied unchanged, so zero-width via-port lines survive. Every layer or
  purpose that is left out is reported.
- `simcfg.py`: writes a setupEM settings file (`.simcfg`) with the GDS file, stackup, cell and ports. setupEM takes
  all other settings from its preferences.

## Tests

KLayout batch mode (`klayout_app.exe -z -nc -rx -r tests/test_export.py`), environment `GDS`, `STACKUP`, `OUT` and
optionally `BOX="x1,y1,x2,y2"` (um).
