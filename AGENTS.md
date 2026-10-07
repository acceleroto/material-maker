# AGENTS.md — Material Maker Agent fork

Instructions for coding agents (Codex and others). Claude Code reads `CLAUDE.md` and the skill in
`.claude/skills/material-maker/SKILL.md`; this file mirrors both. **Keep the material workflow below in sync
with SKILL.md** (it is a copy of the skill body).

## Project rules
- Goal: make Material Maker usable by AI agents (procedural PBR materials from text, visual iteration, Unity export).
  Plan: `agent_docs/ROADMAP.md`; current state and next step: `agent_docs/PROGRESS.md`.
- Work only on branch `agent`; push only with `git push origin agent`. Never push to `master` or `upstream`,
  never force-push, never open PRs upstream (upstream forbids AI-written PRs).
- Commit after every working step (`Session X.Y: <what>`) and update `agent_docs/PROGRESS.md` first.
- New Python tooling goes in `agent_tools/`, docs in `agent_docs/`; keep upstream file changes minimal.
- Never run Material Maker/Godot with `--headless` (it needs a GPU); use `agent_tools/mmx.py`, which handles
  the CLI rules (absolute paths, `--target`, `--export-material`).
- Iteration output goes in `agent_runs/` (gitignored).

## Making a material from a description

