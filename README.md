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

The menu follows the workflow, top to bottom.

1. **Choose Stackup...**: the gds2palace stackup XML for this layout. It is chosen once and used by every step. It
   is stored in the layout (meta info, saved with it) and as the default for other layouts. The port dialog and the
   export dialog show it and can change it too.
2. **EM Port Tool** (also in the toolbar as "EM Port"): click a metal edge to create a via port, a zero-width line
   along that edge; Shift+click into the gap between two shapes of one metal to create an in-plane port, a box that
   bridges the gap. The edge or gap under the cursor is highlighted first. The shape goes on the next free port
   layer (port number = layer - 200), then the port dialog opens; Cancel removes the shape again.
3. **Port Settings...**: the same dialog for selected port shapes (layers 201..299, datatype 0; from the tool or
   drawn with KLayout's own tools): direction, from/to layer (via port, Z/-Z) or target layer (in-plane port), Z0
   and excitation.
   - Shows which stackup metals are drawn at the port and offers only those, unless "offer all stackup metals" is
     ticked. New via ports default to from = lowest, to = highest metal at the port.
   - The settings are stored on the shape as GDS property 200, e.g. `port:dir=-Z;from=Metal3;to=TopMetal2;z0=50;v=1`,
     so they are saved with the layout.
4. **Port Overview**: all ports of the current cell with their settings and problems.
5. **Mark EM Region from Selection**: draws the bounding box of the selected shapes on layer **800/0**, replacing an
   earlier box. Saved with the layout, it gives the same region on the next export.
6. **Export Region for EM...**: one dialog with everything about the export, then one click.
   - Region: the bounding box of the selected shapes; else the box on layer 800/0; else the whole cell. Selected
     instances count with all their shapes.
   - With a selection, choose between "bounding box of the selection" (everything inside, cut at the box) and
     "selected shapes only" (uncut). The second adds what is easy to miss when selecting: the vias that land on two
     selected metals, and the port shapes that touch selected metal. The dialog lists what was added.
   - Stackup (Change...), output GDS (Browse...; default `<layout>_em.gds`, then the last output of this layout).
   - Preview: which layers are kept and which are dropped, and the ports in the region with their problems
     (incomplete ports are still exported, to be completed in setupEM).
   - "Open in setupEM after the export". The `.simcfg` is written next to the GDS.

Remembered in `~/.klayout_em_export.json`: the last stackup, the last port settings, the setupEM program and the
setupEM option. If `setupEM` is not on the `PATH` that KLayout sees, the plug-in asks once for the program (e.g.
`<venv>\Scripts\setupEM.exe`).

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
