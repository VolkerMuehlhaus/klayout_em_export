# klayout_em_export reference

Everything the plug-in does, in workflow order, with the exact rules. To learn the flow, start with the
[user's guide](userguide/klayout_em_export_userguide.md).

## Usage: EM panel and EM menu

The **EM panel** is docked at the right of the main window (opens at startup; menu **EM > EM Panel** brings it
back). It is a checklist in workflow order: each step is one line with a status mark (OK, warning, error) and a
summary; the arrow shows its details and buttons.

- **Stackup** of the current layout (details: Change...). A warning here means a metal or via whose height is given
  by a variable in the stackup file: the plug-in cannot place it, so it is left out of the nets, the ground and the
  port directions.
- **Region**: what the export uses right now, following the selection: the bounding box of the selection, else
  the EM region box (layer 800/0), else the whole cell. A selection of port shapes only does not count (details:
  Mark Region from Selection).
- **Ground**: the ground net, traced through the vias in the EM region box (or the whole cell). It is checked on
  every refresh (a very large region: Run Checks in the details).
  - The ground is found from the via ports: of the nets at both ends of the via ports, the one most ports reach (on
    a tie, the larger one). Which end is from and which is to does not matter.
  - Details: **Mark Selected** marks the selected metal shapes as ground instead (stored in the layout), **Use
    Ports** forgets the marks, **Show in Layout** outlines the ground net.
  - Only wiring is traced: the stackup's conductors above the device level, connected by the vias between
    vertically adjacent metals (from the stackup's z positions). Activ, Cont, resistors and the PEC sheets are left
    out, so a transistor or resistor is an open circuit here. Ground that is joined only outside the region shows
    up as separate pieces.
- **Devices**: PDK transistors (npn13G2, npn13G2L, npn13G2V, nmos, pmos and their HV and rf variants) and resistors
  (rsil, rppd, rhigh) found in the cell, and whether they are replaced by ports. Recognized as SG13_dev pcells, or
  as static device cells: exported from Cadence (`<device>_CDNS_<number>`) or saved without pcell context
  (`<device>$<number>`, e.g. after a fill tool). These have the same pins but no parameters: a resistor's value
  comes from its label, an npn's size from its `Ae=Nx*Ny*we*le` label; any other static device without a parameter
  label is not replaced ("no parameters"). The reference plane is at the pcell's pins: the device model
  (circuit simulator) covers the device up to its pins, the EM model everything from there on.
  - **Replace All** adds, in the layout and tagged (GDS property 202): one `REF_FOR_TRANSISTOR` patch per device,
    under its pins (their bounding box + 0.2 um; separate for devices side by side, the Devices step warns if two
    patches touch), and one via port per terminal from the pin's metal down to that patch, along
    the full pin: one port for the whole terminal (e.g. all emitter fingers). **Undo Replace** removes them again.
  - The export removes the replaced devices' own shapes below their pins: below Metal1 everywhere (Activ, Cont,
    poly, implants), and under a pin on a higher metal also the wiring down to Metal1 (the npn emitter pin is a
    Metal2 strip on one Metal1 island per finger, joined by Via1: islands and Via1 go, the emitter port runs from
    Metal2). The device's other metal stays; your own shapes are not touched.
  - nmos/pmos: their pins are unnamed (nmos) or missing (pmos), so source and drain are the device's Metal1 strips
    along the gate fingers, alternating S, D, S, ... from the left in the cell's own coordinates. A terminal on
    several fingers is one port with one line per finger: the elements of one port, in parallel. The gate pin is
    poly, below Metal1: the gate port goes on your Metal1 gate contact, found by tracing the poly from the gate
    through Cont, and the export removes that traced poly and those contacts (their resistance belongs to the
    device side).
  - Ports with several lines (multielement ports) need gds2palace 0.9.3 or newer: it
    makes them one Palace lumped port with parallel elements. Older gds2palace versions use only one of the lines.
  - Resistors: **Replace All** replaces them too while **include resistors** is ticked (the default). A replaced
    resistor gets two via ports, PLUS and MINUS, from its Metal1 heads down to its own REF patch; the export removes
    its body, contacts and implants. PLUS is the head with the lower coordinate along the resistor in the cell's own
    coordinates (the pins have no names). A resistor of several segments is not replaced. Unreplaced resistors stay
    layout: the stackup models them as sheet resistors of the drawn size, and their R comes out too low, see below.
    Capacitors (cmim) and inductors are never replaced.
  - Why resistors should be replaced: the PDK computes R = Rsh·l/(w + Δw) + 2·rz/w (pcell formula and SPICE models
    agree). Δw changes the width only (rsil +0.01 µm, rppd +0.006 µm, rhigh −0.04 µm), and rz is a contact end
    resistance (rsil 4.5 Ω·µm, rppd 35 Ω·µm, rhigh 80 Ω·µm per end) that no drawn sheet carries. The gds2palace sheet
    has the drawn l × w and the nominal Rsh: the width offset is missing, and of the end resistance only what the
    Cont vias contribute is there. Both are fixed amounts, so physically small resistors are affected most (narrow:
    width offset, short: end resistance). Palace at 10 MHz, PDK cells as drawn (`tests/resistor_palace/`): rhigh
    0.655 × 1.245 µm −13 %, rppd 1 × 1.665 µm −12 %, rhigh 0.5 × 4.29 µm −10 %, rhigh 2 × 1.325 µm −9 %, rsil
    0.5 × 2.33 µm −2 %, rsil 2 × 13.06 µm −0.2 % (for rsil, the Cont vias happen to cover most of the end
    resistance). An unreplaced resistor makes the **Devices** line a warning.
  - The port map names the device and terminal of these ports, for connecting the `.snp` to the device models.
  - A terminal whose net (traced through the vias from its pin) holds only the device's own metal is reported as
    not connected to any wiring, in the Devices step and in the export dialog: it floats in the EM model, e.g. when
    the wiring to the device was cut.
  - Recognition needs the IHP PDK library (SG13G2 or SG13CMOS5L) loaded in KLayout. A layout without IHP devices
    or KLayout technology gets the generic technology: no device support (tooltip of the Devices line).
- **Ports**: one table with the ports of the cell and the ports proposed where the EM region box cuts conductors.
  - Columns: number and layer in the layout, the port, its number in the export (and the `.snp`; "outside" if it
    is not in the region), and its status: ok, its problems (incomplete, layers not drawn at the port, short
    circuit: both ends on one net), "proposed" or "cut without ground".
  - Click a row to highlight it in the layout (a marker, not a selection: a selected port would become the
    export region); double-click to edit a port or create a proposed one; right-click for Settings, Delete or
    Create.
  - **EM Port tool** starts the tool. **Create Proposed Ports** adds a via port on each signal conductor the EM
    region box cuts: a zero-width line on the box edge, from the signal metal to the ground metal at the cut (the
    closest in height), from = lower, to = upper, direction Z, Z0 50 Ohm. The export cuts the metal there, so the
    port sits exactly on the cut. These ports are tagged (GDS property 201 = "boundary"); if the box is moved,
    they are reported as no longer on the edge. Proposals need the EM region box, since the ports are drawn in
    the layout. With **as port walls** ticked, the proposed ports are in-plane ports on the cut metal instead,
    pointing into the region (direction X, -X, Y or -Y), for a gds2palace port wall on that side. They need
    ground metal reaching that side of the box on any metal, also the cut metal itself (a coplanar line); a via
    port needs ground on another metal at the cut.
  - Ports drawn with KLayout's own tools appear on **Refresh**.
- **Export for EM...** and **Open in setupEM** or **Open in EMStudio** (the last export of this layout, without
  exporting again; the program last chosen in the export dialog, the other one is in the EM menu).

The same steps are in the **EM** menu in the menu bar, top to bottom in workflow order:

1. **Choose Stackup...**: the stackup XML for this layout (gds2palace for Palace, gds2openEMS for openEMS). It is chosen once and used by every step. It
   is stored in the layout (meta info, saved with it) and as the default for other layouts. The port dialog and the
   export dialog show it and can change it too. Until you choose one for a layout, the plug-in takes the stackup of
   your own setupThermal / setupEM file for it (a `.tsimcfg` / `.simcfg` next to it with this GDS file), else the
   last one you chose; then the Stackup row says "last used, not chosen for this layout".
   - **Remove Dummy Fill** (next in the menu, once, if the layout has fill): removes the dummy metal fill of the
     current cell, one undo step. Process independent, told by what it is, not by datatype or cell names: a shape
     on a conductor or sheet layer of the stackup (any datatype) that floats (merged with the drawn metal of its
     layer, datatype 0, it touches no via of the stackup, no label, no port and no device or PDK cell; other
     datatypes such as no-fill markers are no metal and are left out) and whose size repeats at least 20 times
     among the floating shapes. Drawn metal (datatype 0) is judged more carefully: a drawn shape touching a shape of
     another datatype stays. Vias and via arrays are never removed: via layers are not searched. A fill tile cell
     loses the placements that are fill; a cell left empty or unplaced is deleted. On a 60 GHz PA: 68,312 fill
     shapes in about 14 s, on a 180 GHz PA 617,659 (all of its fill, Activ included) in about 60 s.
   - **Fill Density Holes and Merge Metal** (next in the menu, once, before ports): fewer edges to mesh and fewer
     polygons for the checks, in the current cell, one undo step (Edit > Undo). Per metal layer of the stackup
     (conductors and sheets, not vias): the repeated small openings that density rules put into wide metal
     (cheesing; a hole size found at least 20 times, in any shape) are filled, other holes stay; then the cell's
     own shapes are merged with the fill, together with the metal of plain subcells placed at least twice (via
     stacks, MIM capacitors: their pads merge into the lines) or holding filled holes (a cheesed plane in a cell of
     its own). Devices, PDK pcells, cells placed once otherwise, cells also placed elsewhere, vias, texts and shapes
     with properties stay as they are. On a 60 GHz PA: 2899 -> 387 metal polygons. Once saved, the change stays:
     such a layout must not go to tape-out (the fill breaks the density rules).
2. **EM Port Tool** (also in the toolbar as "EM Port"): click a metal edge to create a via port, a zero-width line
   along that edge; Shift+click into the gap between two shapes of one metal to create an in-plane port, a box that
   bridges the gap. The edge or gap under the cursor is highlighted first. Only metals visible in the layer panel
   are picked (a hidden group hides its layers); when the only edge or gap under the cursor is on a hidden layer,
   the status bar says so. The port dialog still offers every metal drawn at the port. The shape goes on the next
   free port layer (port number = layer - 200), then the port dialog opens; Cancel removes the shape again.
3. **Port Settings...**: the same dialog for selected port shapes (layers 201..299, datatype 0; from the tool or
   drawn with KLayout's own tools): direction, from/to layer (via port, Z/-Z) or target layer (in-plane port), Z0
   and excitation.
   - Shows which stackup metals are drawn at the port and offers only those, unless "offer all stackup metals" is
     ticked. A via port made with the EM Port tool starts with from = the clicked metal, to = the next metal below
     it at the port (a via port must not pass through a metal); without one below, the next metal above.
   - The settings are stored on the shape as GDS property 200, e.g. `port:dir=-Z;from=Metal3;to=TopMetal2;z0=50;v=1`,
     so they are saved with the layout.
4. **Port Overview**: all ports of the current cell with their settings and problems.
5. **Mark EM Region from Selection**: draws the bounding box of the selected shapes on layer **800/0**, replacing an
   earlier box. Saved with the layout, it gives the same region on the next export.
6. **Export for EM...**: one dialog with everything about the export, then one click.
   - With a selection: "Selected shapes only (+ connecting vias and ports)", the default, exports just the selected
     shapes, uncut. It adds what is easy to miss when selecting: the vias that land on two selected metals, and the
     port shapes that touch selected metal; the dialog lists what was added. "Everything inside the selection's
     bounding box" exports all stackup layers inside that box, cut at the box. Selected instances count with all
     their shapes.
   - Without a selection: everything inside the box on layer 800/0, else the whole cell.
   - Stackup (Change...), output GDS (Browse...; default `<layout>_em.gds`, then the last output of this layout).
   - Datatypes: the GDS datatypes exported, those of setupEM's `.simcfg` for this export and of your own
     setupEM / setupThermal files for the layout together, else 0 (e.g. 0, 4, 35 for copper pillars on 41/35).
   - The ports with their problems. Ports without complete settings are exported as shapes but left out of the
     `.simcfg`, because setupEM cannot load them. Only the stackup's layers are exported; the others are dropped.
   - "Open in setupEM / EMStudio". The `.simcfg` is written next to the GDS. If the program ends at once with an
     error code, the plug-in says so after 2 s ("EMStudio ended at once (exit code 1): this EMStudio cannot open a
     .simcfg": an EMStudio without the .simcfg import exits on the unknown argument). EMStudio imports it
     as a Palace or OpenEMS model and asks which (File > Import setupEM Config, needs EMStudio with that import,
     IHP-GmbH/EMStudio PR #53). For OpenEMS: use an OpenEMS stackup (gds2openEMS, never a gds2palace one), and
     don't replace devices: device replacement (ports to `REF_FOR_TRANSISTOR`) is for Palace only. Neither the
     plug-in nor EMStudio checks this;
     when `<name>.py` exists next to the `.simcfg`, EMStudio updates only that model's ports, layout file, stackup,
     cell and purpose, and keeps its frequencies, mesh, boundaries and code. The stackup comes from the export, also
     when another one was chosen in EMStudio: choose the stackup here. The first import fixes the simulator; for the
     other one, rename or delete `<name>.py` and export again. A model saved elsewhere or under another name is not
     found: the import then makes a new one.
   - Ports are numbered without gaps in the export: the complete ports 1..N in layout order, then the incomplete
     ones. The `.simcfg` and so the `.snp` use these numbers, the exported GDS the port layers 201.. in that order
     (without the stackup's own layers in that range, e.g. SUBGND on 210 or 250); `<name>_portmap.json` maps them
     back to the layout's port numbers (the dialog shows the map when numbers change). Reason: after Palace,
     `combine_extend_snp` takes the highest port number as the port count and fills missing ports with |S| = 1.
   - Exporting again updates an existing `.simcfg`: the GDS file, stackup, cell and ports are set, everything
     else (frequencies, mesh, ... saved with setupEM's Save Config) is kept. The ports always come from the
     layout, where they are defined.
   - Port walls: every side of the region with an in-plane port on it (made with **as port walls**, or drawn by hand)
     gets `PORTWALL` in the `.simcfg`'s `boundary`; the other sides keep their value (`ABC` in a new file).
   - After the export, model scripts (`*.py` next to the GDS and in setupEM's `sim_path`) that read this GDS but
     have other ports are reported (port number, layer, direction, from/to/target; not excitation or Z0): run as
     they are, their S-parameters would not match the new port map. The warning is short (script name, number of
     differing ports, what to do), the port list is under Show Details. Update the script by opening the export in
     setupEM and choosing Continue with the script (setupEM 0.16 or newer):
     ports and layout come from the export, everything else stays. When the export opens EMStudio, the EMStudio
     model `<name>.py` next to the `.simcfg` is not reported: EMStudio updates its ports on that import.
7. **Create Circuit (EM Result with Devices)...**: after the Palace run, the EM result with the PDK devices put
   back, for ngspice, VACASK, Xyce or Spectre; see [Circuit wrapper](#circuit-wrapper-ngspice-vacask-xyce-spectre).

**Backup of the original layout:** before the plug-in first changes a layout that holds none of its data (no meta
info of the plug-in, no port settings, device or boundary tags, no EM region box), it copies the layout file as it is
on disk to `<file>.bak`, e.g. `core.gds.bak` - never over an existing `.bak`, so the oldest original stays. Saving the
layout afterwards writes the EM setup into it; the `.bak` is the file to pass on. KLayout can also keep backups of
every save (File > Setup > Application > General, number of backup files).

Remembered in `~/.klayout_em_export.json`: the last stackup, the last port settings (a port without settings of
its own takes their direction, Z0 and excitation, not their layers), the setupEM and EMStudio
programs, whether and where to open the export (`open_setupem`, `open_with`; `open_setupthermal` for the thermal export), the Create Circuit choices (Python with snp2le, PDK folder, simulator); and per layout file its stackup, last export and ground marks. These are also stored in the layout
itself (saved with it), but storing them does not mark the layout as modified, so the settings file keeps them
when the layout is closed without saving. If `setupEM` or `EMStudio` is not on the `PATH` that KLayout sees, the plug-in asks once for the program (e.g.
`<venv>\Scripts\setupEM.exe`, `<venv>/bin/setupEM`, `EMStudio.exe`).

## Thermal export (setupThermal)

Experimental: it needs gds2palace 0.9.4 and setupEM 0.17 or newer (gds2palace 0.9.5 for the stackups with the heat
target layers `HEAT_TRANSISTOR` and `HEAT_RESISTOR`; without them every heat source sits in Activ and the devices
come out too cool), and resistor temperatures are not validated yet.

**EM > Export for Thermal (setupThermal)...** exports the same region as a model for setupThermal / gds2palace's
Elmer thermal mode. In the EM panel, switch to the **Thermal** tab at the top: it shows the heat sources of the
region with their layers and schematic names, the LVS database, and the boundaries of the last thermal export, with
**Export for Thermal...** and **Open in setupThermal** below (the EM steps, which a thermal model does not need, are
hidden; device replacement is not needed for it). The export writes:

- the layout with the devices as drawn (their metal, contacts and vias conduct heat); EM ports and REF patches
  are left out;
- one heat source per transistor and resistor: its heat area as drawn by the PDK (IHP: the `HeatTrans` and
  `HeatRes` shapes of the device), on a marker layer of its own from 201 upward (skipping the stackup's layers), in
  the z range of `Activ`. PDK versions before these shapes (March 2025 and older) draw none: then the export
  derives the same rectangles from the device's layers, as the PDK does (npn emitter windows grown by 0.05 µm,
  resistor bodies, MOS gates). Only a device with neither gets its bounding box, which the dialog and the panel
  list;
- Activ.mask (1/20) with Activ: IHP's npn cells draw the silicon around each emitter there. The technology module
  names the datatypes the thermal export always keeps (`THERMAL_PURPOSES`, IHP: 0 and 20), together with those of
  the setupThermal files;
- `<name>.tsimcfg` for setupThermal (all powers 0 W until set) and `<name>_thermalmap.json`, which says which
  device each heat source layer belongs to.

**Instance names from LVS.** The powers of the devices come from your circuit simulation, per schematic instance.
Choose the LVS database (`.lvsdb`, Thermal tab: Names, or the
export dialog) of KLayout's LVS of this layout against your schematic (IHP's deck
writes it), and each heat source gets the name of its schematic instance in the thermal map: `Q1`, `Xcore.Q1` for
a device in a subcircuit. setupThermal's **Load powers...** then sets the powers from a file of your simulation, one
line per instance (`Xcore.Q1, 2.5m`). LVS may have been run on the exported cell or on a cell that contains it
once. A heat source without a matching LVS device keeps no name, and the export lists it.

**Your own heat sources and boundaries.** Markers you drew yourself for setupThermal stay on their layers: the
layers your setupThermal file for this layout uses (a `.tsimcfg` next to it with this GDS file), and shapes without
EM port settings on 201..299. Their rows (power, temperature, target layer) go into the exported `.tsimcfg`, and the
export's own layers skip their numbers. EM ports and thermal markers can share one layout when their layer numbers
differ: EM ports on 201..299, thermal markers e.g. on 401..499, which no stackup in these repositories uses.

Boundaries (constant temperatures) are chosen in setupThermal. The region outline is on the first marker layer
(201); the first export puts a placeholder boundary there, a constant temperature (300 K) without a target layer.
setupThermal lists it as "region outline: choose the target layer" and does not build the model until you choose
the stackup layer where the temperature is fixed (e.g. the substrate backside). An export again keeps setupThermal's settings, the boundaries, and the power and instance name of
every device still in the region. Headless: the CLI command `export_thermal` (`lvsdb` for the names).

## Circuit wrapper (ngspice, VACASK, Xyce, Spectre)

After the Palace run, **EM > Create Circuit (EM Result with Devices)...** turns the result into a circuit with the
PDK devices put back. Choose the port map (the last export's is preselected), the EM result (`<model>_dc.sNp`), the
simulator, optionally the IHP PDK folder, and the Python with snp2le (by default the one next to setupEM). The
dialog runs `tools/spice_wrapper.py`, which also works on its own:

```bash
python tools/spice_wrapper.py <export>_portmap.json <model>_dc.sNp -o <name>.cir --simulator ngspice --pdk <IHP-Open-PDK>/ihp-sg13g2
```

| Simulator | EM model | Device models | Tested (cascode, `tests/simulators`) |
| --- | --- | --- | --- |
| ngspice | snp2le equivalent circuit | PDK `libs.tech/ngspice` | yes |
| VACASK | snp2le equivalent circuit (VACASK format) | PDK `libs.tech/vacask`, found through its `.vacaskrc.toml` | yes, same as ngspice |
| Xyce | snp2le equivalent circuit | PDK `libs.tech/xyce` | yes; S21 0.5 dB higher at 100 GHz, from Xyce's npn13G2 model |
| Xyce | the .sNp file (`YLIN`) | PDK `libs.tech/xyce` | harmonic balance only: in AC and DC, Xyce 7.10 treats `YLIN` as open |
| Spectre | the .sNp file (`nport`) | your PDK's includes (commented placeholders) | no |

ngspice cannot use the .sNp file itself (its Touchstone support is a transfer-function element for AC, not an
N-port), and VACASK cannot yet (Touchstone import is planned).

- Start the Palace sweep at 0 Hz in gds2palace: it then simulates 10 MHz and 20 MHz and writes `<model>_dc.sNp`
  with a 0 Hz point extrapolated from them. Give the wrapper that file.
- The EM model becomes a lumped-element equivalent circuit (snp2le universal mode: vector fitted, passive, pinned
  to the 0 Hz point).
- Subcircuit `<name>`: its pins are the ports that belong to no device (pads, bias inputs); each replaced device is
  an instance of its PDK model (npn13G2 with Nx, le, we; MOSFETs with w, l, ng; resistors with w, l), its substrate or
  bulk pin to ground (pmos: to its source). A resistor from a static Cadence cell has no parameters: an ideal resistor
  of its label value, noted in the header.
- Each device terminal is wired straight to its port's pin. This grounds the device's REF patch, which floats in the
  EM model, and adds the patch's capacitance (about 7 fF per npn13G2 Nx=8). Cascode test: S21 0.06 dB lower at
  10 GHz, 0.4 dB at 200 GHz, than with the patches floating.
- DC: a port measures a voltage difference, so the EM model does not fix a device's absolute potential. The ports of
  each net (from the port map, traced through the layout's vias at the export) are tied together, and to ground on
  the ground net, by 1 mH. The wires' DC resistance is not modelled. Without a 0 Hz point in the .sNp, the equivalent
  circuit's DC is a guess of the fit, and every port gets a 1 uF DC block as well.
- The export sets each via port's direction (`Z` or `-Z`) so that every via port has its signal metal on the same
  end; the port map records it with each port's net and signal layer. Export again if the port map lacks them.
- Test report: [doc/test_cascode_wrapper](test_cascode_wrapper/README.md).

## Headless use (scripts, AI agents)

The workflow also runs without the KLayout window, through a JSON command-line interface:
`python/klayout_em_export/cli.py`, run by KLayout in batch mode. `tools/em_cli.py` starts it from any Python
(no KLayout package needed) and prints the result as JSON:

```bash
python tools/em_cli.py status gds=core.gds cell=Core stackup=SG13G2_FEM_200um.xml pdk=~/IHP-Open-PDK/ihp-sg13g2
python tools/em_cli.py add_via_port gds=core.gds cell=Core stackup=... x=12.5 y=-40 output=core_ports.gds
python tools/em_cli.py devices action=replace gds=core_ports.gds cell=Core output=core_ports.gds overwrite=true
python tools/em_cli.py export gds=core_ports.gds cell=Core out=core_em.gds
```

Arguments are `key=value` (values in JSON where they parse: numbers, `true`, lists), or a whole request as a JSON
file or on stdin: `{"command": "status", "gds": "core.gds", ...}`. Coordinates are in µm. The result is
`{"ok": true, ...}` or `{"ok": false, "error": "..."}`; the exit code is 0 or 1.

| Command | Does |
| --- | --- |
| `status` | The plug-in version (`version`) and what the EM panel shows: stackup and metals, technology, region, ground, ports with their problems, devices, and the export checks (problems, ports left out, renumbering). |
| `add_via_port` | A via port on the metal edge nearest to `x`, `y` (within `tol`, default 0.5 µm), from that metal down to the next metal at the port, as the EM Port tool does. `metal` limits the search, `to`, `z0`, `excited` override. |
| `add_inplane_port` | An in-plane port across the narrowest gap around `x`, `y` (within `reach`, default 20 µm). |
| `set_port`, `remove_port` | Change (`direction`, `from`, `to`, `target`, `z0`, `excited`) or remove port `port`. |
| `set_region` | The EM region box: `box` [x1, y1, x2, y2], or `null` to remove it. |
| `boundary_ports` | Metals crossing the region's edge; with `create: true`, ports on those that need one (Create Proposed Ports); with `port_wall: true`, in-plane ports for a port wall. |
| `mark_ground` | Ground marks: `points` [[metal, x, y], ...]; `clear: true` removes the earlier ones. |
| `devices` | `action`: `list`, `replace` (`resistors`, default true) or `unreplace`. |
| `export` | The EM layout `out` (.gds) with its .simcfg and port map, from `box`, else the EM region, else the whole cell (`whole: true` ignores the region). Same result as the export dialog. |

Every command takes `gds`, `cell` (needed when the file has several top cells), `stackup` (default: the layout's
own), `technology` (default: from the layout) and `pdk`. The layout gets a KLayout technology (`sg13g2`, or
`klayout_technology`) only with `pdk` or `klayout_technology`, never from what the local KLayout has installed, so a
request gives the same result on every machine. Commands that change the layout write it to `output`;
the input is replaced only with `overwrite: true`. The written layout keeps the stackup and the ground marks as meta
info, so the plug-in in KLayout opens it as if the steps were done by hand. The settings file
(`~/.klayout_em_export.json`) is not used.

- **KLayout:** the `KLAYOUT` environment variable, else `klayout` / `klayout_app` on the PATH, else the usual
  Windows install folders. It runs with `-zz -nc -rx`: no window, no configuration, no autorun macros.
- **IHP PDK devices:** the device cells of the IHP PDK library (npn13G2, MOSFETs, ...) are only recognized with
  `pdk` (the `ihp-sg13g2` folder of IHP-Open-PDK, or set `KLAYOUT_EM_EXPORT_PDK`). The library needs KLayout's own
  Python with Qt, which is why the interface runs in KLayout and not in the `klayout` pip package.
- **Create Circuit:** `tools/spice_wrapper.py` is already a command-line program (see above).
