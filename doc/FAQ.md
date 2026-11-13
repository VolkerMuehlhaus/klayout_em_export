# klayout_em_export FAQ

Questions RFIC designers ask when they first set up an EM simulation from KLayout with this plug-in. Each answer
gives the reason first and then what to do; the step-by-step instructions with screenshots are in the
[user's guide](userguide/klayout_em_export_userguide.md), every panel line, menu item and rule in the
[reference](REFERENCE.md). For the EM solver side (mesh, boundaries, Palace runs), see the
[gds2palace FAQ](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2/blob/main/doc/FAQ.md).

## Contents

[Getting started](#getting-started)  
[Your layout file](#your-layout-file)  
[Stackup and layout clean-up](#stackup-and-layout-clean-up)  
[Choosing the region](#choosing-the-region)  
[Ground](#ground)  
[Ports](#ports)  
[Port walls and de-embedding](#port-walls-and-de-embedding)  
[Transistors and resistors](#transistors-and-resistors)  
[Splitting a large region into pieces](#splitting-a-large-region-into-pieces)  
[Export and setupEM](#export-and-setupem)  
[Back to the circuit](#back-to-the-circuit)  
[Thermal](#thermal)  
[Scripts and AI agents](#scripts-and-ai-agents)  
[The KLayout window](#the-klayout-window)

## Getting started

### What does the plug-in do, and what does it not do?

An EM simulator computes metal and dielectric, but not a transistor. A circuit simulator computes the transistor
with its PDK model, but not the wiring you drew. At mm-wave frequencies you need both. The plug-in prepares the
part of your layout that matters for the EM simulation: it places the ports, replaces transistors and resistors by
ports at their pins, checks ground and shorts, and exports a clean flat layout with a settings file for setupEM. After
the simulation, Create Circuit puts the PDK devices back around the EM result, for your circuit
simulator.

It does not run the EM simulation itself (that is Palace, set up in setupEM, or openEMS), and it does
not change the stackup or the solver settings.

### What do I need to install?

KLayout 0.29 or newer with the IHP SG13G2 PDK, the plug-in in KLayout's `salt` folder (next question), and a Python
environment with `pip install setupEM snp2le`. Palace runs on Linux; on Windows, setupEM hands the run to WSL or to
a Linux machine. The [user's guide](userguide/klayout_em_export_userguide.md#installation) has the table, and the
[README](../README.md) lists which versions of gds2palace and setupEM each feature needs.

### What is "salt", and can I install the plug-in from KLayout's package manager?

Salt is KLayout's name for its add-on packages. KLayout loads every package it finds in the `salt` folder in your
home directory (`~/.klayout/salt/` on Linux, `%USERPROFILE%\KLayout\salt\` on Windows) at every start; a package
is a folder with a `grain.xml` that describes it.

Yes: KLayout's package manager (**Tools > Manage Packages**) installs packages from a central index, the Salt Mine,
and offers their updates. In the tab **Install New Packages**, select **klayout_em_export**, mark it and press
**Apply**, then restart KLayout. The package manager installs only the plug-in: setupEM, gds2palace and snp2le still
come with pip, and Palace separately.

For development, a git clone linked into the `salt` folder takes the place of the package. Don't use the package
manager for the plug-in on such a machine: an install or update replaces the folder and can delete the clone through
the link.

### Does it work for other technologies than SG13G2?

Partly. SG13CMOS5L works like SG13G2. For any other technology, ports, the region, the checks and the export work
with any gds2palace or gds2openEMS stackup, because they only need the stackup's layers. Recognizing transistors and
resistors, and putting them back in Create Circuit, needs a technology module that knows the PDK's device cells;
today there is one for the IHP SG13 PDKs. Other layouts get the generic module: devices stay as drawn metal.

### Palace or openEMS?

Both get the same export. For Palace, open it in setupEM. For openEMS, write the gds2openEMS model script yourself:
it reads the exported layout, and the `.simcfg` lists each port's layers and direction (user's guide, chapter 11).
Two things differ:

- **The stackup:** choose one made for the simulator, from gds2palace for Palace, from gds2openEMS for openEMS. They
  model some layers differently, e.g. the MIM dielectric.
- **Devices:** replace them only for Palace. Device ports end on a reference layer that only the Palace stackups
  have.

The plug-in cannot tell which simulator you will use, so check both before the export.

## Your layout file

### Does the plug-in change my layout?

Only when you ask it to, and only by adding its own data: port shapes (layers 201..299), the REF patches of
replaced devices (layer 300), the EM region box (800/0), and settings as GDS properties and layout meta info. The
clean-up commands (Remove Dummy Fill, Fill Density Holes and Merge Metal) do change your geometry; see below.

### Is my original file safe?

Yes. The first time the plug-in changes a layout that has none of its data yet, it copies the file as it is on disk
to `<name>.gds.bak`. An existing `.bak` is never replaced. You can also let KLayout keep backups of every save
(File > Setup > Application > General).

### What is the empty `$$$CONTEXT_INFO$$$` cell other tools show?

KLayout stores the plug-in's meta info (stackup, last export, ground marks) in that hidden cell. KLayout writes it
anyway for every layout with PCells. Other GDS tools may show it as an empty top cell; it holds no geometry.

### Can I tape out a layout I prepared for EM?

Not as it is. Remove the EM setup first: the shapes on the port layers, on layer 300 and on 800/0, and the meta info
(the user's guide, [Stored in the layout](userguide/klayout_em_export_userguide.md#stored-in-the-layout), has a
short script for the meta info). A layout
converted with **Fill Density Holes and Merge Metal** must never be taped out: the filled holes break the density
rules. Use the original.

## Stackup and layout clean-up

### Which stackup file should I choose?

The one of your technology and simulator, e.g. `SG13G2_FEM_200um.xml` from gds2palace's `XML_stackup/latest/IHP/`
for Palace. The stackup tells the plug-in which layers are metals and vias, how high they are, and which layers to
export. It is stored with the layout and used as the default for the next layout you open.

### Do I need to remove the dummy fill?

For the view, usually yes: tens of thousands of fill tiles clutter the layout and slow down the checks. For the EM
model, it depends on where the fill is drawn. Fill on its own datatype is not exported anyway. Fill on the drawing
datatype is floating metal in the EM model, with its coupling capacitance.

**EM > Clean Up Layout > Remove Dummy Fill** removes metal that floats (no via, label, port or device touches it)
and repeats (its size occurs at least 20 times among the floating shapes). Vias, single floating shapes such as a
shield, and devices stay. It is one undo step.

### What does Fill Density Holes and Merge Metal do, and when do I use it?

Density rules put many small openings into wide metal. To the EM fields that is solid metal, but every opening adds
edges the mesh must follow. The command fills openings whose size occurs at least 20 times (other openings belong to
your circuit) and merges the metal into as few polygons as possible. On the 60 GHz PA of the examples: 2899 metal
polygons before, 387 after.

Run it once, before you place ports, and on a copy if you are unsure: a layout saved after it must not go to
tape-out.

### Why does the export say some layers are left out?

The export writes only the layers the stackup knows. Everything else (implants, markers, text layers, fill
datatypes) has no meaning in the EM model. The export dialog lists what was left out, so you can check that no
metal you need is among it.

## Choosing the region

### Do I simulate the whole chip?

Rarely. EM simulation time grows quickly with the size of the region. Simulate the core with the wiring that
matters at RF, e.g. the transistors, their matching and the lines to the pads. Where the region cuts a wire, the
plug-in proposes a port, so the cut wire does not simply float.

### How do I set the region?

Three ways, in order of precedence: a selection (the export offers the selected shapes, or everything in their
bounding box), the EM region box on layer 800/0 (saved with the layout), or else the whole cell. For the box, use
**Region from Selection**, or draw it with the **EM Region** tool: drag a rectangle; it snaps to the grid.

### Mark Region from Selection does nothing useful with my PDK inductor or a hierarchical layout. What now?

A click often selects a whole instance, and its bounding box is not the region you want. Draw the box instead with
the **EM Region** tool. Also check the **Region** line in the panel: it names the cell the export takes. If it says
"the instance you descended into", you are inside an instance (Descend), and the box and the export would be of that
cell; Ascend first.

### Why is a metal cut by the region not proposed as a port?

Two reasons. A metal that is marked or found as ground needs no port: it is the reference. And a metal that covers a
whole side of the box is a plane, not a line, so it is never proposed. If the Ground line says "not found", every cut
metal counts as signal and the list is long: mark your ground first.

### "signal cut, but no ground metal at the cut": what do I do?

A via port at the cut needs a ground metal next to or under the wire, at the cut. There is none, so the plug-in
cannot place the port. Place it yourself with the EM Port tool, or move the box so that it cuts where ground is
nearby.

## Ground

### How does the plug-in know what ground is?

It traces your metal through the vias of the stackup into nets. Of the nets your via ports reach, the one most ports
reach is ground. That is usually right once the pad ports are placed. You can also mark ground yourself: select its
shapes and press **Mark Selected**, or click it with the **EM Ground** tool (**Mark at Click**). **Use Ports** goes
back to the automatic choice.

### I clicked the ground plane, but only a small part became ground.

A chip's ground plane is often one large shape that enters the region box in several parts, connected only outside
it. A click on the plane, inside or outside the box, marks every part inside the box. Check the Ground line: it
lists the ground metals and how many polygons each has, and **Show in Layout** outlines the ground net in green. If
a part is still missing, click it too.

### "the marked ground is N separate pieces in the region": is that a problem?

It means the ground shapes you marked connect only outside the region. Inside the EM model they are separate
conductors, so a port referenced to one piece does not see the others as ground. Often harmless (a plane split by
the box edge), sometimes a hint that the region is too small. Enlarge the region if the pieces should be one ground
in the simulation.

### "short circuit: both ends of via port(s) ... are on the same net": what does that mean?

The port's two metals are already connected by your layout, through vias, close to the port (within 10 µm, or the
port's own length if that is longer). A port across a short measures nothing useful. Usually the from or to layer
is wrong: the port should end on a metal that is not part of the signal's net, e.g. the ground plane below.

A connection further away is not a short: a balun or inductor winding that is grounded at its other end is a DC
path to ground, but at RF the winding is an inductance, and the port measures it. Such a port is not reported.

## Ports

### Via port or in-plane port?

A **via port** is vertical, between two metals, e.g. from the pad on TopMetal2 down to the ground plane on Metal5.
It is the usual port at a pad and at a wire the region cuts. An **in-plane port** is horizontal, across a gap
between two shapes of one metal, e.g. between the signal and ground strip of a coplanar line, or at a port wall.
With the EM Port tool: click a metal edge for a via port, Shift+click into a gap for an in-plane port.

### Where exactly does a pad port go?

On the edge of the pad metal, as a zero-width line along that edge. The tool highlights the edge under the cursor
and offers only the metals that are drawn there. A new via port goes from the metal you clicked down to the next
metal below it at the port, because a via port must not pass through a metal.

### The tool picks the wrong edge, a large shape covers the one I want.

The tool only looks at visible layers. Hide the covering layer in the layer panel and click again. Hiding a layer
does not limit the port itself: the port dialog still offers every metal drawn there.

### Why are some via ports `-Z` after the export, although I set `Z`?

So that all via ports have their signal metal at the same end. The export finds which end of each via port is the
signal and sets the sign. Create Circuit relies on that orientation when it connects the PDK devices.

### I forgot a port. Can I change the port numbers afterwards?

Yes. A port is the shapes on layer 200 + its number, so a port added later gets the next free number. Right-click it
in the port table: **Move Up** / **Move Down** swaps it with its neighbour, **Set Number...** moves it to a number and
shifts the ports in between by one place. Gaps in the numbering need nothing: the export numbers the complete ports
1, 2, 3, ... without gaps and lists any renumbering.

### How do I simulate a differential port?

As two single-ended ports, one on each line, both to ground. The result stays single-ended; convert it to mixed-mode
(differential and common mode) afterwards, in your circuit simulator or with scikit-rf. For calibrated ports at the
layout edge, put both lines on the same port wall: they are calibrated together, including their coupling.

### A port is marked "not simulated (incomplete)".

Its settings are missing, e.g. a port shape you drew with KLayout's own tools. It is exported as a shape but left out
of the simulation. Double-click its line in the port table, or select it and use **EM > Ports > Port Settings...**.

## Port walls and de-embedding

### What is a port wall, and why would I use it instead of a via port at the cut?

A via port includes its own inductance in the result, which setupEM can only estimate. At a port wall, gds2palace
calibrates the ports instead: the side of the region becomes a metal wall at the layout edge, the ports are in-plane
ports on the cut lines, and two short line standards with the same cross-section remove the port from the result.
The reference plane is then exactly at the wall. Tick **as port walls** before **Create Proposed Ports**.

### When does a port wall work well?

When the lines at the cut are simple:

- **Straight lines, cut at a right angle**, with the same cross-section for a length D into the region. D is the
  span of the lines plus twice their distance to ground; setupEM shows it and warns if a device is closer.
- **Ground metal at the cut**, next to or under the lines. Ground on the same metal is enough, e.g. the ground strips
  of a coplanar line.
- **No cheesing holes at the cut.** The standards copy the cross-section at the wall along their length; a hole in it
  would become a slot. Run Fill Density Holes and Merge Metal first.

### Which result file do I use with port walls?

The `_deembedded` one (or `_dc_deembedded`, with the 0 Hz point). Its ports are calibrated, with the reference plane
at the wall. The raw result still contains the uncalibrated gap ports. setupEM's viewer shows both, Model Fit and
Create Circuit take the calibrated one.

### What are the port wall extension and the reference plane shift in setupEM?

Both move where the result is referenced. The **extension** continues the lines straight outward beyond the layout
edge before the wall, for a cut too close to a bend or device, and the calibration brings the reference plane back to
the layout edge. The **shift** moves the reference plane into the layout along the feed line. Both are set per port
wall in setupEM's Ports tab.

## Transistors and resistors

### Why replace transistors by ports?

The EM simulator cannot simulate a transistor, and the PDK model already contains the device's own parasitics up to
its pins. So the EM simulation should see the wiring up to the pins and leave the device to the circuit simulator.
Each transistor gets a small reference sheet under its pins (the REF patch) and one via port per terminal, from the
pin metal down to that sheet. At the export, the device's own metal below the pins is removed, so nothing is counted
twice. Create Circuit connects the PDK model at those ports again.

### Which devices are recognized?

The SG13_dev PDK cells of IHP SG13G2 and SG13CMOS5L: npn13G2 and its variants, nmos and pmos (and the HV variants),
and the resistors rsil, rppd and rhigh. Static device cells are recognized too: cells exported from Cadence
(`<device>_CDNS_<n>`) and PDK cells saved without their pcell context (`<device>$<n>`, as fill tools write them).
Capacitors and inductors are never replaced: they are metal, and the EM simulation computes them.

### A device says "cannot be replaced: no parameters".

A static cell has the device's shapes but not its pcell parameters, which Create Circuit needs for the PDK model. The
plug-in reads them where it can: a resistor's value from its label, an npn's size from its `Ae=Nx*Ny*we*le` label, a
MOSFET's w, l and ng from its drawn gates (GatPoly over Activ). The Value column says "from the drawn gates" then.
Without that information, the device stays as drawn.

### Should I replace the resistors too?

Yes, that is the default. The PDK computes a resistor's value with a width offset and an end resistance at each
contact head; a sheet of the drawn size has neither. Simulated as drawn, rhigh and rppd come out about 10 to 13 %
low in the guide's examples (e.g. rhigh 0.655 µm × 1.245 µm: 2997 Ω in the PDK, 2599 Ω in the EM model). Replaced,
the resistor is the PDK model in the circuit, with its temperature behaviour.

### Can I replace only some devices?

Yes. Select rows in the device table and right-click: **Replace N Selected** or **Undo Replace of N Selected**. Leave
a device as drawn when it is not on the EM signal path, e.g. a bias transistor far from the RF lines. Such a device
is simulated as its drawn metal only, and Create Circuit does not put it back: keep it in your schematic outside the
EM block.

### My design has hundreds of devices. Are they all replaced?

Only those in the region. With an EM region box, the Devices line counts and Replace All replaces only the devices
that reach into the box. That matters beyond speed: each terminal takes one port layer, and there are only 99.

### "pair(s) of REF patches touch" / "terminal(s) not connected": what now?

Touching patches would give two devices one shared reference, so their ports would be connected through it; move
the devices apart or check the layout. A terminal that is not connected has no wiring inside the region, so its port
would measure an open end; enlarge the region or check the wiring.

## Splitting a large region into pieces

### When should I split the region?

When the region is large, or when you change one part often. Each piece is simulated as its own model, and setupEM
joins the results into one result of the whole region. Only the pieces you change are simulated again.

### Why is the join exact, and what does it miss?

Where two pieces meet, each line crossing the cut gets a port wall port in each piece, both calibrated with their
reference plane on the cut, so the two results connect at the same plane. What it misses: coupling between the
pieces other than through those lines. The cut is a metal wall in both pieces.

In the validation with a 600 µm coplanar line on TopMetal2, and with two single-turn inductors in series on a
TopMetal2 microstrip over a Metal1 plate, the joined result matched the full model at the level of the full model's
own mesh noise.

### Where should I cut, and where not?

Cut across simple feed lines, like any port wall: straight, the same cross-section for at least D on both sides, no
device closer than D, and ground metal at the cut. Do not cut between parts that couple (two inductors side by side
do not see each other in the joined result), and not where a line's return current flows in the substrate instead of
in ground metal: the wall changes that current. The boxes must fill a rectangle together.

### Can a piece have a finer mesh?

Yes. All pieces share the settings of the whole region (frequencies, mesh, solver, boundaries); a cut is a port wall
in both pieces. In setupEM, tick **Own mesh settings for p2** in the Mesh tab for one piece with its own mesh.

### How do I check a split?

Tick the **full (check)** row in setupEM's model list once: the whole region as one model, next to the joined
result. Compare the two before you rely on the pieces.

### I reopened the layout and the pieces are gone.

The boxes are part of your layout, so they are lost if you did not save it (e.g. a read-only layout). **Import
Pieces...** in the Region details takes the boxes, their names and the ground marks from the earlier export's
.simcfg. It also works for a new revision of the design; because the names stay the same, setupEM reuses the
results of the pieces that did not change.

## Export and setupEM

### What does the export write?

Three files with the same name: the flat layout (`<name>_em.gds`, stackup layers and ports only), setupEM's settings
(`<name>_em.simcfg`) and the port map (`<name>_em_portmap.json`: which port is which pad or device terminal, and on
which net). A split region adds a folder `<name>_em_pieces` with one model per piece.

### I changed the layout. What happens to my setupEM settings?

Export again: everything you set in setupEM (frequencies, mesh, ...) stays; layout, stackup and ports are updated.
If you run an older model script from setupEM, it reads the new layout with its old port list, and port numbers may
have shifted. The export warns about each such script; open the export in setupEM and choose **Continue with the
script**, which takes the new ports and keeps your settings.

### Why should the frequency sweep start at 0?

For a circuit with bias, the EM result needs a good 0 Hz point: the DC connections of your wiring. With fstart = 0,
gds2palace simulates two low frequencies in addition and writes `<model>_dc.sNp`, with a 0 Hz point from them. A
sweep that starts at 1 GHz or above extrapolates the DC point too far for a bias network with kΩ resistors.

### Can I run Palace on Windows?

Palace itself runs on Linux. setupEM on Windows writes the model and hands the run to WSL or to a Linux machine; see
the gds2palace documentation for `run_palace` and the containers.

## Back to the circuit

### What does Create Circuit give me?

One subcircuit for your circuit simulator: the EM model with one pin per port, the PDK models of the replaced
devices connected at their ports, and the pads and other ports that belong to no device as the subcircuit's pins.
For ngspice, VACASK and Xyce the EM result goes in as an equivalent circuit fitted by snp2le; for Spectre (and Xyce
harmonic balance) as the S-parameter file itself.

### Why are there 1 mH inductors in the circuit?

A device port measures between a device pin and its REF patch, and the patch has no DC connection to anything. So
the EM result alone does not tell the circuit simulator at which DC potential a transistor sits. The inductors tie
each terminal to the rest of its net: shorts at DC, so they carry the bias; open at GHz, so the EM model carries the
signal. The port map tells which ports are on the same net.

### "no 0 Hz point in the .sNp: the EM model is connected through 1 uF DC blocks".

Your EM result has no DC point, so Create Circuit keeps the EM model out of the bias with DC blocks. The circuit
works, but the wiring's DC paths are not simulated. Start the sweep at 0 Hz and use the `_dc` result.

### Which EM result file does Create Circuit want?

The one with the 0 Hz point, calibrated if you have port walls: `_dc_deembedded`, else `_dc`. The dialog presets the
best one it finds next to the export and says which.

## Thermal

### Can I get the temperature of each device from the same layout?

Yes, experimentally. Switch the EM panel to **Thermal**: each transistor and resistor in the region becomes a heat
source, the size of the area where it really heats (the emitter, the gate fingers, the resistor body).
**Export for Thermal...** writes a model for setupThermal. Load the device powers from your circuit simulation, set
where the heat leaves the chip, and Elmer computes the temperatures. With an LVS database, the results carry your
schematic instance names, ready to set as temperature rise in the circuit. Resistor temperatures are not validated
yet.

## Scripts and AI agents

### Can I use the plug-in without the KLayout window?

Yes. `tools/em_cli.py` runs every step headless through a JSON command-line interface: status, ports, region,
split, ground marks, device replacement and export. Each command prints a JSON result and exits with 0 or 1. The
[reference](REFERENCE.md#headless-use-scripts-ai-agents) lists the commands; it is meant for scripts and AI agents as
much as for batch runs.

## The KLayout window

### The EM tool icons are gone from the toolbar.

They are there only while the EM panel is open, so the toolbar is yours again when you work on other things.
**EM > EM Panel** brings the panel and the icons back. The tools are always in the EM menu.

### The EM panel is too small, or in the wrong place.

Drag it where you want it; KLayout remembers the place and size and the plug-in restores them at the next start.

### Where are my settings stored?

With the layout: port settings as GDS properties on the port shapes, the stackup, the last export and the ground
marks as layout meta info. A copy of the stackup, the export paths, the ground marks and your Create Circuit choices
is in `~/.klayout_em_export.json`; the plug-in uses it only when the layout has none of its own. Deleting the file is
safe: you lose the remembered choices, not your layouts' setup.

### The plug-in says something I don't understand.

The [troubleshooting table](userguide/klayout_em_export_userguide.md#troubleshooting) in the user's guide lists the
messages with their meaning and what to do.
