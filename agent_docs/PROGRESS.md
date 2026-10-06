# Progress

**Current session:** 4.2 (in progress)

## Done
- 0.0: Project rules (`CLAUDE.md`), progress tracking (`agent_docs/PROGRESS.md`,
  `agent_docs/ROADMAP.md`), permission allowlist (`.claude/settings.json`),
  `agent_runs/` gitignored. Working on branch `agent` (tracks `origin/agent` on the
  acceleroto fork).
- 0.0 follow-up: full plan copied into `agent_docs/ROADMAP.md`; CLAUDE.md gained the
  `--target`/absolute-path/steam_appid rules from the plan.

- 0.1 (user, 2026-10-05): manual export WORKS. Release binary,
  `--export-material --target "Unity/URP"` on `examples/bricks.ptex`. Output folder had
  `bricks.mat` + `bricks_albedo`, `bricks_height`, `bricks_metal_smoothness`,
  `bricks_normal`, `bricks_occlusion` PNGs. Copied to `MM-Agent-Test/Assets/out/`; material
  on a sphere renders bricks correctly with a URP shader (Unity 6.5, 6000.5.5f1, Metal).
  No magenta, no steam_appid workaround reported.
- 0.2 (agent, 2026-10-05): edited release `bricks.ptex` (parameters only: mortar colour via
  `colorize_0` gradient → blue, `graph/Bricks.mortar` 0.05→0.15), exported Unity/URP to
  `agent_runs/0.2/out/` (~5.2 s/export); both changes visible in albedo + normal.
  Findings in `agent_docs/phase0_notes.md`: exports hang if launched from the Bash tool
  (use the Terminal panel); `Bricks.repeat/rows/columns` edits had NO effect on output
  (unexplained); exporter won't create nested out dirs and doesn't quit on that error.
  CLAUDE.md updated with the export workaround.
- 0.3 (agent, 2026-10-05): 5-iteration loop on "weathered red roof tiles, slightly mossy,
  stylized", starting from release `examples/improved_brick.ptex` (no roof example exists).
  `agent_runs/0.3/iter_1..5/` each have build.py, roof.ptex, out/ (Unity/URP), sheet.png,
  critique.md. Converged roughly: iter 5 is a plausible stylized mossy red roof. Biggest blockers:
  graph/port semantics (lost iter 2 to a blend-port mistake), then judging from flat maps
  (wrote a Lambert-lit preview sheet). Findings + tool wishlist appended to phase0_notes.md.
  Prototype helpers (export.sh with DONE marker, g.py edit API, sheet.py) in
  `agent_tools/proto_0.3/`.
- 0.4 (user, 2026-10-05): decision: the pipeline works and the agent made reasonable progress
  ("not amazing, but a good start") → continue to Phase 1 (normal path).
- 1.1 (agent, 2026-10-05): `agent_tools/mmx.py` (stdlib only) with `catalog` (→ `agent_tools/catalog.json`,
  411 types incl. built-ins, port-type table; `agent_docs/NODES.md`, 442 lines, ~65 curated types + .ptex
  primer incl. blend foreground/background/mask semantics), `validate <ptex>` (JSON ok/errors/warnings,
  exit 0/1; codes table in `agent_tools/README.md`), `node <type>`. Subgraph `paramN` resolve to real labels
  (`normal_map.param1` = Strength). Tests `python3 -m unittest agent_tools/test_mmx.py -v`: all 43
  `material_maker/examples/*.ptex` pass; broken copies (bad type / bad port / bad params) fail correctly.
  Findings: old examples carry stale params MM ignores (→ `ignored_parameter` warning via `STALE_PARAMS`);
  `.mmg` files can set a default `generic_size` (mwf_mix = 2); out-of-slider values are common (warning).
  **Phase-0 mystery solved:** `Bricks.repeat/rows/columns` in `bricks.ptex` are driven by the subgraph's
  `gen_parameters.param0` config_control (Pattern), which overwrites them on load; `validate` now warns
  `overridden_parameter` for this.

