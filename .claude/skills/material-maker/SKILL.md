---
name: material-maker
description: Design a procedural PBR material in Material Maker from a text description (or reference photo), iterate on it visually with mmx, and export it for Unity/URP. Use when the user asks for a texture or material ("make a mossy stone wall", "rusty metal for Unity", "tweak the planks to look older"), or wants to edit, preview or export a .ptex.
---

# Material Maker: make a material from a description

You build a `.ptex` graph (JSON), export it with Material Maker through `agent_tools/mmx.py`,
look at the contact sheet, and repeat until it matches the request. Everything runs from the
repo root: `/Volumes/External1/Users/bryan/Documents/Material Maker Agent/material-maker`.

**When to use:** the user asks for a texture or material in words or with a photo ("dry cracked desert
ground", "rusty metal for Unity"), wants an existing `.ptex` changed, previewed or exported to Unity, or asks
why a Material Maker graph looks wrong. Not for editing Material Maker's own GDScript (that's normal coding).

Reference, read on demand (don't inline them into your context all at once):
- `agent_docs/NODES.md`: .ptex primer + ~65 curated node types with ports and parameters.
  `python3 agent_tools/mmx.py node <type>` prints any of the 411 types as JSON.
- `agent_docs/examples_annotated.md`: four example graphs explained node by node.
- `agent_tools/README.md`: mmx commands, validation codes, export/sheet details.

## The loop (cap: 8 iterations; stop earlier when it matches)

1. **Restate the request** as 3–6 checkable traits: macro shape/pattern, colour palette, surface
   relief, roughness/metal, style (realistic vs stylized), scale (how many features per tile).
2. **Start from the closest existing graph**, never from an empty file. Look in
   `material_maker/examples/*.ptex` (list them; names are descriptive: `dry_earth`, `wooden_floor`,
   `wood`, `rusted_metal`, `stone_wall`, `tiles`, `marble`, `metal_pattern*`, ...) and
   `agent_docs/examples_annotated.md`. Copy it to `agent_runs/<run>/<name>.ptex`; the output files
   are named after the ptex basename. Run it once unchanged as the baseline (iteration 1).
3. **Edit one or two things** per iteration with a small Python script (keep it as
   `agent_runs/<run>/edit_NN.py` so the change is reproducible). Helpers worth copying:
   `agent_tools/proto_0.3/g.py` (`Graph(path).set(node, **params)`, `.add(name, type, **params)`,
   `.wire(from, port, to, port)` which replaces whatever fed that input, `C(r,g,b)`, `G(...)`).
4. **Validate**: `python3 agent_tools/mmx.py validate <ptex>`. Fix every error; read warnings
   (`overridden_parameter` means your edit will be thrown away on load). After the Python checks pass
   it runs the engine's check (~2 s), which catches shader compile errors (`shader_compile_error`
   names the faulty node); use `--fast` to skip it for quick structural checks between edits.
5. **Run**: `python3 agent_tools/mmx.py run <ptex> --run-name <run> --note "what changed and why"`.
   Creates `agent_runs/<run>/iter_NNN/` with a ptex copy, `out/` (Unity/URP maps + `.mat`),
   `sheet.png`, `mmx_result.json`. `--run-name` may nest (`1.3/desert`). ~2–8 s per export.
   If it reports `error: timeout`: start the same command with the Terminal panel
   (`run_in_terminal`) and block on `python3 agent_tools/mmx.py wait --run-name <run>` from Bash.
6. **Look at `iter_NNN/sheet.png`** (Read the image) and **write `iter_NNN/critique.md`**:
   for each trait from step 1, matches / doesn't, plus the single biggest gap and what you'll
   change next. Be concrete ("cracks too thin: ~1 px at 2048"), not vague ("needs work").
   **Something didn't show up or looks wrong and you can't tell why?** Do a debug export (doesn't count as an
   iteration): copy the ptex to `agent_runs/<run>/debug/dbg.ptex`, wire the suspect node(s) straight into
   Material albedo (in 0) / roughness (in 2) / metallic (in 1), then
   `python3 agent_tools/mmx.py export agent_runs/<run>/debug/dbg.ptex --out agent_runs/<run>/debug/out` and
   `python3 agent_tools/mmx.py sheet agent_runs/<run>/debug/out`. This is the stand-in for a per-node preview
   (it found two missing wires and a scale mistake in Session 1.3).
7. **Decide**: all traits OK → stop and report. Otherwise go to 3 and change the 1–2 things that
   close the biggest gap. If an iteration made it worse, revert to the previous ptex rather than
   stacking fixes on a broken state.

When you stop, write `agent_runs/<run>/summary.md`: final iteration, which traits match, what's
still off, seconds per iteration. Point the user at the final `sheet.png` and `out/`.

## Reading the contact sheet

