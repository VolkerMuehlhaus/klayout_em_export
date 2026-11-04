# klayout_em_export architecture

How the plug-in is built and why. For agents and developers changing it. The user-facing description is the
[user's guide](userguide/klayout_em_export_userguide.md) and the [README](../README.md); the working rules are in
[AGENTS.md](../AGENTS.md).

## 1. What it is

A KLayout plug-in made for the IHP SG13G2 PDK (SG13CMOS5L too; other processes through a technology module, see
[Technologies](#technologies)). It prepares part of a layout for an EM simulation with gds2palace and
AWS Palace, and afterwards puts the PDK devices back around the EM result for a circuit simulator.

```text
KLayout layout
   |  EM panel / EM menu / EM Port tool          (this plug-in, inside KLayout)
   v
<name>.gds + <name>.simcfg + <name>_portmap.json
   |  setupEM or EMStudio -> gds2palace -> Palace (other repos)
   v
<model>_dc.sNp
   |  Create Circuit -> tools/spice_wrapper.py   (this plug-in, outside KLayout: needs snp2le)
   v
<model>_<simulator>.cir / .inc / .scs: EM model + PDK devices, for ngspice and Xyce / VACASK / Spectre
```

The plug-in never runs gds2palace or Palace itself. Its contract with gds2palace is the exported GDS (layers and
port shapes) and setupEM's `.simcfg` format.

## 2. Runtime

- **KLayout package (salt grain).** `grain.xml` describes the package. KLayout adds `python/` to its module path
  and runs `pymacros/em_export_menu.lym` at startup (autorun). The macro calls `gui.install_menu()` only when there
  is a main window, so batch mode (`-z`) loads nothing.
- **Pure Python inside KLayout.** Everything under `python/klayout_em_export/` uses only `pya` and the standard
  library: no gdspy, numpy or shapely, because KLayout's own Python has none of them. Geometry is `pya.Region`,
  `pya.Box`, `pya.Edges`.
- **Outside KLayout.** `tools/spice_wrapper.py` needs snp2le (vector fitting), which does not live in KLayout's
  Python. Create Circuit runs it as a subprocess with a separate Python (`circuit.default_python`: the
  `snp2le_python` setting, else the Python next to setupEM). It also works from the command line on its own.
- **Tested with** KLayout 0.29.4 on Windows and 0.30.12 on Linux; `api-version` in `grain.xml` is 0.28.
- **Version:** in `grain.xml` (KLayout's package manager) and `__version__` in `python/klayout_em_export/__init__.py`,
  kept equal (`test_version.py`); the EM panel's title and the CLI's `status` show it. Raise both together.
- **PDK.** Device recognition needs the SG13G2 PDK library (`SG13_dev`) loaded in KLayout. Static device cells
  (exported from Cadence, `<device>_CDNS_<number>`, or saved without pcell context, `<device>$<number>`) are
  recognized by name; an npn's parameters come from its `Ae=Nx*Ny*we*le` label.

## 3. Module map

Core modules work on `pya.Layout` and `pya.Cell` without any GUI, so the batch tests can drive them. The GUI
modules only collect input and call the core.

| Module | Role |
| --- | --- |
| `stackup.py` | Reads a gds2palace stackup XML: the GDS layers the EM model reads (derived layers replaced by their source layers), metal names, z positions (`is_above`; applies `<Substrate Offset>`; `unresolved()` lists metals and vias whose height is a variable, which the panel warns about). A small parser of its own, because KLayout's Python cannot import gds2palace; `test_stackup_drift.py` guards it against gds2palace's reader. |
| `locate.py` | Finds metals at a point or port shape: `edge_at` (via port), `gap_at` (in-plane port), `metals_at`, `next_port_layer`. |
| `ports.py` | Port settings as a shape property (`PortSettings`), collecting ports, checks, export numbering, via port directions, the `.simcfg` port list, the port map. |
| `connectivity.py` | Traces metal through vias: the ground net (`check_ground`), shorted via ports, the net of each port (`port_nets`). Vias are traced as blocks (`via_blocks`). |
| `dummyfill.py` | EM > Remove Dummy Fill: floating, repeated shapes on the stackup's conductor and sheet layers (any datatype), never on via layers; deleted where they are, tile cell placements one by one, empty or unplaced cells deleted. |
| `density.py` | EM > Fill Density Holes and Merge Metal: density holes (cheesing) filled with gds_prepare_for_EM's hole rule, then each metal layer of the cell merged, with the metal of plain subcells placed twice or more or holding filled holes (`plain_cells`). |
| `boundary.py` | Where conductors cross the EM region box: proposed via ports on the cut. |
| `devices.py` | Finds PDK devices (through the technology) and replaces them by a REF patch and via ports; the device shapes the export removes. |
| `tech/` | The PDK specifics, one module per technology (see [Technologies](#technologies)): `ihp_sg13.py` (which cells are devices, their terminals, the device level for the ground check, panel texts; needs pya), `ihp_sg13_circuit.py` (device models, terminal order and model libraries for the circuit wrapper; plain Python, imported by `tools/spice_wrapper.py`), `generic.py` / `generic_circuit.py` (no device support). `tech.for_layout` chooses the technology. |
| `selection.py` | The selected shapes, flattened, completed with connecting vias and touching port shapes. |
| `export.py` | Writes one flat cell with only the stackup's layers and the port layers, clipped and merged. |
| `simcfg.py` | Writes or updates setupEM's `.simcfg`. |
| `thermal.py` | The thermal export for setupThermal / gds2palace's Elmer thermal mode: the devices stay as drawn, each gets one heat source (the technology's `heat_area`) on a marker layer of its own; writes the `.tsimcfg` and `_thermalmap.json`. See [Thermal export](#thermal-export). |
| `lvs.py` | The schematic instance names of the heat sources, from a KLayout LVS database (`.lvsdb`). |
| `modelcheck.py` | Finds model scripts that read an exported GDS but have other ports (stale after a re-export). |
| `pipeline.py` | The workflow without the GUI, as data: `export_em` (the whole export), `export_checks` (what the export dialog reports), `layout_devices`, `region_ports`, the `NoUndo` view stand-in, the meta info keys. Reads no settings file: the caller passes stackup, ground marks and technology. Used by `gui.py`, the batch tests and `cli.py`. |
| `cli.py` | Headless JSON interface, run by KLayout in batch mode (`-zz`); one command per request (status, ports, region, ground, devices, export, export_thermal). Writes changed layouts to an explicit output file, never the settings file. |
| `tools/em_cli.py` | Plain-Python launcher for `cli.py`: finds KLayout, passes the request, prints the result. |
| `gui.py` | Menu, dialogs (export, port settings), persistence (layout meta info and settings file), setupEM / EMStudio launch (`open_simcfg`, `launch_command`). |
| `panel.py` | The docked EM panel: the workflow as a checklist (Stackup, Region, Ground, Devices, Ports). |
| `tool.py` | The EM Port tool (`pya.Plugin`): hover preview, click for a via port, Shift+click for an in-plane port. |
| `circuit.py` | Create Circuit dialog; runs `tools/spice_wrapper.py`. |
| `tools/spice_wrapper.py` | Port map + `.sNp` -> netlist with the PDK devices, per simulator. |
| `tools/make_icon.py` | Draws the EM Port tool icon. |

### Technologies

Everything that knows a PDK, apart from the stackup, is in `tech/`. The rest of the plug-in works with any
gds2palace stackup.

- **Choosing one** (`tech.for_layout`, `gui.layout_technology`): the `technology` entry of the settings file, if
  set; else the first technology whose devices are in the layout (`devices_in`: IHP: a cell of the `SG13_dev`
  library, also when the library is not loaded, or a static device cell `<device>_CDNS_<n>` / `<device>$<n>`); else the first whose
  KLayout technology name the layout has (`KLAYOUT_TECHNOLOGIES`); else `generic`. The Devices line's tooltip shows
  the technology and why. Devices decide before the KLayout technology name because a GDS is often opened without
  choosing a technology, and the stackup is not used because nothing in it names the process.
- **generic**: no devices; they stay in the EM model as drawn layout. Its ground check leaves out only the known
  technologies' device levels.
- **IHP SG13G2 and SG13CMOS5L share `ihp_sg13`**: the same library `SG13_dev`, the same pcells (no npn in
  SG13CMOS5L), the same layer numbers and model libraries (IHP-Open-PDK `dev` branch, November 2026). They differ
  in the stackup only. A process with a library of its own (e.g. a future SG13Cu) is a technology of its own; it can
  import `ihp_sg13`'s terminal finders where its pcells draw the same pins.
- **Port map**: the export writes `technology`; `tools/spice_wrapper.py` loads `tech/<technology>_circuit.py`. A
  port map without it is from an older export and counts as `ihp_sg13`.

#### Adding a technology

1. `tech/<name>.py` with the interface of `ihp_sg13.py` / `generic.py`: `NAME`, `LABEL`, `KLAYOUT_TECHNOLOGIES`,
   `DEVICE_LEVEL` (stackup names of the diffusion and every other layer below the wiring that would join nets),
   `NO_DEVICES`, `devices_in(layout)`, `context`, `identify`, `is_device`, `is_resistor`, `terminals` (fill
   `device.terminals` as `{name: (GDS layer of the pin metal, [pin boxes])}`), `describe` (the panel's Value
   column: size or value), `resistor_note`.
2. `tech/<name>_circuit.py`, plain Python: `NAME`, `PDK_LABEL`, `PDK_HINT`, `PDK_BROWSE_TITLE`, `LIBRARIES`,
   `SPECTRE_NOTE`, `VACASK_HEADER`, `pcell_of`, `lib_path`, `instantiate` (the subcircuit or model per device with
   its terminal order).
3. Add the name to `tech.TECHNOLOGIES`.
4. A gds2palace stackup for the process, with a `REF_FOR_TRANSISTOR` sheet (layer 300) if devices are to be
   replaced.
5. Tests: copy `test_devices.py` / `test_resistors.py` for its devices, and add its cases to
   `test_technology.py`.

## 4. What the plug-in stores in the layout

All of it survives a GDS round trip, so a saved layout keeps its EM setup.

| What | Where | Format |
| --- | --- | --- |
| Port shape | layers 201..299, datatype 0, without the stackup's own layers in that range (SUBGND 210 or 250, BACKSIDEGND 251) | via port: zero-width box along an edge; in-plane port: box across a gap. Port number = layer − 200. |
| Port settings | GDS property 200 on the port shape | `port:dir=-Z;from=Metal3;to=TopMetal2;z0=50;v=1` (via port) or `port:dir=X;target=Metal5;z0=50;v=1` (in-plane). Kept short: some GDS tools cut values after 126 characters. |
| Boundary port tag | GDS property 201 | `boundary`: made by Create Proposed Ports, found again when the box moves. |
| Device tag | GDS property 202 on the REF patch (`device:<id>`) and the ports (`device:<id>:<terminal>`) of a replaced device | The id is `<cell name>@<x>,<y>` (dbu), so it changes when the device moves: the old ports and patch are then orphaned, reported by `devices.orphaned_tags` in the Devices step and the export dialog. Undo Replace removes everything with this tag. |
| REF patch | layer 300 (REF_FOR_TRANSISTOR in the stackup) | one box per replaced device: its pins' bounding box + 0.2 µm. |
| EM region box | layer 800/0 | one box; Mark EM Region from Selection replaces it. |
| Stackup, last output, ground marks | layout meta info `klayout_em_export.stackup`, `.output`, `.ground` (JSON `[[layer, x, y], ...]` in dbu) | persisted meta info. |

KLayout writes persisted meta info into a hidden `$$$CONTEXT_INFO$$$` cell of the GDS file (other tools may list it as
an empty top cell); the export's `_em.gds` has no meta info and no such cell. The user's guide (Reference) tells
designers how to remove the EM setup before passing a layout on.

GDS keeps only integer property keys, so all keys are integers. Persisted meta info does not mark the layout as
modified, so KLayout does not offer to save it. `gui.set_layout_value` therefore mirrors each value into
`~/.klayout_em_export.json`, keyed by the layout file, and `gui.layout_value` reads the layout first, then that
file. The same file keeps the global choices (last stackup, last port settings, setupEM program, Create Circuit
settings).

## 5. From layout to export

`pipeline.export_em` is the whole flow; `gui.export_region` adds the dialog (region, output file, stackup), the
settings file and opening setupEM / EMStudio, and `cli.py` the request handling. The steps:

1. **Region** (`gui.region_source`): the selection, else the EM region box, else the whole cell. With a selection,
   the default is "selected shapes only": `selection.Selection.completed()` adds the vias that land on two selected
   metals, the port shapes touching selected metal, and the REF patch of each replaced device whose ports are in
   the selection, because they are easy to miss when selecting.
2. **Ports** (`ports.collect_ports` or `ports_of`) inside the region.
3. **Numbering** (`ports.export_numbering`): complete ports 1..N in layout order, then incomplete ones, on the
   available port layers in order.
4. **Device shapes** (`devices.device_shapes`): the shapes of replaced devices below their pins, removed from the
   export.
5. **Write the GDS** (`export.export_flat`): flat, only stackup layers and port layers, metal merged per layer and
   cut at the box, port shapes copied unchanged (zero-width lines would not survive merging), dropped layers
   reported.
6. **Nets and directions** (`connectivity.check_ground`, `port_nets`, `ports.export_directions`): each port's net
   and signal layer; each via port gets `Z` or `-Z` so its signal metal is on the same end as for all others.
7. **Write `<name>.simcfg`** (`simcfg.write_simcfg`) with the complete ports only, and **`<name>_portmap.json`**
   (`ports.port_map`).
8. Optionally open the `.simcfg` in setupEM (`setupEM -simcfg <file>`) or EMStudio (`EMStudio <file>`), as chosen in
   the export dialog (`open_with`). EMStudio imports it as a Palace or OpenEMS model (it asks which), or, when
   `<name>.py` exists next to it,
   updates only that model's ports, layout file, stackup, cell and purpose (EMStudio's `simcfgimport.cpp`). The
   `.simcfg` stays the one contract for both programs; the plug-in writes no EMStudio-specific file. The export
   does not know the solver: device replacement and the stackup are Palace choices, and an OpenEMS model needs
   an export without replaced devices and with a gds2openEMS stackup. Nothing enforces that (the user's decision,
   2026-10-31: no layer-name checks in EMStudio).

### Output files

- **`<name>.gds`**: one cell, the stackup's GDS layers (derived layers by their sources) and the renumbered port
  layers.
- **`<name>.simcfg`**: setupEM's format (`application: setupEM`, `saved_values` with `GdsFile`, `SubstrateFile`,
  `cellname`, `purpose`, `unit`; `ports` as setupEM stores them). A new file has only these; setupEM fills the
  rest from its preferences. An existing setupEM file is updated: files, cell, purpose and ports are replaced,
  everything else (frequencies, mesh, ...) is kept.
- **`<name>_portmap.json`**: per exported port: `port` (number in the `.simcfg` and `.snp`), `layer`,
  `layout_port`, `layout_layer`, `in_simcfg`, `settings`, and when known `direction`, `device`, `terminal`, `net`,
  `ground_net`, `signal_layer`. Plus `devices`: pcell and parameters of each replaced device. This file is the
  only link between the `.snp` and the devices for Create Circuit.

## 6. From EM result to circuit

`circuit.create_circuit` shows the dialog and calls `circuit.run_wrapper`, which runs

```text
<python with snp2le> tools/spice_wrapper.py <portmap> <model>_dc.sNp -o <out> --simulator <sim> --em fit|snp [--pdk <ihp-sg13g2>]
```

`spice_wrapper.build` makes a simulator-neutral `Circuit` from the port map: subcircuit pins = ports of no device,
one device instance per replaced device (parameters from the port map; a static Cadence resistor becomes an ideal
resistor of its label value), 1 mH ties per net, 1 µF DC blocks when the `.sNp` has no 0 Hz point. The writers
(`write_spice` for ngspice and Xyce, `write_vacask`, `write_spectre`) turn it into a netlist.

| Simulator | EM model | Why |
| --- | --- | --- |
| ngspice | snp2le equivalent circuit (default, only choice) | ngspice has no N-port Touchstone element (XSPICE `xfer` is a transfer function for AC). |
| VACASK | snp2le equivalent circuit in VACASK format | no Touchstone import yet. PDK primitives are loaded from `.osdi` modules; the PDK libraries are found through `.vacaskrc.toml`. |
| Xyce | `.sNp` via `YLIN` (default) or snp2le | `YLIN` works in harmonic balance only; in AC and DC Xyce 7.10 treats it as open. snp2le's `noisy=0` is stripped for Xyce. |
| Spectre | `.sNp` via `nport` | untested (no license). |

`tests/simulators/` runs the cascode in ngspice, VACASK and Xyce in the IIC-OSIC-TOOLS image.

### Thermal export

`thermal.export_thermal` writes a model for setupThermal / gds2palace's Elmer thermal mode from the same region:

- **Devices as drawn, one heat source each.** A device's metal, contacts and vias conduct heat, so nothing is
  replaced: no ports, no REF patches (`REF_FOR_TRANSISTOR` and the port layers are left out of the GDS).
- **Heat area from the PDK.** IHP's pcells draw it themselves (`sg13g2_pycell_lib/ihp/thermal.py`): `HeatTrans`
  51/0 over each MOS gate finger and npn emitter (+0.05 µm), `HeatRes` 52/0 over each resistor body stripe;
  `tech/ihp_sg13.heat_area` takes the device's shapes on these layers. A device without them (an older or static
  cell) gets its bounding box, reported in the dialog and the result: a larger area, a lower peak temperature.
- **One power per device.** gds2palace takes one power per marker layer and spreads it over the volume of all its
  polygons (Elmer `-distribute`), so a device's fingers share it by area. A circuit simulation gives one power per
  device, not per finger.
- **In the z range of `HEAT_TARGET`** (IHP: `Activ`, a slab on top of EPI): the stackup layer nearest to where the
  heat is generated that has a thickness. The export stops if the stackup lacks it or it has no thickness.
- **Marker layers from 201 upward**, skipping every layer the stackup uses (also derived and boundary layers),
  past 299 if there are many devices: the region outline first, then one per heat source.
- **No boundaries.** No default fits every assembly (backside on a heat sink, flip-chip through bumps, ...): they
  are chosen in setupThermal. The region outline on the first marker layer is geometry a boundary can use.
- **Export again keeps** setupThermal's settings, the boundaries, and for every device still in the region its
  power and schematic instance name (matched by device id through the previous `_thermalmap.json`).

- **Instance names from LVS** (`lvs.py`, optional `.lvsdb`): the layout netlist has each device with its position,
  the cross-reference its schematic device. A layout device belongs to the heat source whose device box contains
  its position and whose LVS class fits (`technology.lvs_classes`: the pcell name, for a MOSFET the deck's base
  model); a substrate tap or capacitor inside a transistor's box does not count. Subcircuits are walked with their
  transformations, so deep and flat LVS runs both work. KLayout's SPICE reader drops element letters and LVS is
  upper case (`Xcore.Q1` is `CORE.1`): the name is rebuilt with X per subcircuit and `technology.lvs_element` for
  the device. LVS may be run on a cell that contains the exported one once (not several times: the names would not
  be unique). Heat sources without an LVS device, or with several of different names, are reported, never guessed.

`<name>_thermalmap.json`: per heat source its marker layer, device id (as in the port map), pcell and parameters,
bounding box, heat area (µm²), polygon count, `from_pdk`, `cut_by_region`, `instance` (the schematic name, for the
powers from a circuit simulation) and `lvs_name` (as in the LVS database), plus the `lvsdb` path. Powers live in
the `.tsimcfg` only; gds2palace's `util_thermal_map` and setupThermal's **Load powers...** set them by name.

## 7. Design decisions

Each with its reason, so a change does not undo it by accident.

### Reference plane at the pcell's pins

The PDK model covers the device up to its pins; the EM model covers everything from there. So a replaced
device's ports sit on its pins, and the export removes the device's own shapes below them: everything below
Metal1, and under a pin on a higher metal also the wiring down to Metal1 (the npn emitter is a Metal2 strip on one
Metal1 island per finger, joined by Via1). The device's other metal and the user's shapes stay.

### One REF patch per device, sized to its pins

Each replaced device gets its own `REF_FOR_TRANSISTOR` patch under its pins (bounding box + 0.2 µm), not under
the cell's bounding box. The cell box includes implant and buried layers, and the boxes of devices placed side by
side (a cascode) overlap, which would join their patches into one shared reference. The Devices check warns when
two patches touch.

### One port per terminal

A terminal is one port over the whole pin, also for several emitter fingers. MOSFET source and drain on several
fingers are one port with one line per finger (a multielement port: parallel elements of one Palace lumped port).
That needs gds2palace 0.9.3 (merged upstream in PR #91; PyPI still has 0.9.2); older versions use only one line.

### Devices wired directly, DC fixed by 1 mH ties

In the EM model each device's ports end on its floating REF patch, while Palace references every port to ground.
The wrapper wires each device terminal straight to its EM pin. This grounds the patch and adds its capacitance
(about 7 fF per npn13G2 Nx=8; cascode: S21 −0.06 dB at 10 GHz, −0.4 dB at 200 GHz), for a much simpler netlist.

A port measures a voltage difference, so the EM model does not fix a device's absolute DC potential. The ports of
each net (traced through the vias at the export) are tied together, and to ground on the ground net, by 1 mH:
a short at DC, open at GHz. The wires' DC resistance is not modelled.

Rejected or kept only as documented variants: ideal transformers for floating references (hard to read), REF
patches tied to ground in the EM model (dropped), patches on the EPI (`doc/test_cascode_epi_tie`: no ties needed,
but depends on substrate ties in the region and adds wire resistance). Reports: `doc/test_cascode_wrapper`,
`doc/test_cascode_epi_tie`.

### The Palace sweep starts at 0 Hz

With `fstart = 0`, gds2palace simulates 10 MHz and 20 MHz and writes `<model>_dc.sNp` with a 0 Hz point
extrapolated from them; snp2le pins its fit to that point. A 0 Hz point extrapolated from GHz points instead leaks
kΩ to MΩ between nets, which once looked like a problem of snp2le. Without a 0 Hz point the wrapper adds DC blocks.

### Port numbers without gaps, port layers around the stackup

After Palace, `combine_extend_snp` takes the highest port number as the port count and fills missing ports with
|S| = 1. So the export numbers ports 1..N without gaps, and the port map links them back. Port layers skip the
stackup's own layers in 201..299, because SUBGND (210 or 250) and BACKSIDEGND (251) live there.

### Via port polarity: relative, set at the export

gds2palace hands `Z` to Palace as one orientation and `-Z` reverses it; only the relative orientation is verified,
not which end is "+". The export chooses `Z` or `-Z` per via port so that every via port has its signal metal on
the same end, which is what the wrapper assumes. The port map records `direction` and `signal_layer`; a port map
without them is from an older export.

### Ground from the via ports, only wiring traced

The ground net is found without user input: of the nets at both ends of the via ports, the one most ports reach
(on a tie, the larger). Ports of replaced devices do not vote: their only traced end is the device terminal (the
other end is the REF sheet, which is not traced), so they say nothing about ground. With device ports only, no
ground is chosen and the panel asks for a pad port or a marked ground. The user can mark ground instead. Only wiring is traced: stackup conductors above the device
level, through the vias between vertically adjacent metals. Activ and every via touching it are left out, because
tracing through diffusion merges source and drain and so all nets. A device is an open circuit for this check.

The device level is a list of layer names per technology (`DEVICE_LEVEL`), and the check leaves out the names of
all known technologies (`tech.device_level_names`), so it needs no layout. A rule by z position does not work: the
lowest conductor is the diffusion in a stackup with front end, but Metal1 in a stackup without it, and nothing in
the stackup tells the two apart.

### Vias traced as blocks

Tracing tests vias against the growing net, and a large layout has tens of thousands of vias per layer (77k on Via3
and Via4 in a 60 GHz PA): the ground check took 35 s after one port. `via_blocks` replaces the vias of each layer by
the areas where the metal below and above overlap that hold at least one via. A via connects only the two metal
polygons that hold it, and each overlap area lies in one polygon of each, so the blocks connect exactly what the vias
connect (checked from every metal polygon of four layouts), with one polygon per via array: 1.8 s instead. Only
for the checks: the export writes every via, and gds2palace corrects via arrays itself.

### Dummy fill told by what it is

Fill tools differ: IHP's put tiles on a fill datatype (22) as cells placed tens of thousands of times, others draw on
the drawing datatype or flat. So fill is not found by datatype or cell name, but by its nature: it floats (touches
no via of the stackup's via layers above or below its metal, no label, no port, no device or PDK cell) and repeats
(each drawn shape's size is found 20 times or more among the floating shapes; judged per drawn shape, because
abutting tiles merge into large blocks, and a floating structure with one shape of its own size stays). Floating is
judged per datatype, merged with the drawn metal (datatype 0) only: markers on other datatypes are no metal, and
IHP's fill tiles abut its no-fill marker (23), which made all of a 180 GHz PA's Activ fill look connected when all
datatypes were merged. Drawn metal itself is EM model geometry and judged more carefully: a drawn polygon touching a
shape of another datatype stays (in that PA, 22 floating repeated drawn groups next to no-fill markers stay). Via layers
are never searched: a via array is repeated and isolated on its own layer too, which is what a purely geometric rule
such as gds_prepare_for_EM's gds_removefill (with its IHP via list and 1 um minimum size) has to work around. A tile
cell placed thousands of times usually has a few placements touching a via or a label: such a cell keeps those
placements and loses the others (arrays are split into single placements). Layers that are not stackup metals
(GatPoly) are left alone: the stackup does not say what connects to them.

### Holes filled and metal merged in the layout, on request

Cheesed metal (density rule openings) and metal drawn in many pieces are solid to the EM fields but add edges to
mesh and polygons to trace. The layout is converted once, in place, by a menu item (one undo step), not by an export
option: the user sees the result, and the checks and the export need nothing more. The hole rule is
gds_prepare_for_EM's (`gds_simplify_for_em.ground_plane_holes`), ported to KLayout regions, but without its
ground-plane test: any shape on a non-via stackup layer with a hole size found 20 times or more. The merge keeps the
hierarchy where it matters: devices (recognition needs their cells), PDK pcells (KLayout regenerates them), subcells
placed once without filled holes, and subcells also placed outside the cell stay; vias stay single for gds2palace's
via array correction. The result is checked to be exactly the original metal plus the fill (`test_density.py`).
Running gds_prepare_for_EM first is no alternative: it flattens the layout and drops layers the plug-in needs
(devices, ports). The converted layout breaks the density rules: it must never go to tape-out.

### Backup of the original layout

Saving a layout after the plug-in worked on it writes its data (meta info, port shapes with settings, REF patches,
the EM region box, filled and merged metal) into the designer's file. KLayout offers no hook before saving that the
plug-in could rely on, so the backup is made at the plug-in's first change instead: `gui.backup_original` runs in
`set_layout_value` and before every undo transaction (gui, panel, EM Port tool, device and boundary port wrappers).
If the layout holds none of the plug-in's data (`gui.has_em_data`: its meta info, properties 200-202 on the port
layers and the REF layer 300, or the EM region box) the file on disk is still the original and is copied to
`<file>.bak`, never over an existing one (the oldest original stays), once per file and session. Plain port shapes
without settings do not count: gds2palace layouts have those too.

### Resistors replaced by default

The PDK computes R = Rsh·l/(w + Δw) + 2·rz/w. The gds2palace sheet has the drawn size and the nominal Rsh: no width
offset, and of the end resistance only what the Cont vias carry. Palace on the PDK cells as drawn: rhigh and rppd
9 % to 13 % low, rsil within 2 % (`tests/resistor_palace`). So **include resistors** is ticked by default, and an
unreplaced resistor makes the Devices line a warning. Resistors of several segments are not replaced.

### Selections and the panel

A selection means "these shapes", so the export defaults to the selected shapes. That is also why clicking a port
in the panel's table only highlights it with a marker: selecting the port shape would make it the export region.

### Incomplete ports and re-export

Ports without complete settings are exported as shapes but left out of the `.simcfg`, because setupEM cannot load
them. Re-exporting keeps setupEM's own settings in an existing `.simcfg`: the ports always come from the layout,
everything else from setupEM.

The model script (`.py`) that setupEM writes is not updated by a re-export, and it reads the GDS by file name. Run
after a re-export, it would use the new layout with its old ports, which may have been renumbered; Create Circuit
would then wire the devices to the wrong ports, without any error. So the export reads the scripts next to the GDS
and in setupEM's `sim_path` with `ast` (`modelcheck.py`, never run) and warns about each one whose ports differ.
A hand-edited script keeps its code through setupEM's preserve mode (Edit *.py model in place), but setupEM cannot
yet take the new ports from the `.simcfg` there: loading a `.simcfg` ends preserve mode, so the ports are set in
the Ports tab by hand.

When the export opens EMStudio, the EMStudio model `<name>.py` next to the `.simcfg` is left out of that warning
(`gui.updated_on_open`): EMStudio's import replaces its ports with the exported ones right away.

## 8. Tests

There is no test runner: each test is a KLayout batch script (`klayout_app.exe -z -nc -rx -r tests/<test>.py`),
with inputs and outputs from environment variables. Several read layouts outside the repo; `tests/testpaths.py`
finds them on Windows and Linux (`KLAYOUT_EM_EXPORT_TESTDATA`, `GDS2PALACE`, `OUT`). The device tests need the PDK
through `klayout_em_export_tests/pdk_env.py`.

| Area | Tests |
| --- | --- |
| Export, selection, simcfg | `test_export.py`, `test_selection.py`, `test_simcfg.py`, `test_modelcheck.py` (the last two also plain Python) |
| Thermal export | `test_thermal.py`: the cascode, one heat source per device equal to the PDK's heat shapes, marker layers past 299 around the stackup's, no ports or REF patches, export again keeps powers, boundaries and instance names; names from IHP's LVS deck, flat and with a subcircuit (PDK and `klayout_em_export_tests/testcases/lvs_cascode` needed) |
| Version | `test_version.py` (plain Python): `grain.xml` and `__version__` agree (the EM panel's title shows it), the user's guide names it |
| Stackup parser | `test_stackup_drift.py` (plain Python): z positions against gds2palace's `util_stackup_reader.py` for every stackup in the sibling repos `gds2palace_ihp_sg13g2` and `EMStudio` |
| Ports | `test_ports.py`, `test_locate.py`, `test_numbering.py`, `test_portlayers.py`, `test_boundary.py` |
| Ground and nets | `test_ground.py`, `test_unconnected.py`, `test_density.py` (Fill Density Holes and Merge Metal: the rule, what is merged and what stays, exact geometry on the FMD layouts if present), `test_dummyfill.py` (Remove Dummy Fill: what is fill and what stays, vias and devices unchanged on the FMD layouts) |
| Devices | `test_devices.py`, `test_mosfets.py`, `test_resistors.py`, `test_replaced_devices.py` (selection patches, ground voting, moved devices) (PDK needed) |
| GUI pieces in batch | `test_panel.py`, `test_reopen.py` (stand-in view, own settings file), `test_open_with.py` (setupEM / EMStudio command line, which stale scripts are reported), `test_backup.py` (backup of the original layout: when, and when not) |
| Technologies | `test_technology.py` (choice and generic fallback, SG13CMOS5L stackup, wrapper per port map technology) (PDK needed) |
| Create Circuit | `test_circuit.py` (needs a Python with snp2le), `tests/simulators/` (Docker, Linux) |
| Physics checks | `tests/resistor_palace/` (Palace), `doc/test_cascode_wrapper`, `doc/test_cascode_epi_tie` |
| Example exports | `run_cascode_export.py`, `run_cascode_epitie_export.py`, `run_mpa_core_export.py` (through `pipeline.export_em`, as the GUI) |
| Headless interface | `test_cli.py`: every command of `cli.py`; the cascode exported through the CLI equals `export_em` called directly (PDK needed) |

The GUI itself (EM Port tool, dialogs) is checked with the user's guide capture
(`doc/userguide/capture/capture.py`, run in KLayout with a window), which drives the real plug-in through the
guide's steps.

## 9. Documentation build

- User's guide: `doc/userguide/klayout_em_export_userguide.md`, screenshots by `doc/userguide/capture/`
  (`capture.py` in KLayout, `capture_setupem.py` in the palace venv, `figures.py`, `set_dpi.py`), PDF by
  `doc/pdf_build` (pandoc → Typst) with `--chapter-pagebreak`.
- `doc/pdf_build` is a copy of the one in gds2palace and gds2openEMS. This copy has two additions the others lack:
  the `--chapter-pagebreak` option and sticky chapter headings. Sync by hand.
