# Phase 0 notes

## Session 0.2 — agent edits `examples/bricks.ptex` (release binary), 2026-10-05

Files: `agent_runs/0.2/` (gitignored): `bricks.ptex` (edited), `out/` (export),
`baseline/` (unmodified copy + export for diffing), `probe/` (parameter experiments).

### `.ptex` structure (bricks)
1. Top level is a node of `type: "graph"` with `nodes[]`, `connections[]`, `parameters{}`, `label`.
2. Each node: `name` (unique id, e.g. `colorize_0`), `type` (= a `nodes/<type>.mmg` definition or a
   built-in like `graph`/`remote`/`ios`), `parameters{}`, `node_position{x,y}`.
3. Parameter values are plain JSON: floats, ints for enums (`pattern: 3` = 4th enum entry),
   `{"type":"Color", r,g,b,a}`, and `{"type":"Gradient", interpolation, points:[{pos,r,g,b,a}]}`.
4. Connections are `{from, from_port, to, to_port}` with 0-based port indices on each node.
5. Subgraphs nest: node `graph` ("Modular Bricks") has its own `nodes`/`connections`; inside it
   `gen_parameters` (`remote`) exposes `param0` and `gen_outputs` (`ios`) is the output port list.
6. A top-level `remote` node (`_2_2`) exposes Hue/Sat/Value widgets linked to `adjust_hsv_0`.
7. Pipeline: subgraph bricks mask → `Warp` (Perlin-warped) → `colorize_2` → mask for `blend_0`;
   brick colour = Perlin→`blend_1`→`colorize_1`→`adjust_hsv_0`; mortar colour = Perlin→`colorize_0`.
8. `blend_0` (normal blend, mask on port 2): port 0 = bricks colour (mask=1), port 1 = mortar (mask=0).
9. `Material` node (type `material`) inputs: 0 albedo, 1 metallic, 2 roughness, 3 emission,
   4 normal, 5 ao, 6 depth, 7 opacity, 8 sss. Here 0,1,2,4,5,6 are wired.
10. `Material.parameters` hold the scalar multipliers (`albedo_color`, `metallic`, `roughness`, `normal`,
    `ao`, `depth_scale`, …) and `size: 11` → 2^11 = 2048 px textures.

### Edits (parameters only)
- `colorize_0` gradient: grey→white became dark blue → light blue (**mortar colour**).
- `graph/Bricks.mortar` 0.05 → 0.15 (**mortar width**).

Result: albedo shows wide blue mortar; normal map shows much wider flat gaps between bevelled
bricks. Both changes are visible as expected. Height/AO also change (all from the same mask).

### Problem: brick-size parameters were ignored
The first plan was brick size via `graph/Bricks.repeat` 2 → 4. The export ran fine, but every map
except albedo came out **byte-identical** to the baseline (albedo changed only because of the colour edit).
Probes: `rows`/`columns` 2 → 4 gave output identical to the baseline too; `mortar` 0.05 → 0.2 changed it.
`bricks.mmg` declares all four the same way (float params used in `oldbricks_bw(...)`), so the
cause is unknown. Open question for later: does the GUI honour `repeat` on this file?
Could it be a subgraph/uniform/caching quirk? Agents must **verify each edit by diffing
outputs** (md5 vs. a baseline export) rather than trusting that a parameter took effect.

### What was easy
- `.ptex` is readable JSON; `nodes/*.mmg` in the release gives parameter names, ranges, enum
  values and port order (`material.mmg` inputs). Editing via a small Python script is trivial.
- Export is fast: **~5.2 s wall** (4.3 s user) for 5 maps at 2048² + `.mat` + `.meta`.

### What was confusing / errors
- **Exports hang when launched from Claude's Bash tool**, sandboxed or not, directly or via
  `open -a`. The app opens a 64×64 window and the main thread blocks forever in
  `-[CAMetalLayer nextDrawable]` (seen with `sample`). Nothing is printed, not even the
  engine header. The display was awake. Bringing the window to the front with AppleScript
  didn't help. **Workaround: run the export in the Claude desktop Terminal panel
  (`run_in_terminal`)**, where it works every time. Likely cause: the GUI app isn't composited
  when its parent is Claude's non-interactive process. To check later (a 0.x/1.x tooling question).
- Terminal panel tabs start in the parent folder (`Material Maker Agent/`), not the repo, so
  always use absolute paths (CLAUDE.md rule confirmed).
- The exporter creates only the last directory level (`make_dir`, not recursive). With a missing
  parent it prints `ERROR: Output directory ... does not exist` and then **does not quit**.
  `mkdir -p` the output dir first.
- Output files are named after the input basename (`bricks_rows.ptex` → `bricks_rows_albedo.png`).
- Harmless noise on every run: `Cannot open user://export_targets`, and at exit
  `6 ObjectDB instances were leaked` / `1 resources still in use`.
- Reading the graph needs care: which blend input is "top", and that mask=0 selects port 1.

## Session 0.3 — tiny real loop: "weathered red roof tiles, slightly mossy, stylized", 2026-10-05