Tiles, left to right, top to bottom (only maps that were exported appear):
- **lit**: crude Lambert preview (light from the top-left, albedo × N·L × AO; raised things are lit on
  their top-left side and shadowed bottom-right; sheets made before the Session 1.3 fix were lit
  from the bottom-left, so old Phase-0/1.2 sheets show bumps as dents). This is your main
  "does it read as X" view. No specular and no parallax: metal and gloss look flat and dull here,
  so judge metal from the roughness/metallic tiles instead.
- **lit tiled 2x2**: seams (visible lines at the tile border) and obvious repetition.
- **albedo**: colour only. Real-world albedo is rarely near pure black or white.
- **normal**: should show the relief you intend. Mostly flat lavender = too weak; harsh rainbow
  edges everywhere = too strong or too noisy.
- **height / roughness / metallic / AO**: grayscale with `min/mean/max` in the label.
  `min = max` means a constant map (often a wiring mistake). Roughness is derived from Unity's
  smoothness (1 − A). Non-metals should read metallic ≈ 0; bare metal ≈ 1.
- A map is missing from the sheet if nothing is wired into that Material input (no roughness
  input → no `metal_smoothness` PNG at all).

## Pitfalls seen in this project

- **Blend ports.** `blend` in 0 = foreground (top), in 1 = background, in 2 = mask (1 shows the
  foreground). Lowering `amount` fades out the *foreground*. Getting this backwards cost a whole
  iteration in Phase 0. `blend2` is different: in 0 = background, in 1 = layer.
- **Edits that silently do nothing.** A parameter controlled by a `remote` / subgraph
  `gen_parameters` widget is overwritten on load (`overridden_parameter` warning; e.g. `Bricks.rows`
  in `bricks.ptex`; change the remote's `paramN` instead). A misspelt parameter is ignored by MM
  (`unknown_parameter` error). When in doubt, md5 the output against the previous iteration.
- **Legacy types in examples.** `voronoi`, `bricks`, `transform`, `fbm`, `noise` (and other
  un-numbered types with a newer `...2`/`...3` version) have different ports than the new ones (`bricks` out 1 = random colour per brick, out 4 = Brick UV; `bricks3` has
  fill outputs). Always check ports with `mmx node <type>` for the exact type in the file.
- **Subgraph nodes** (`normal_map`, `graph`) expose `param0..N`; NODES.md lists the real labels
  (`normal_map.param1` = Strength, `param0` = resolution).
- **Unwired Material inputs export nothing.** E.g. `metal_pattern_2` exports only a normal map;
  albedo/metal/roughness come from the Material node's scalar params and Unity won't get maps for
  them. Wire albedo, roughness and metallic (a `uniform` is fine) if the user wants a full set.
- **Odd choices in examples.** `dry_earth` wires a noise into *metallic* (0.08–0.45); `wooden_floor`
  feeds albedo straight into roughness. Fix inherited nonsense like this early.
- **Depth vs height.** Material in 6 is *depth*: white = deeper. The Unity export writes
  `_height.png` = 1 − depth, so on the sheet's height tile white = high. A `normal_map` wants a
  height field (white = high), so feed depth through an inverting `colorize` first, or the relief
  comes out inside-out.
- **Stale parameter names look real.** `normal_map.amount`/`.size`, `Material.normal_scale`,
  `Material.resolution` are leftovers MM ignores (`ignored_parameter` warning). Normal strength is
  `normal_map.param1`; overall normal strength in Unity is `Material.normal`.
- **Unconnected inputs fail silently.** An unwired input reads as 0 (black), so a `tiler` with no
  input renders nothing and an unwired `colorize` shows its gradient across U. `mmx validate`
  doesn't flag this. After adding nodes, list every new node's inputs and check each is wired.
- **Scales are not always per cell.** `tiler.scale_x/y` are fractions of the whole texture: an
  instance in a `tx`×`ty` grid fills one cell at scale 1/tx. Voronoi `Borders` distance grows with
  cell size, so changing `voronoi.scale` changes crack width for the same colorize threshold.
  Change scale *or* width per iteration, not both.
- **Port types.** `f`, `rgb`, `rgba` convert automatically (a colorize can feed a math `f` input);
  `fill`, `sdf2d` etc. don't.
- **Tileability.** Generators in MM tile, but `transform` without `repeat: true`, non-integer
  scales, and rotations by non-multiples of 90° can create seams; check the 2x2 tile.
- **Judging limits.** The lit preview approximates Unity (OpenGL +Y normals). Don't spend
  iterations chasing specular looks you can't see; say what you couldn't verify.
- **CLI rules** (already handled by mmx): absolute paths, `--target` not `-t`,
  `--export-material` not `--export`, never `--headless`. Use mmx instead of calling the binary.

## Don't

- Don't edit files in `material_maker/examples/` or `addons/`; copy into `agent_runs/`.
- Don't make many changes in one iteration: you won't know which one helped.
- Don't exceed 8 iterations; report what's left instead.
