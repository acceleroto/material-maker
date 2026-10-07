# Progress

**Current session:** 5.3 (in progress)

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

- 4.2 (agent, 2026-10-06): engine `--render-preview <abs ptex> [--mesh sphere|plane|cube|a+b] [--env name|index]
  [--size px] -o <abs png> [--json]` in new `cli_preview.gd` (parsing in `cli_inspect.gd`; `parse_args.gd` dispatch
  line only). Reuses the editor: `preview_3d_scene.tscn` (objects/camera/sun/WorldEnvironment) in an own-world
  SubViewport, `EnvironmentManager.apply_environment` (bundled HDRIs; default **Studio**: grey bg + studio HDRI +
  sun), `MMGenMaterial.update_material` (Material preview shader + preview textures at the graph's size).
  Default sphere+plane side by side, 512 px per view. Deviations (all for reproducibility, in README): per-mesh FOV
  (sphere 30°, plane 37°, cube 31° vs editor 50°, same camera pose), UV scales reset to the scene's (editor applies
  user `mm_config.ini`), opaque bg, MSAA 4×; `mm_globals.main_window` stub (tessellation 256) only while generating
  cube/plane meshes; EnvironmentManager kept out of the tree (its `_exit_tree` rewrites `user://environments.json`).
  **Deterministic** (two renders byte-identical). ~2–4 s per render. Guard: render modes now fail ("wrote no file")
  if a script error aborts them — found when a GDScript error made a run report ok. Also found: a script that fails
  to compile makes the app hang instead of quitting (mmx's timeout covers it).
  mmx: `preview` (defaults `preview_mesh/env/size` in mmx.toml), `run` renders `iter_NNN/preview_3d.png` (failure =
  warning; `--no-preview` / `preview_3d = false`), `sheet` puts the preview as a full-width top row (`--preview`,
  else `<dir>/preview_3d.png`, else `<dir>/../preview_3d.png`). `mmx run` bricks: 8.4 s total (export 5.4 s +
  preview 2.0 s); stylized_wall `--size 1024`: 9.1 s. Checked: bricks, stylized_wall, dry_earth look right; a mortar
  colour edit (colorize_0 → blue) is clearly visible; cube + Epping Forest/Moonless Golf render; errors for unknown
  env/mesh, no Material node (exit 1), missing file (2). Tests: GUT 41 pass; mmx 57 pass (fake-engine preview,
  sheet top row, run with preview ok/failing/disabled, real-engine render). Images: `agent_runs/4.2/`
  (`compare.png` = bricks / blue-mortar bricks / dry_earth), `agent_runs/4.2/{wall,bricks}/iter_001/sheet.png`.
  Docs: SKILL.md + AGENTS.md (3D preview = primary image to judge; Lambert tile secondary), README, CLAUDE.md.

- 4.3 (agent, 2026-10-06): nothing open from 4.1/4.2 (optional preview `--texture-size` skipped: all graphs ≤2048,
  previews ~2 s). GUT 41 + mmx 57 tests pass. Re-ran the three 1.3 requests with the skill, judging from the 3D preview
  (`agent_runs/4.3/{desert,steel,oak}/`, cap 8): desert **5 iterations, success**; steel **4, success** (started from
  `metal_pattern_3`, picked by `mmx preview` of the three metal examples; preview showed the rivets were pits → fixed in
  one edit; no debug exports); oak **7, success** (stylized grain, bevel relief, wear, scratches, knots; two node-previews
  diagnosed wear band/scratch angle). 16 iterations vs 18 in Phase 1, no partials, ~25 s wall per iteration.
  `agent_runs/4.3/compare/phase1_vs_phase4.png`: Phase 1 finals re-rendered with the 3D preview. **Finding:** Phase 1's
  "successful" steel is a noisy rippled chrome in 3D (only flat maps were judged then). Report:
  `agent_docs/phase4_report.md`. Skill + AGENTS.md: preview candidate examples before choosing; `scratches2.randomness`
  spreads the angle. Open ideas: zoom/crop helper for fine detail, `parameter_out_of_range` too strict (voronoi stretch).

- 5.1 (agent, 2026-10-06): engine server `--serve` (`cli_serve.gd`; `parse_args.gd` gained one dispatch branch):
  JSON-RPC lines on stdin/stdout (`{"id","method","params"}` → `{"mm_rpc":1,"id","ok","result"|"error":{code,message},
  "warnings"?}`; ready line at startup; non-`mm_rpc` stdout lines are engine noise; stdin EOF → exit 0). Methods load,
  save, list_nodes (query/category filter), describe_node (type or node with current values + connections), add_node,
  remove_node, connect (port range/type checks, loop → `connection_rejected`), disconnect, set_param (values coerced per
  definition: enum names, colours, gradients...; float strings only as `$` expressions), get_graph (compact or full .ptex),
  validate, render_output, render_preview, export (strict target, deletes stale `<prefix>.*`/`<prefix>_*`), shutdown.
  All built on MMGenGraph methods; `cli_inspect.gd`/`cli_preview.gd` split into load + `validate_gen`/`render_node`/
  `render_gen` (CLI output unchanged). `agent_tools/mm_client.py`: `MMClient` (wrappers, timeouts kill the server, noise
  filtering), `batch <jsonl>`, `bench`. **Byte-identical** to the CLI after edits: render_output, render_preview and all 5
  exported maps (tests). **Engine bugs found + worked around:** (1) freeing a graph/node while mm_deps renders its buffers
  left `mm_deps.do_update()` awaiting forever → all later renders hung (server waits for renders before load/remove_node);
  (2) export replaces the Material node's preview textures (process_shader on the templates) → later float edits never
  reached render_preview (server calls `material.update()` after export). Probably upstream editor bugs too (not checked).
  **Measured** (`agent_runs/5.1/bench_*/bench.json`): server start ~1.3 s; edit + 3D preview + node render ≈ 0.45 s warm
  (first 0.7–1.9 s) vs 4.2 s (bricks) / 6.8 s (stylized_wall) relaunching: 8.1× / 9.1× over a 5-value sweep; with a 2048
  export per iteration 4.3 s vs 7.5 s (1.7×, export rendering dominates). Tests: GUT 50 (new `test/test_cli_serve.gd`),
  mmx 57, `agent_tools/test_mm_client.py` 23 (fake server + real server ~25 s). Docs: README "Server mode", CLAUDE.md,
  SKILL.md + AGENTS.md (parameter sweeps via MMClient).

- 5.2 (agent, 2026-10-07): stdio MCP server `agent_tools/mcp_server.py` (stdlib only, own JSON-RPC 2.0 over
  newline-delimited stdio; protocol 2024-11-05…2025-11-25, echoes the client's) on top of `MMClient`: 14 tools = the
  `--serve` methods (shutdown → `restart`) + `batch` (ops in order, stops at the first failure, returns all render
  images). Schemas with `additionalProperties: false`; unknown/missing args → `bad_params` before the engine is called;
  read-only annotations. `render_preview`/`render_output` return the PNG as an MCP image block (2×512 preview ≈ 0.5 MB)
  + the JSON result. Engine starts lazily on the first tool call (~1.3–2 s) and stays up; timeout/crash → isError text
  says the next call starts a fresh engine (graph must be reloaded). Relative paths → repo root; default outputs
  `agent_runs/mcp/<stem>/preview_NNN.png`, `node_<node>_p<port>_NNN.png`, `export/`; engine log `agent_runs/mcp/engine.log`.
  `--check` (start engine, print info), `--list-tools`. Registered project-scoped: `.mcp.json` (absolute script path) +
  `enabledMcpjsonServers` in `.claude/settings.json`; `claude mcp get material-maker` → Connected. Codex: documented
  (`codex mcp add ...` + `tool_timeout_sec = 300`), user's `~/.codex/config.toml` not modified. Reference
  graysonchalmers/Tool-MaterialMaker-MCP is MIT; read for ideas only (lazy start, `--check`, stop-at-first-failure batch),
  no code copied (it uses the `mcp` SDK + its own Godot socket; ours needs no dependency). Smoke run over real stdio
  (bricks): load 0.1 s, render_preview 0.56 s, set_param 0.01 s, render_output 0.22 s, batch edit+preview(256) 0.30 s,
  validate 0.27 s, export(256) 1.1 s. Tests: `agent_tools/test_mcp_server.py` 15 (fake engine: protocol, schemas, lazy
  start, arg checks, image content, defaults, batch, crash/timeout recovery, stdio subprocess; real engine batch +
  validate + export). Docs: README "MCP server" (incl. Codex), CLAUDE.md, SKILL.md + AGENTS.md ("Prefer the MCP tools
  when they are available" section, sweeps via `batch`). Not checked: the tools inside a live Claude Code / Codex chat
  (this session was started outside the repo, so `.mcp.json` wasn't loaded here).

## In progress
- 5.3: engine hardening + MMClient crash recovery + MCP arg checks committed; next: MCP real-engine recovery test,
  docs (README), agent_docs/ARCHITECTURE.md, full test run.

## Blockers
- None. Exports run fine from the Bash tool (Terminal-panel fallback via `mmx wait` if `mmx` reports a timeout).

## Next step
- Session 5.3 per ROADMAP.md "### 5.3" (hardening): crash recovery in `MMClient`/`mcp_server.py` (restart the engine and
  reload the last saved graph; today `mcp_server.MaterialMakerTools._drop` just forgets the graph and asks the agent to
  reload), timeouts, malformed requests, very large sizes, missing files; tests; run the full suite (GUT
  `-gtest=res://test/test_cli_serve.gd,res://test/test_cli_inspect.gd,res://test/test_parse_args.gd`,
  `agent_tools/.venv/bin/python -m unittest agent_tools/test_mmx.py agent_tools/test_mm_client.py agent_tools/test_mcp_server.py`);
  write `agent_docs/ARCHITECTURE.md` (one page). First, start Claude Code in the repo root and try the
  `mcp__material-maker__*` tools once (load bricks, render_preview) to confirm images show up in a real chat.
- Still open for the user: Checkpoint 4 review (`agent_docs/phase1_report.md` vs `agent_docs/phase4_report.md`).