- 1.2 (agent, 2026-10-05): `mmx export/sheet/run/wait` + `agent_tools/mmx.toml` (mode/target/timeout/binary;
  `source` mode stubbed for Phase 2). `export` validates first, predicts the expected files from the Material
  node's export template (`$(connected:x_tex)` conditions), deletes old outputs (MM silently skips existing
  `.mat`/`.meta` in CLI mode), runs with timeout + `export.log`, writes/prints `mmx_result.json`. `sheet`:
  lit + lit-tiled previews, split packed maps (Unity metal_smoothness, Godot orm), min/mean/max labels.
  `run` → `agent_runs/<run>/iter_NNN/` (ptex copy, out/, sheet.png, note.md). `wait` polls results for the
  Terminal-panel fallback. Pillow lives in gitignored `agent_tools/.venv` (mmx re-execs into it).
  Tests: 19 pass (`agent_tools/.venv/bin/python -m unittest agent_tools/test_mmx.py`), export paths tested
  with a fake MM binary (ok / missing file / hang→timeout / validation refusal).
  **Finding: the Phase-0 Bash-tool hang no longer reproduces** (6/6 exports from Bash, ~5 s, incl. a plain
  direct launch). CLAUDE.md now says: use `mmx run` from Bash; on `error: timeout`, fall back to
  `run_in_terminal` + `mmx wait`. Real runs: `agent_runs/s1.2/iter_001` (bricks, via Terminal panel),
  `iter_002` (improved_brick, via Bash).

- 1.3 (agent, 2026-10-05): `.claude/skills/material-maker/SKILL.md` (when to use, 8-iteration loop: closest example →
  validate → `mmx run` → read sheet → `critique.md` → 1–2 edits; reading the sheet; pitfalls; debug-export technique) and
  root `AGENTS.md` (project rules + a verbatim copy of the skill body; keep in sync). `agent_docs/examples_annotated.md`
  (dry_earth, wooden_floor, wood, metal_pattern_2). End-to-end test in `agent_runs/1.3/{desert,steel,oak}/` (6 iterations
  each): desert **success**, steel **success**, oak **partial**; export ~3.8 s, ~18 s median wall per iteration.
  Report: `agent_docs/phase1_report.md` (recommends Phase 4 > 3 > 2 > 5).
  **Fixes:** `mmx sheet` lit preview lit from the bottom-left (y-sign bug; older sheets show bumps as dents) → top-left
  + test; `mmx run --run-name` may nest (`1.3/desert`) + test (21 tests pass). **Findings:** Material in 6 is *depth*
  (Unity `_height.png` = 1 − depth); `tiler.scale_x/y` are fractions of the whole texture; unconnected inputs read as 0
  and `validate` doesn't flag them (cheap follow-up: warn on used nodes with unconnected inputs).