Files: `agent_runs/0.3/` (gitignored): `baseline/` (unmodified `improved_brick.ptex` + export),
`iter_1..5/` each with `build.py` (the edit script, applied to the previous iteration's ptex),
`roof.ptex`, `out/` (Unity/URP export), `sheet.png`, `critique.md`. Helper prototypes copied to
`agent_tools/proto_0.3/`.

**Base:** the release has no roof example. I picked `improved_brick.ptex`: a flat graph (no subgraphs)
of bricks, Perlin weathering and a separate height/normal/AO chain, so it's easy to rewire.

**Path:** iter 1 recoloured it and added a per-tile overlap ramp (`bricks` port 4 "Brick UV" →
`decompose` G → colorize → × tile mask), but it read as cobbles because the gaps were too wide.
Iter 2 added thin gaps, a barrel curve (Brick UV R) and moss restricted to low areas; it read as a
roof, but I made the noise worse with a wiring mistake. Iter 3 fixed the noise and gave the first
good read. Iter 4 added two-tone moss and a height-driven multiply tint, but was too dark.
Iter 5 rebalanced the brightness: final.

### Did the loop converge?
**Yes, roughly.** Iteration 5 is a recognisable, seamless, stylized red tile roof with light moss.
Each iteration improved on the last except iter 2's noise mistake, which I caught and reverted in iter 3.
It did not converge on *nice*: the tiles are rounded squares rather than scallop or S-tile shapes,
the moss has no relief, and roughness is constant. Five iterations was enough for "plausible", not "good".
Wall time per iteration: ~5 s export + ~1 s sheet; the time went into reading the graph and judging the result.

### What blocked me most (ranked)
1. **Graph semantics / wiring (biggest).** Which blend port is the top layer, what `amount` fades,
   that `normal_map` is a subgraph whose strength is the anonymous `param1`, and what range "Brick UV"
   covers (normalised by the brick's *larger* side, so V spans only part of 0–1). In iter 2 I lowered
   `blend_3.amount` to "reduce noise" and faded out the *tile* normal instead, a whole iteration lost.
   Per-port descriptions exist in `.mmg` (`shortdesc`/`longdesc`) but not for subgraph nodes, and
   nothing tells you which input of `blend` is s1 vs s2 except reading the GLSL.
2. **Judging from flat maps.** Albedo/normal/height on their own don't show whether it "reads as a
   roof". I had to write a Lambert preview (albedo × N·L × AO, 1× / 2×2 tiled / crop) to judge at all,
   and it's a guess at Unity's convention (Y flip) and lighting. I couldn't tell how dark the overlap gaps will be in
   URP, or whether the AO is double-counted. It also can't show parallax/height or roughness.
3. **No per-node preview.** To see whether the new ramp/barrel nodes did what I meant, I had to
   route them to the Material and export everything. A "render node X port N" would have caught
   the iter 2 mistake in seconds.
4. **Unknown node types** were a minor issue: the `.mmg` files gave me params/enums/ports for `bricks`,
   `decompose`, `math`, `colorize`, `blend` quickly. Subgraph-defined nodes (`normal_map`) were the
   exception (`param0..4` with links to inner nodes).
5. **Slow exports: not a blocker** (~5 s). The Bash-hang workaround (launch in the Terminal panel,
   poll a `DONE` marker file from Bash) worked every time; it's just clunky.

Other observations:
- Graphs without a roughness input export **no** `metal_smoothness` PNG (improved_brick: 4 maps only).
- Connecting an `rgba` colorize into a `math` `f` input worked (implicit conversion).
- Adding new nodes only needs `name`, `type`, `node_position`, `parameters` (no `seed`); unspecified
  params take defaults.
- Pillow isn't installed system-wide; I used a venv in the scratchpad. Phase 1 `mmx` needs a documented
  setup (`pip install pillow numpy` or a project venv).

### Tools that would have helped most
1. **Lit 3D preview** (Phase 4.2), ideally sphere + plane at a fixed light, as the main image to judge.
   That's the biggest gap.
2. **`mmx describe-node` with port semantics** (Phase 1.1/3.1), including subgraph nodes' real param
   labels and "which blend input is on top".
3. **Single-node render** (Phase 4.1) for debugging a stage of the graph.
4. **`mmx run` + `mmx sheet`** (Phase 1.2): my `export.sh` + `sheet.py` + `g.py` prototypes in
   `agent_tools/proto_0.3/` are a working sketch of these; they cut iteration overhead a lot.
5. A small edit API (set/add/wire by name) rather than hand-editing JSON; `g.py` was ~20 lines and enough.

## Resolved in Session 1.1
- `Bricks.repeat`/`rows`/`columns` edits had no effect because the `graph` subgraph's `gen_parameters`
  remote has a `config_control` (param0, "Pattern") whose configurations set those values on load.
  Change `graph.param0` instead. `mmx validate` reports this as `overridden_parameter`.

## Session 1.2 follow-up: Bash-tool hang
Could not reproduce on 2026-10-05: `mmx export` (Popen, new session, stdin=/dev/null), a plain
`subprocess.run`, and a direct shell launch from Claude's Bash tool all finished in ~5–7 s (6/6).
Cause of the Phase-0 hang still unknown (display state? first launch/permissions?). `mmx` kills a hung
export after `timeout` (mmx.toml) and hints at the Terminal-panel fallback (`mmx wait`).