You build a `.ptex` graph (JSON), export it with Material Maker through `agent_tools/mmx.py`,
look at the contact sheet (whose top row is Material Maker's own lit 3D preview), and repeat until
it matches the request. Everything runs from the
repo root: `/Volumes/External1/Users/bryan/Documents/Material Maker Agent/material-maker`.

**When to use:** the user asks for a texture or material in words or with a photo ("dry cracked desert
ground", "rusty metal for Unity"), wants an existing `.ptex` changed, previewed or exported to Unity, or asks
why a Material Maker graph looks wrong. Not for editing Material Maker's own GDScript (that's normal coding).

Reference, read on demand (don't inline them into your context all at once):
- `agent_docs/NODES.md`: .ptex primer + ~65 curated node types with ports and parameters.
  `python3 agent_tools/mmx.py node <type>` prints any of the 411 types as JSON.
- `agent_docs/examples_annotated.md`: four example graphs explained node by node.
- `agent_tools/README.md`: mmx commands, validation codes, export/sheet details.

### Prefer the MCP tools when they are available

If your tool list has the `material-maker` MCP server (Claude Code: `mcp__material-maker__*`, registered in
`.mcp.json`; Codex: see `agent_tools/README.md` "MCP server"), run the loop below through it instead of
`mmx`: one engine stays up with the graph in memory, edits take ~0.01 s and a 3D preview ~0.5 s (vs ~6–10 s
per `mmx run`), and render tools **return the image directly** (no Read needed). Tools: `load`, `save`,
`get_graph`, `describe_node`, `list_nodes`, `add_node`, `remove_node`, `connect`, `disconnect`, `set_param`,
`validate`, `render_preview` (lit 3D, the primary image to judge), `render_output` (one node, for debugging),
`export`, `batch` (several of these in one call, stops at the first failure: e.g. two `set_param` + a
`render_preview`), `restart`. How the steps map:
- Step 2: `load` the example (`render_preview size=256` on candidates to choose), then `save` it to
  `agent_runs/<run>/<name>.ptex` right away so later saves never touch `material_maker/examples/`.
- Step 3–5: edits are `set_param` / `add_node` / `connect` (no edit scripts), `validate` after structural edits.
- Step 6: one iteration = edits + `render_preview`; judge the returned image, write the critique, and
  `save` to `agent_runs/<run>/iter_NNN.ptex` so every iteration is reproducible. `render_output` replaces
  `mmx node-preview`. Paths may be repo-relative; render/export outputs default to `agent_runs/mcp/<graph>/`.
- At the end: `validate`, `save`, `export` (Unity/URP maps + `.mat`); for a contact sheet of the final maps run
  `mmx run <saved ptex>` once.
- Engine errors come back as `code: message` (e.g. `unknown_parameter` lists the valid names). After a
  `timeout`/`server_died` the engine is restarted automatically with your last loaded/saved graph and the edits
  made since replayed (the error says so); the failed call is not repeated, so change it (smaller size, other
  edit) rather than retrying it as is. `save` often: it is the recovery point. Heed load/validate warnings
  about unknown node types or missing image files (those render blank).
Without the MCP server, use `mmx` as written below.

### The loop (cap: 8 iterations; stop earlier when it matches)

1. **Restate the request** as 3–6 checkable traits: macro shape/pattern, colour palette, surface
   relief, roughness/metal, style (realistic vs stylized), scale (how many features per tile).
   With a reference photo, also follow "Matching a reference photo" below.
2. **Start from the closest existing graph**, never from an empty file. Look in
   `material_maker/examples/*.ptex` (list them; names are descriptive: `dry_earth`, `wooden_floor`,
   `wood`, `rusted_metal`, `stone_wall`, `tiles`, `marble`, `metal_pattern*`, ...) and
   `agent_docs/examples_annotated.md`. Copy it to `agent_runs/<run>/<name>.ptex`; the output files
   are named after the ptex basename. Run it once unchanged as the baseline (iteration 1).
   When several examples could fit, look before choosing: `mmx preview <example> --size 256` (~2 s each)
   shows what each one is (in 4.3 this found `metal_pattern_3`, already a riveted panel).
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
   `preview_3d.png` (lit 3D preview), `sheet.png`, `mmx_result.json`. `--run-name` may nest
   (`1.3/desert`). ~6–10 s per iteration (export + ~3 s preview). A failed preview is only a warning
   in the result (the sheet then has no 3D row); check `preview` / `warnings` in the JSON.
   If it reports `error: timeout`: start the same command with the Terminal panel
   (`run_in_terminal`) and block on `python3 agent_tools/mmx.py wait --run-name <run>` from Bash.
6. **Look at `iter_NNN/sheet.png`** (Read the image) and **write `iter_NNN/critique.md`**.
   **Judge from the 3D preview (the sheet's top row) first:** it is the material as Material Maker
   renders it (real lighting, specular, normal + height on a sphere and a plane, fixed camera and the
   neutral Studio environment, so iterations are directly comparable). Use the flat maps below it only
   to diagnose *why* something looks off. For each trait from step 1: matches / doesn't, plus the
   single biggest gap and what you'll change next. Be concrete ("cracks too thin: ~1 px at 2048"), not vague ("needs work").
   **Something didn't show up or looks wrong and you can't tell why?** Render the suspect stages
   (doesn't count as an iteration): `python3 agent_tools/mmx.py node-preview <ptex> --node <name> [--port N]`
   (`a/b` for a node inside sub-graph `a`; ~2 s each) and Read the PNG it prints. Walk upstream from the
   Material input that looks wrong until a stage looks wrong; the JSON lists the node's outputs if you need
   another port. Normal-map nodes show MM's internal format (not the exported Unity normal colours).
   If several nodes must be judged together, a debug export still works: copy the ptex to
   `agent_runs/<run>/debug/dbg.ptex`, wire suspects into Material albedo (in 0), then `mmx export` + `mmx sheet`.
   **Comparing several values of a parameter** (or many quick edits): with the MCP tools, one `batch` of
   `set_param` + `render_preview` per value. Without them, use the engine server instead of
   repeated `mmx` runs: one process, edits in memory, ~0.5 s per 3D preview vs ~4–7 s per relaunch:
   `from mm_client import MMClient` (`agent_tools/mm_client.py`; `mm.load`, `mm.set_param`, `mm.render_preview`,
   `mm.render_output`, `mm.validate`, `mm.save`; README "Server mode"). Render each value to its own PNG, Read
   them side by side, `mm.save` the winner into the iteration's ptex and continue the loop with `mmx run`.
7. **Decide**: all traits OK → stop and report. Otherwise go to 3 and change the 1–2 things that
   close the biggest gap. If an iteration made it worse, revert to the previous ptex rather than
   stacking fixes on a broken state.

When you stop, write `agent_runs/<run>/summary.md`: final iteration, which traits match, what's
still off, seconds per iteration. Point the user at the final `sheet.png` and `out/`.

### Handing off to Unity

When the user wants the material in their Unity project (or the default one in `mmx.toml`):
`python3 agent_tools/mmx.py to-unity <final ptex> --project <Unity project root> --name <MaterialName> [--verify]`.
- Picks the target from the project's render pipeline (URP → `Unity/URP`, HDRP → `Unity/HDRP`, none → `Unity/3D`;
  `--target` overrides) and writes `<Name>.mat` + `<Name>_*.png` into `Assets/Materials/Generated/<Name>/`.
  Name: letters, digits, `_`, `-` (PascalCase like `MossyRoofTiles` reads best in Unity).
- Re-running with the same `--name` updates the material in place: texture and material GUIDs are kept, so
  scenes/prefabs using it stay linked; maps the graph no longer produces are removed.
- `--verify` opens the project in Unity batchmode (~15–60 s) and reports whether the material, its shader and
  every texture resolved, plus import settings (`verify.report`). It needs the Unity editor **closed** on that
  project (`stage: editor_open` otherwise; without `--verify` the open editor imports the files when focused).
  It installs `Assets/Editor/MaterialMakerAgent/MMAgentVerify.cs` (Editor-only) in the project. Tell the user if
  the result has `stage: license` (they must sign in to Unity Hub / activate a license).
- Report to the user: the Unity asset path (`material`), the target used, and any verify warnings.

### Matching a reference photo

The photo is the **target to match, never an input**: don't load it into an `image` node or wire it into
the graph (the result must stay procedural, tileable and resolution-independent). The user's photos live in
`agent_refs/` (gitignored) unless they give another path.

Setup:
- **Look at the photo** (Read it) and restate the traits from it along the five axes below. Separate the
  material from the lighting: baked shadows, highlights, perspective and vignetting are not albedo.
- **Palette:** `python3 agent_tools/mmx.py palette <photo> [-n 8] [--crop L,T,R,B]` prints the dominant
  colours (hex, share, luma) by share, `luma` mean/std/p05/p95 and a paste-ready `gradient` (all colours
  dark → light, each at its cumulative-share midpoint). Usually split it by component: darker entries into
  the crevice/mortar `colorize`, lighter ones into the main surface's (raise `-n` to separate them). `--crop`
  (fractions) skips background or samples one component (e.g. a single stone). Gradient colours land 1:1 in
  the albedo PNG, so the hex values can be used as-is. Swatch PNG: `agent_runs/palette/<photo stem>.png`.
- **Choose the start graph against the photo:** `mmx preview <example> --size 256 --out <png>`, then
  `mmx compare <png> --ref <photo>` (one image: photo | preview + palette strip) for each candidate.
- **First run:** `mmx run <ptex> --run-name <run> --ref <photo>` copies the photo to
  `agent_runs/<run>/reference.<ext>`; every later `mmx run` / `mmx sheet` of that run picks it up. The sheet's
  top row becomes [reference (centre square) | 3D preview], followed by palette strips for the reference and
  the exported albedo (hex, share, luma mean ± std). The result JSON has `reference_palette`, `albedo_palette`,
  `reference_luma`, `albedo_luma`.
- **With the MCP tools:** after `render_preview` (its result names the PNG), run
  `mmx compare <png> --ref <photo> [--albedo <exported _albedo.png>]` and Read the image.

Compare along these axes, roughly in this order (fixing a later one is wasted while an earlier one is off):
1. **Scale:** features per tile. Count them in the photo (bricks per row and column, planks, cracks across)
   and set the generator to match; assume the photo's centre square ≈ one tile unless the user says otherwise.
2. **Shape:** silhouettes and layout (running bond vs random, chipped vs rounded edges, crack branching,
   straight vs warped).
3. **Coverage:** how much of each component (mortar vs stone, moss, rust patches, dirt in crevices). The
   palette shares give a number to compare (e.g. the photo's darkest 22% vs the albedo's).
4. **Palette:** hue and value per component. Aim for albedo luma mean within ~0.03 of the photo's. A photo
   includes shading, so a rough surface's albedo should have a somewhat lower std than the photo; judge the
   overall impression from photo vs 3D preview, the numbers from the two palette strips.
5. **Roughness and relief:** read them off the photo's light: small sharp highlights = smooth or wet, broad
   dull sheen = rough; shadow length in crevices = relief depth. Compare with the sphere's highlights and
   the plane's shadows.

Expectations:
- Aim for a **convincing match**: the same material at a glance, at the same scale, with a similar palette and
  wear. Not a pixel copy: individual stones, cracks and stains won't line up and aren't worth chasing, and
  one-off features (a specific stain, a logo) are out of scope for a tileable procedural material.
- **After ~4 iterations, stop and ask the user to steer:** show the latest sheet (photo beside the preview),
  list what matches, the 1–3 biggest remaining differences and what you'd change next, and ask what matters
  most to them (or whether it's good enough). Continue with their answer, within the 8-iteration cap.
- In `summary.md`, include reference vs albedo luma and palette, and which differences are left on purpose.

### Reading the contact sheet

**Top row: 3D preview — the primary image to judge.** Material Maker's own 3D preview (the editor's
preview scene and the Material node's preview shader): a sphere (left) and a tilted plane (right),
Studio environment (grey background, studio HDRI + sun). It shows what the flat maps can't: gloss
and specular highlights, metal, how strong the relief really reads, and scale on a curved surface
(the sphere wraps the texture 4×2, the plane 2×2; the sphere's poles always pinch). Same camera, lights
and environment every iteration, so compare iterations side by side. Quick look without exporting:
`python3 agent_tools/mmx.py preview <ptex>` (→ `agent_runs/preview/<name>.png`; `--mesh cube`,
`--env "Epping Forest"` to vary, but keep the defaults for iteration-to-iteration comparisons).

With a reference photo (`mmx run --ref`), the photo sits left of the 3D preview and two palette strips
follow (reference, then the exported albedo; swatches dark → light, width = share).

Map tiles below it, left to right, top to bottom (only maps that were exported appear):
- **lit**: crude Python Lambert preview of the exported maps (light from the top-left, albedo × N·L × AO).
  Secondary now: useful to check the *exported* Unity maps agree with the 3D preview (e.g. normal
  direction), not to judge the look. No specular: metal and gloss look flat and dull here.
- **lit tiled 2x2**: seams (visible lines at the tile border) and obvious repetition.
- **albedo**: colour only. Real-world albedo is rarely near pure black or white.
- **normal**: should show the relief you intend. Mostly flat lavender = too weak; harsh rainbow
  edges everywhere = too strong or too noisy.
- **height / roughness / metallic / AO**: grayscale with `min/mean/max` in the label.
  `min = max` means a constant map (often a wiring mistake). Roughness is derived from Unity's
  smoothness (1 − A). Non-metals should read metallic ≈ 0; bare metal ≈ 1.
- A map is missing from the sheet if nothing is wired into that Material input (no roughness
  input → no `metal_smoothness` PNG at all).

### Pitfalls seen in this project

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
- **`scratches2.randomness` spreads the angle.** At 0.5 the scratches point in every direction
  (a web of arcs) even with `angle` 0; use ~0.05 for scratches along a grain.
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

### Don't

- Don't edit files in `material_maker/examples/` or `addons/`; copy into `agent_runs/`.
- Don't make many changes in one iteration: you won't know which one helped.
- Don't exceed 8 iterations; report what's left instead.