- Checkpoint 1 / Setup B (user, 2026-10-06): continuing to Phase 2. Godot 4.7.2 imported the project
  (Game Embed Mode disabled), MM runs from source (F5). Agent check: from-source export
  `Godot --path <REPO> --export-material --target "Unity/URP" -o <abs out> <abs bricks.ptex>` works from the Bash
  tool without `steam_appid.txt`: exit 0, ~11 s (release ~5 s), all 5 maps + `.mat`, and every PNG is
  **byte-identical** to the release export (`agent_runs/0.2/baseline`). Log noise: Steam API init errors (no Steam),
  thread/semaphore warnings, leak messages at exit. The editor import rewrote 16 `.import` files + `project.godot`
  line order (default keys only), committed separately. macOS has no `timeout` command (use mmx's timeout).

- 2.1 (agent, 2026-10-06): `parse_args.gd` (the only upstream file touched): `--size` honoured (0/absent = the
  graph's own size; was always 2048), exit codes via `get_tree().quit(code)` (0 ok, 1 bad args, 2 load/parse,
  3 export; highest wins), errors/warnings to stderr, `--json` one summary line (keys sorted; `mm_cli`, `ok`,
  `exit_code`, `materials[{input,target,size,files,ok}]`, `files`, `warnings`, `errors`), similarity target
  fallback now warns, `--strict-target` fails instead (lists available targets). Also fixed: a bad `--size`
  returned from `_ready` without quitting (process hung); no-match target crashed on `{}.files`; output dir now
  `make_dir_recursive`. Parser/target logic are static funcs (`parse_export_args`, `resolve_target`); written
  files found by dir snapshot filtered to the export prefix name. GUT: `test/test_parse_args.gd`, 13 tests pass
  (`Godot --headless --path <repo> -s addons/gut/gut_cmdln.gd -gtest=res://test/test_parse_args.gd -gexit`).
  Real-run matrix in `agent_runs/2.1/` (default bricks byte-identical to pre-change; `--size 512` → 512²;
  fuzzy target → 0 + warning; strict → 1; missing/garbage ptex → 2; `--size abc`/unknown option/no file → 1;
  uncreatable or read-only out dir → 3). mmx: `mode = "source"` now default in `mmx.toml` (passes `--json
  --strict-target`, optional `--size` on `export`/`run`), stdout → `export.log`, stderr → `export.stderr.log`,
  result has `mm` (exit code, targets, sizes, files_written, warnings, errors); non-zero exit → named error.
  32 mmx tests pass (fake binary covers exit codes 1/2/3 + missing summary). `mmx run` bricks: ~5.4 s;
  `--size 256`: ~2 s. Not exercised: the additional-export (export node) branch — no example uses one.

- 3.1 (agent, 2026-10-06): `cli_inspect.gd` (repo root; `parse_args.gd` delegates to it when
  `--list-nodes`/`--describe-node`/`--validate` is given). `--list-nodes --json` (items from the add-node menu's
  library manager + all 411 types), `--describe-node <type>...|--all --json` (instantiated generators; whole set in
  ~2 s), `--validate <ptex>... --json` (unknown types, connection checks, then SPIR-V compile of every output of
  every node incl. sub-graph nodes via `MMComputeShader`, no rendering; skipped if the graph already has errors;
  exit 4 = invalid). All 43 examples in one launch: ~50 s, 1663 outputs; 42 clean, `doc_tools.ptex` has 2 real
  GLSL errors (`'input'` reserved word, undeclared `_seed_variation_`). GUT `test/test_cli_inspect.gd` (run with `-gtest=res://test/test_cli_inspect.gd,res://test/test_parse_args.gd`;
  `-gdir=res://test` also runs upstream doc tests that already fail). `--describe-node` reports a parameter's
  `default` as the instantiated value (what an omitted .ptex parameter resolves to; the def's own default is kept
  as `def_default` when different). mmx: `run_engine`, `engine_validate`, `validate_full` (Python first, engine only
  if clean; `--fast`; `validate_engine` in mmx.toml; engine failure → `engine_unavailable` warning); `mmx catalog`
  now merges engine data (`--static` = old path); `catalog.json`/`NODES.md` regenerated (engine_vs_static: only
  comment_line, webcam differ; ~400 parameter defaults corrected, reroute/portal ports `any`). 44 mmx tests pass
  (`TestRealEngine` ~1 min; `MMX_SKIP_ENGINE=1` skips it).
  Docs: `agent_tools/README.md` ("Engine CLI modes", new codes), CLAUDE.md, SKILL.md + AGENTS.md (validate step).
  Sanity: `mmx validate bricks` → static+engine ok (1.6 s, 34 outputs); `mmx run bricks --size 256` ok (2 s).
  Findings: describing generators needs them in the tree under an MMGenGraph parent (linked remote params and
  switch ports are set up in `_ready`), except comment/comment_line/material_export; buffers compile shaders in
  `_ready`, so describe/validate need a GPU context (no `--headless`); structural errors cascade into shader
  errors, so the compile check only runs on otherwise-clean graphs.

- 4.1 (agent, 2026-10-06): engine `--render-output <abs ptex> --node <name|a/b> [--port n] [--size px] -o <abs png> [--json]`
  in `cli_inspect.gd` (`parse_args.gd` only gained the dispatch condition). Renders with
  `MMGenBase.render_output_to_texture` + `MMTexture.save_to_file`, i.e. the compute-shader path the exporter and
  the 2D preview use, **not** the roadmap's `renderer.gd`/`multi_renderer.gd` (legacy SubViewport path; its
  `render()` is marked deprecated). Waits for buffers like `export_material`; waits up to 5 s for
  `mm_renderer.rendering_device` (created asynchronously at startup; without the wait the first try failed).
  Summary: `type` (the .ptex type, from `gen.model`), `output_type`, `output_label`, `outputs` (all ports).
  Exit 1 unknown node (lists nodes with outputs at that level) / bad port / Material or comment, 2 load, 3 render.
  `mmx node-preview <ptex> --node N [--port] [--size 512] [--out]` → default
  `agent_runs/node_preview/<stem>/<node>_p<port>.png`, deletes stale file, ok only if the PNG exists.
  Tests: GUT 38 pass (5 new parser tests); mmx 50 pass (5 fake-engine + 1 real-engine render test).
  Real run (11 renders, 2 graphs, ~2 s each, ~3.5 s with buffers): bricks `Perlin` (f), `graph/Bricks` (inside
  a sub-graph), `blend_1`, `blend_0`, `colorize_3`, `normal_map_2`; stylized_wall `bricks` (ports 0 and 1), `fbm`,
  `buffer`, `graph_5` (downstream of the buffer), `blend_5`. Contact images `agent_runs/4.1/{bricks,wall}_contact.png`.
  **Byte-identical to `mmx export --size 512`**: bricks blend_0 = `_albedo`, colorize_3 = `_occlusion`;
  stylized_wall blend_5 = `_albedo`. **Finding:** a `normal_map` node's raw output is MM's internal format
  (blue ≈ 27/255, red flipped vs the Unity export, which the target converts) — documented in SKILL/README.
  stylized_wall's `bricks` port 0 is all white (mortar 0, bevel 0; the graph only uses port 1) — correct.
  Docs: `agent_tools/README.md`, CLAUDE.md, SKILL.md + AGENTS.md (debug step now uses node-preview first).

## In progress
- 4.2: engine `--render-preview` works (cli_preview.gd, editor preview scene + EnvironmentManager + Material preview shader;
  deterministic, ~2.6 s). Next: `mmx preview`, sheet top row, `mmx run` integration, docs.

## Blockers
- None. Exports run fine from the Bash tool (Terminal-panel fallback via `mmx wait` if `mmx` reports a timeout).

## Next step
- Session 4.2 per ROADMAP.md "### 4.2" (plan mode first): `--render-preview <ptex> --mesh sphere|plane|cube
  --env <name> --size <px> -o <png>` (material on a mesh, fixed camera/lighting; see `material_maker/meshes`,
  `material_maker/environments`). Useful from 4.1: `cli_inspect.gd` `render_output_file()` (load, wait for
  RD + buffers, render, save; exit codes) and `mmx node_preview()` (run_engine wrapper, stale-file removal).
  Material preview needs the Material node's 3D shader (`MMGenMaterial` preview textures, `gen_material.gd`
  ~l.110-210) and a real 3D viewport (not the compute path). Tests: GUT
  `-gtest=res://test/test_cli_inspect.gd,res://test/test_parse_args.gd`, `agent_tools/.venv/bin/python -m unittest agent_tools/test_mmx.py`.
