# agent_tools

Python tooling that lets an AI agent work with Material Maker. Python 3.11+ (`tomllib`), stdlib only,
except `sheet`/`run`, which need Pillow in a project venv (gitignored):

```
python3 -m venv agent_tools/.venv && agent_tools/.venv/bin/pip install pillow
```

`mmx.py sheet`/`run` re-exec themselves under `agent_tools/.venv` automatically, so always call
`python3 agent_tools/mmx.py ...`.

## mmx.py

```
python3 agent_tools/mmx.py catalog [--static]  # rebuild catalog.json + agent_docs/NODES.md (from the engine)
python3 agent_tools/mmx.py validate <file.ptex> [--fast] [--hide CODE]... [--timeout S]
python3 agent_tools/mmx.py node <type>        # one type's params/ports as JSON
python3 agent_tools/mmx.py export <file.ptex> --out <dir> [--target "Unity/URP"] [--timeout S] [--keep-meta]
python3 agent_tools/mmx.py sheet <dir> [--out sheet.png] [--preview preview_3d.png]
python3 agent_tools/mmx.py preview <ptex>... [--mesh sphere+plane] [--env Studio] [--size 512] [--out x.png] [--cols 3]
python3 agent_tools/mmx.py node-preview <ptex> --node NAME [--port N] [--size 512] [--out x.png]
python3 agent_tools/mmx.py run <file.ptex> --run-name NAME [--note "what changed"] [--no-preview]
python3 agent_tools/mmx.py wait (<dir> | --run-name NAME) [--timeout S]
python3 agent_tools/mmx.py to-unity <ptex> --project <Unity root> --name NAME [--verify]   # "Unity hand-off"
agent_tools/.venv/bin/python -m unittest agent_tools/test_mmx.py -v   # plain python3 skips the sheet test
                                     # TestRealEngine runs Godot (~1 min); MMX_SKIP_ENGINE=1 skips it
python3 -m unittest agent_tools/test_unity_handoff.py -v             # no Unity needed (fake editor)
python3 agent_tools/setup.py [--godot G] [--unity-project P]          # one-time setup + smoke test (GETTING_STARTED)
```

Every command prints its JSON result on stdout, then one `mmx: <outcome>` summary line on stderr
(`2>&1 | tail -1`). `validate --hide ignored_parameter` drops those warnings (leftover parameter names in many
examples) and reports their count under `hidden`. `preview` with several `.ptex` renders each (default 256 px
per view) to `agent_runs/preview/<stem>.png` and a labelled contact image (`--out`, default
`agent_runs/preview/contact.png`; needs Pillow); see `agent_docs/EXAMPLES.md` for the examples rendered that way.

- **catalog**: asks the engine (`--list-nodes`, `--describe-node --all`, see "Engine CLI modes" below;
  ~4 s, needs `mode = "source"`) and overlays that on a Python parse of `addons/material_maker/nodes/*.mmg`,
  `nodes/io_types.mmt` and `material_maker/library/*.json`. The engine is authoritative for labels,
  descriptions, parameters, ports, categories and keywords; the Python parse adds generic templates,
  `source`, `superseded_by`, `library_graphs` and the port-type table. Writes `agent_tools/catalog.json`
  (every type: kind, `generator` class, category (menu path) and `section`, parameters with
  type/range/default/enum values, inputs/outputs with 0-based index, type and descriptions) and the
  condensed `agent_docs/NODES.md` (~65 types, < 600 lines; the curated list is `CURATED` in `mmx.py`).
  A parameter's `default` is the value a node starts with (what an omitted `.ptex` parameter resolves
  to); `def_default` is the definition's own default when different. `engine_vs_static` lists types
  where the Python parse disagrees with the engine (2026-10-06: only `comment_line`, `webcam`).
  `--static` skips the engine; `--nodes-dir DIR` (static only) adds a `.mmg` dir that overrides repo
  defs (e.g. the release app's `nodes/`). Re-run after changing node definitions; commit both outputs.
- **preview** (Session 4.2): lit 3D preview of a `.ptex` with the engine's `--render-preview` (~2.5–4 s;
  source mode only): the editor's 3D preview scene and the Material node's own preview shader, sphere
  + plane side by side, Studio environment, fixed camera. Defaults (`preview_mesh`, `preview_env`,
  `preview_size` per view) come from `mmx.toml`; keep them fixed so iterations stay comparable. Default
  file `agent_runs/preview/<ptex stem>.png`. Prints `{"ok", "file", "meshes", "env", "size", "width",
  "height", "image_size" (the graph's texture size the preview textures are rendered at), "seconds",
  "errors", "warnings"}`; exit 0/1.
- **node-preview** (Session 4.1): renders one output of one node to a PNG with the engine's
  `--render-output` (~2 s, ~3.5 s for graphs with buffers; source mode only). `--node` is the node name,
  `a/b` for node `b` inside sub-graph node `a`; `--port` the output index (default 0); `--size` default
  512. Default file: `agent_runs/node_preview/<ptex stem>/<node>_p<port>.png` (`a/b` → `a__b`); a stale
  file is deleted first. Prints `{"ok", "file", "node", "port", "size", "type" (the .ptex type),
  "output_type", "output_label", "outputs" (every output: index/type/label, to pick a port), "seconds",
  "errors", "warnings"}`; exit 0/1. Unknown node → the error lists the nodes with outputs at that level.
  Use it to debug a graph stage by stage instead of a debug export.
- **validate**: Python checks first (instant). If they pass, runs the engine's `--validate` (~2 s for
  bricks: loads the file with `mm_loader`, checks types and connections against the instantiated
  generators, compiles every output's shader) and merges its findings (`"source": "engine"`).
  `--fast` (or `validate_engine = false` in `mmx.toml`) skips the engine; if the engine can't run
  (release mode, no Godot, timeout) you get an `engine_unavailable` warning and the Python result.
  Prints `{"ok", "errors", "warnings", "checks": ["static", "engine"], "engine": {seconds, nodes,
  outputs_checked}}`; exit 0 if no errors, else 1. Each item has `code`, `graph_path` (`/`, `/graph`,
  ...), `node`, `message`, and often `hint` (close-match suggestions, valid ports or the expected
  parameter format). `mmx export`/`run` only run the Python checks (the export itself is the engine).

| code | level | meaning |
|---|---|---|
| `invalid_json`, `bad_structure`, `missing_name`, `missing_type` | error | file/node shape |
| `duplicate_node_name` | error | names must be unique per graph |
| `unknown_type` | error | not a .mmg, built-in or content-typed node |
| `unknown_node`, `bad_connection` | error | connection endpoint missing / malformed |
| `bad_input_port`, `bad_output_port` | error | port index out of range (hint lists the ports) |
| `input_multiply_connected` | error | an input has more than one source |
| `port_type_mismatch` | error | e.g. sdf2d into an rgba input (f/rgb/rgba convert freely) |
| `unknown_parameter` | error | parameter name not defined for the type (typo → MM silently ignores it) |
| `bad_parameter_type`, `bad_enum_value`, `bad_generic_size` | error | wrong value shape |
| `bad_linked_widget` | error | remote widget links to a missing node/parameter |
| `overridden_parameter` | warning | a remote widget will overwrite this value on load: edit the remote instead |
| `ignored_parameter` | warning | known leftover from an older MM version (or edited inline shader); ignored by MM |
| `parameter_out_of_range` | warning | outside the slider range (allowed; common in examples) |
| `unresolved_type` | warning | `website:` type, fetched by MM at load time |
| `shader_compile_error` | error (engine) | generated GLSL doesn't compile; `node` is the node whose code fails (`section`, `line`, `code_line`, `messages`, `outputs` = compiled outputs that hit it) |
| `connection_rejected` | error (engine) | the engine refused a connection (loop) |
| `engine_check_skipped`, `engine_unavailable`, `shader_check_skipped` | warning | engine/shader check not run (Python errors, no Godot, graph errors, `--headless`) |

Type resolution mirrors `MMLoader.create_gen` (`addons/material_maker/engine/loader.gd`): inline
`shader_model` → shader/material; inline `nodes`/`connections` → subgraph (ports from its
`gen_inputs`/`gen_outputs` ios nodes, params from its `gen_parameters` remote); `widgets` → remote;
then built-in types (`buffer`, `switch`, `ios`, `reroute`, `portal`, `image`, `export`, ...; ports
hand-coded from `engine/nodes/gen_*.gd`); then `.mmg` files. Generic nodes expand their `#`
ports/params by the node's `generic_size`, defaulting to the `.mmg`'s own `generic_size`.

### Engine CLI modes (Session 3.1, `cli_inspect.gd`)

`parse_args.gd` hands these to `cli_inspect.gd` (source mode; not in the release app). Add `--json` for
one summary line `{"mm_cli": 1, "mode", "ok", "exit_code", "errors", "warnings", ...}` (stdout also has
Godot noise; take the last line starting with `{"`). Exit codes: 0 ok, 1 bad arguments, 2 load failure /
unknown type, 3 render failure (`--render-output`), 4 validation errors.

```
<Godot> --path <repo> --list-nodes --json                       # items (add-node menu) + types
<Godot> --path <repo> --describe-node bricks3 blend2 --json    # or --describe-node --all (~2 s)
<Godot> --path <repo> --validate <abs a.ptex> [<abs b.ptex>...] --json
<Godot> --path <repo> --render-output <abs a.ptex> --node graph/Bricks [--port 0] [--size 512] -o <abs x.png> --json
<Godot> --path <repo> --render-preview <abs a.ptex> [--mesh sphere+plane] [--env Studio] [--size 512] -o <abs x.png> --json
```

- `--list-nodes`: `items` = every add-node menu entry, read through the editor's own library manager
  (`tree_item`, `display_name`, `category` = top section, `type`, `library`, `enabled`, `inline_graph`,
  `shortdesc`, `keywords` from the aliases); `types` = every type `mm_loader.create_gen` accepts
  (`label`, `category`, `in_library`, `builtin`, `shortdesc`).
- `--describe-node`: per type, the instantiated generator's `generator` class, `label`, descriptions,
  raw `parameters`/`inputs`/`outputs` defs (parameter `default` = the instantiated value).
- `--validate`: per file `{input, ok, nodes, outputs_checked, errors, warnings}`: `unknown_type`,
  connection codes as in the table above, then (only if no errors so far) `shader_compile_error` for
  every output of every node, including nodes inside sub-graphs, compiled to SPIR-V with
  `MMComputeShader` (nothing is rendered). Each faulty node is reported once. All 43 examples: ~50 s in
  one launch; `doc_tools.ptex` (MM's doc helper graph) really has 2 GLSL errors. Needs a GPU context:
  under `--headless` the shader check is skipped with a warning.
- `--render-output` (Session 4.1): loads the file, waits for buffers like the exporter, then renders the
  output with `MMGenBase.render_output_to_texture` (the compute-shader path the exporter and the 2D
  preview use; the legacy `renderer.gd` SubViewport path is deprecated) and saves it (`png`/`exr`/`jpg`/
  `webp`; parent dirs created). `--size` 16..8192 (default 512). Summary adds `input`, `node`, `port`,
  `size`, `file`, `type`, `output_type`, `output_label`, `outputs`. Greyscale (`f`) outputs come out grey
  RGBA; sdf/other types use the type's preview code (as in the editor). Pixels match the export
  byte-for-byte where the target writes the value unchanged (bricks albedo/AO, stylized_wall albedo);
  **not** for normals: a `normal_map` node's raw output is MM's internal format (blue ≈ 0.1, red flipped),
  the target converts it when exporting. Exit 1 for unknown node / port out of range / node without
  outputs (Material, comment), 2 load failure, 3 render or write failure.
- `--render-preview` (Session 4.2, `cli_preview.gd`): reuses the editor's pieces instead of new ones:
  `preview_3d_scene.tscn` (objects, camera, sun, WorldEnvironment) in an own-world SubViewport,
  `EnvironmentManager.apply_environment` with `material_maker/environments/environments.json` (bundled
  HDRIs: Epping Forest, Moonless Golf, Studio; `--env` = name, case-insensitive, or index), and
  `MMGenMaterial.update_material` (the Material node's preview shader + preview textures, rendered via
  `mm_deps` at the graph's own texture size). `--mesh` = `sphere`, `plane`, `cube`, or several joined with
  `+` (one `size`×`size` view each, side by side; default `sphere+plane`). Differences from the editor,
  all for reproducibility: per-mesh field of view (sphere 30°, plane 37°, cube 31°; editor 50° — same
  camera position/angle, just zoomed in), UV scales reset to the scene's (sphere 4×2, plane 2×2, cube 3×2;
  the editor applies the user's `mm_config.ini` overrides), opaque background, MSAA 4×. Tessellation 256
  (editor default) via a stub `mm_globals.main_window` that exists only while the cube/plane mesh is
  generated. The EnvironmentManager is never added to the tree (its `_exit_tree` rewrites
  `user://environments.json`). Deterministic: two renders are byte-identical. Summary adds `input`,
  `meshes`, `env`, `env_index`, `size`, `width`, `height`, `image_size`, `file`, `seconds`. Exit 1 unknown
  mesh/env or no `Material` node, 2 load failure, 3 render/write failure. Both render modes fail with
  "wrote no file" if a script error aborted them (instead of silently reporting ok).
- GUT: `<Godot> --headless --path <repo> -s addons/gut/gut_cmdln.gd -gtest=res://test/test_cli_inspect.gd,res://test/test_parse_args.gd -gexit`.

### Limitations
- The Python checks are structural only; the engine check adds shader compilation. Neither evaluates
  expressions in float parameters (`"$time*2"`), and a valid file can still render nothing useful.
- `website:` node types and user shared nodes (`user://shared_nodes`) aren't available offline.
- Ports of `meshmap`, `sdf`, brush and `model_data` nodes, and an empty `material_export` node, are
  unknown, so their connections aren't range-checked.
- Built-in node defs are copied by hand from `gen_*.gd` and can drift if upstream changes them.
- `STALE_PARAMS` (in `mmx.py`) lists leftover parameters found in the bundled examples; other old
  files may contain more, which show as `unknown_parameter` errors.
- The catalog reflects the repo's node defs; the release app may ship different ones (use
  `--nodes-dir` to override). Checked 2026-10-05: the release has the same `.mmg` set except
  `clouds_noise2` (repo only, so a file using it validates but won't load in the release app);
  6 files differ in content, none in parameter names or ports.
- `overridden_parameter` only compares values already in the file; it can't see changes made
  through the GUI after load.

## Export, sheet, run (Session 1.2)

**Config** `agent_tools/mmx.toml` (override: `$MMX_CONFIG` or `--config`): `mode` (`source` = Godot +
this repo, the default since Session 2.1; `release` = the installed app), default `target`, `timeout`
(default 180 s; an export takes ~2–11 s), `[source] godot` and `project`, `[release] binary` and
`data_dir` (its `nodes/` is used to predict outputs).

**export**: `validate` first (errors → exit 1, nothing runs), then plans the expected files from
the Material node's export template for the target (mirrors `MMGenMaterial.export_material`:
`$(connected:x_tex)` conditions vs. the graph's connections into the Material node; an unknown
target fails with close matches). It `mkdir -p`s the out dir, **deletes previous outputs of that
prefix** (MM silently skips existing `.mat`/`.meta` in CLI mode, and old maps would hide a failure;
`--keep-meta` keeps `.meta` files to preserve Unity GUIDs), runs the binary with absolute paths,
`--export-material --target`, stdout → `<out>/export.log`, stderr → `<out>/export.stderr.log`, and kills
it after the timeout. `--size N` (source mode only) renders N×N maps, e.g. 512 for fast drafts; default
is the graph's own size (Material node `size`, usually 2048).
Success = every expected file exists and is newer than the start; in source mode also MM's exit code
is 0 and its `--json` summary line is present (the release app always exits 0 and has no summary).
Prints and writes `<out>/mmx_result.json`: `ok`, `stage` (validate/plan/export/done), `mode`, `error`,
`files` [{file, bytes}], `missing`, `mm` (source mode: MM's `exit_code`, `targets`, `sizes`,
`files_written`, `warnings`, `errors`), `log_errors` (known harmless Steam/shutdown noise filtered),
`seconds`, `hints`. Exit 0 ok, 1 validation/plan, 2 export failed. A non-zero MM exit becomes
`error: "<bad arguments|load/parse failure|export failure>: <MM's errors>"`.

**Material Maker CLI (source mode, `parse_args.gd`, Session 2.1)**:
`<godot> --path <repo> --export-material [--target T] [-o DIR] [--output-file PATTERN] [--size N]
[--json] [--strict-target] <file.ptex|glob|website:ids>...`
- `--size N`: texture size in pixels; `0`/absent = the graph's own size (before 2.1 it was ignored
  and always 2048).
- Exit codes: `0` success, `1` bad arguments (missing value, bad `--size`, unknown option, no input,
  unknown target), `2` load/parse failure (missing/invalid file, no glob match, no Material node),
  `3` export failure (output dir can't be created, an export wrote no files). Several failures → the
  highest code.
- Errors and warnings go to **stderr** (`ERROR: ...` / `WARNING: ...`).
- Unknown `--target`: MM falls back to the most similar profile and now warns
  (`target "X" not found, using "Y"`); with `--strict-target` it fails (exit 1, lists the available
  targets). mmx always passes `--strict-target` (and checks the target before launching anyway).
- `--json`: last stdout line is one JSON object (keys sorted): `mm_cli` (1), `ok`, `exit_code`,
  `target_requested`, `size_requested`, `output_dir`, `materials` [{input, target, size, files, ok}],
  `files` (all written paths), `warnings`, `errors`. "Written" = files named after the export prefix
  that are new or changed during the export (detected by directory snapshot, 1 s mtime resolution).
- Tests (GUT): `<godot> --headless --path <repo> -s addons/gut/gut_cmdln.gd -gtest=res://test/test_parse_args.gd -gexit`
  (parsing only, so `--headless` is fine; GUT prints one harmless `SCRIPT ERROR` from its own loader).

**sheet**: one PNG of everything in an export dir. Top row (full width): the 3D preview, if there is one
(`--preview`, else `<dir>/preview_3d.png`, else `<dir>/../preview_3d.png` — where `mmx run` puts it).
Then `lit` (crude Lambert, light from top-left,
from albedo+normal+AO), `lit tiled 2x2` (seams/repetition), then albedo, normal, height,
roughness, metallic, AO, emission, ... Packed maps are split (Unity `metal_smoothness`: R =
metallic, roughness = 1 − A; Godot `orm`: R/G/B = AO/roughness/metallic). Grayscale tiles are
labeled with min/mean/max so flat or clipped maps are obvious. Default output `<dir>/sheet.png`.

**run**: claims the next `agent_runs/<run>/iter_NNN/` (from 001; `--run-name` may nest with `/`, e.g. `1.3/desert`), copies the ptex there (outputs
are named after it), exports into `iter_NNN/out/`, renders `iter_NNN/preview_3d.png` (source mode,
`preview_3d = true` in mmx.toml, not with `--no-preview`; a failed preview adds a warning and the
sheet has no 3D row), writes `iter_NNN/sheet.png`, `mmx_result.json` (export result + `iter_dir`,
`sheet`, `preview` {ok, file, meshes, env, seconds, errors}), `mmx_status.json` (running/done) and
`note.md` (`--note`). Validation failures still use up an iteration dir (the result explains why).

**wait**: for when the app has to be launched from the Terminal panel. Start
`mmx run ... --run-name X` with `run_in_terminal`, then from Bash `mmx wait --run-name X` blocks until
the newest iteration has a result (one finished up to `--fresh` 60 s before the call counts), and
prints it. `mmx wait <dir>` waits for a specific out/iteration dir.

**Launching from Claude's Bash tool**: in Phase 0 the app hung forever there (`CAMetalLayer
nextDrawable`). In Session 1.2 it did **not** reproduce: `mmx export`, a plain subprocess and a
direct shell launch all finished in ~5–7 s (6/6). So call `mmx run` from Bash first; if it reports
`error: timeout` (with the hint), use the Terminal panel + `mmx wait`.

Fixed in Session 1.3: the lit preview used to put the light at the bottom-left (a y-sign slip), so
raised features looked sunken on sheets made before then. Limitations: the lit preview is a flat-plane Lambert approximation (no specular, no parallax) and
assumes OpenGL (+Y) normals; additional `material_export` nodes' files aren't predicted; only the
first material node is checked. The `parse_args.gd` additional-export branch (export nodes) wasn't
exercised in Session 2.1 (no example uses one).

## Reference photos (Session 6.1): `palette`, `compare`, `run --ref`

A reference photo is the *target* the agent compares against; it never goes into the graph. Keep the
user's photos in `agent_refs/` (gitignored). All three commands need Pillow (re-exec into `.venv`).

**palette** `mmx palette <photo> [-n 6] [--crop L,T,R,B] [--swatch PNG | --no-swatch]`: downscales to 192 px
(long side), median cut + k-means (`Image.quantize`, 8 rounds) into `n` colours (2..12, default 6; fewer if the
image has fewer). EXIF rotation applied, alpha composited on black, `--crop` in fractions of the image.
Prints `colors` [{hex, rgb, share, luma}] by share (luma = Rec. 709, 0..1), `luma` {mean, std, p05, p95} of
the whole (cropped) image, `gradient`: an MM `Gradient` value (`interpolation` 1) with every colour dark →
light at the midpoint of its cumulative share, so a colorize fed a uniformly distributed grayscale reproduces
the photo's shares. MM stores gradient colours as the albedo PNG's sRGB bytes / 255 (checked: a gradient of
palette colours gave the photo's luma mean within 0.002). Swatch default `agent_runs/palette/<stem>.png`.

**compare** `mmx compare <preview.png> --ref <photo> [--albedo PNG] [--width 1536] [--out PNG]`: one PNG with
[reference, centre square | preview] scaled to `--width`, labels, and palette strips (reference; albedo
if given; swatches dark → light, width = share, `luma mean ± std`). For previews made outside `mmx run`
(`mmx preview`, MCP `render_preview`). Default output `<preview stem>_vs_ref.png` next to the preview. Prints
`compare`, `reference_palette`, `reference_luma` (+ `albedo_palette`, `albedo_luma`).

**run --ref / sheet --ref**: `mmx run ... --ref <photo>` copies the photo to `agent_runs/<run>/reference.<ext>`
(replacing an older `reference.*`); every sheet of that run (later `run`s without `--ref`, `mmx sheet <iter>/out`)
finds it (`find_reference`: `<dir>/..`, `<dir>/../..`, `<dir>`), so the top block of the sheet is the `compare`
image with the exported albedo's strip. The result JSON adds `reference`, `reference_palette`, `albedo_palette`,
`reference_luma`, `albedo_luma`. Without a 3D preview the reference alone fills the top row.

Limitations: the palette counts pixels, so large flat areas dominate and small accents (a few % of the
image) may merge into neighbours; raise `-n` or `--crop` onto them. A photo's palette includes its
lighting (shadows, highlights), so expect an albedo to be somewhat flatter; nothing here measures shape,
scale or roughness — those are judged by eye (SKILL.md "Matching a reference photo").

## Unity hand-off (Session 6.2): `to-unity`

`mmx to-unity <ptex> --project <Unity root> --name <Name> [--target T] [--size N] [--verify] [--unity <exe>]`
(defaults for `--project` and `--unity` in `mmx.toml` `[unity]`; code in `unity_handoff.py`). JSON, exit 0/1;
also written to `agent_runs/to-unity/<Name>/to_unity_result.json` (staged export in `export/` beside it).

1. **Target** from the project's render pipeline: the pipeline assets set in `GraphicsSettings.asset` and every
   `QualitySettings` level are looked up by GUID under `Assets/` and classified by their `m_Script` GUID (URP/HDRP
   asset classes) or content; none set → Built-in (`Unity/3D`) even if the URP package is installed; asset not
   found → the single installed pipeline package; mixed → error, pass `--target`. Result: `pipeline`, `target`.
2. **Export** (source mode) with `--output-file <Name>`, so files are `<Name>.mat`, `<Name>_albedo.png`, ...
   (`expected_files`/`export_command` take `output_name`).
3. **Copy** into `Assets/Materials/Generated/<Name>/` (`sync_into_project`):
   - GUIDs: a map whose `.meta` already exists there keeps its GUID (the new `.mat` is rewritten to it);
     `<Name>.mat.meta` is kept, or created with a new GUID (`material_guid`), so references survive re-exports.
     Result: `kept_guids`, `new_guids`.
   - Texture `.meta` files are **rewritten** (`texture_meta`): MM's Unity templates indent nested blocks with
     tabs (invalid YAML) or flatten them (normal map), and Unity ignored every nested setting (checked in batchmode:
     data maps imported as sRGB). Ours: albedo/emission sRGB, `_normal` NormalMap (linear), every other map linear;
     mipmaps on, wrap Repeat, bilinear, `maxTextureSize` = next power of two ≥ the PNG (never downscaled).
     Result: `textures` {file: role, srgb, texture_type, max_size}.
   - Files `<Name>.mat(.meta)` / `<Name>_<map>.png(.meta)` that this export didn't produce are deleted (`removed`);
     other files in the folder are left alone.
   - `editor_open`: PIDs of Unity editors with the project open (they import the files when focused).
4. **`--verify`** (`verify`): refuses while an editor has the project open (`stage: editor_open`; batchmode
   cannot open a locked project); installs `unity/MMAgentVerify.cs` as
   `Assets/Editor/MaterialMakerAgent/MMAgentVerify.cs` (Editor-only, rewritten only when changed), then
   `Unity -batchmode -quit -projectPath P -logFile L -executeMethod MMAgentVerify.Run -mmFolder Assets/... -mmReport R`.
   The verifier force-imports the folder, then per material: shader found (not the error shader), compiles,
   supported, matches the active pipeline (URP shader ↔ URP asset, Built-in shader with a pipeline = magenta);
   every `m_Texture` GUID in the `.mat` file resolves to a loaded texture and is a property of the shader; importer
   checks (normal map type, data maps not sRGB, downscaled on import). `verify.report` = its JSON
   (`render_pipeline`, `assets`, `materials[{shader, textures[{property, path, resolved, importer_type, srgb,
   mipmaps, max_size, wrap, width, height}], errors, warnings}]`); unity exit 0 ok / 1 problems / 2 bad args /
   3 exception. Log in `agent_runs/to-unity/<Name>/unity_verify.log`. No report + a licensing line in the log →
   `stage: license` + `license_lines` (a working log also has `[Licensing::Module]` lines; only failure phrases
   count). Timeout `[unity] verify_timeout` (900 s; a fresh project import takes ~45 s, a warm run ~10 s).
   Unity 6000.5 occasionally crashes while shutting down batchmode *after* the verifier wrote a clean report (seen:
   exit -10, "fatal error in the mono runtime"): a clean report with a non-zero exit is retried once
   (`retried_after_exit_code`, `attempts: 2`); if it happens twice, `ok: false`, `stage: exit_after_ok_report` and an
   error naming the exit code (the report itself is still clean).

Licensing: on this machine (Unity Hub signed in, Unity 6000.5.5f1) batchmode needed no extra step: the editor
connects to the Hub's licensing client.

Tests: `test_unity_handoff.py` (pipeline detection on synthetic projects, names, GUID-keeping sync, metas, editor
process matching, a fake Unity for verify ok/problems/license, `to_unity` with a faked export).

## Server mode (Session 5.1): `--serve` + `mm_client.py`

`<Godot> --path <repo> --serve` (`cli_serve.gd`) is a long-running engine process that keeps one graph loaded.
Edits go through MMGenGraph methods (`add_generator`, `connect_children`, `set_parameter`, ...), never through the
JSON, and render/validate/export run on the in-memory graph. Same code paths as the CLI modes: after edits, server
renders and exports are **byte-identical** to the CLI on the saved graph (tested).

**Speed** (bricks / stylized_wall, `mm_client.py bench`, `agent_runs/5.1/bench_*/bench.json`): server start ~1.3 s,
load 0.1–0.5 s; set_param + 3D preview (2×512 px) + one node render ≈ **0.45 s** per iteration once warm
(first iteration 0.7–1.9 s) vs **4.2 s / 6.8 s** relaunching the engine per step: ~8–9× on a 5-step sweep,
~10–15× steady state. With a full 2048 export each iteration: 4.3 s vs 7.5 s (export rendering dominates).

### Protocol
One JSON object per line on stdin; one per line on stdout. Requests are processed in order, one at a time.
```
-> {"id": 1, "method": "set_param", "params": {"node": "Perlin", "name": "scale_x", "value": 8}}
<- {"mm_rpc": 1, "id": 1, "ok": true, "result": {"node": "Perlin", "changed": [...], "seconds": 0.01}, "warnings": [...]}
<- {"mm_rpc": 1, "id": 2, "ok": false, "error": {"code": "unknown_node", "message": "..."}}
```
- First line after startup: `{"mm_rpc": 1, "id": null, "ok": true, "result": {"ready": true, "version": 1, "pid", "rendering_device", "methods"}}`.
- The engine also prints its own messages to stdout: **ignore every line that isn't a JSON object with `mm_rpc`**.
  Server logs (and engine errors) go to stderr.
- A failing request never stops the server. stdin EOF → exit 0 (64 empty reads in a row count as EOF: Godot's
  `read_string_from_stdin` returns `""` for both). Blank lines are ignored.
- Paths must be absolute. Node paths: `"Perlin"`, or `"graph/Bricks"` for a node inside sub-graph `graph`.

### Methods
| method | params | result |
|---|---|---|
| `load` | `path` | `path, nodes, material, image_size` |
| `save` | `path?` (default: loaded file) | `path, bytes` (written like the editor's save) |
| `list_nodes` | `query?`, `category?` | `items` (add-node menu), `types` (as `--list-nodes`) |
| `describe_node` | `type` **or** `node` | type: as `--describe-node`; node: current parameter values (`default`), `inputs`, `outputs`, `connections`, `position` |
| `add_node` | `type`, `name?`, `parent?`, `position?`, `parameters?` | `node, name` (deduplicated, e.g. `perlin_2`), ports, parameter values |
| `remove_node` | `node` | `removed, connections_removed` |
| `connect` | `from, from_port, to, to_port` (ports default 0) | `connection, replaced` (the connection it replaced on that input, or null) |
| `disconnect` | `to, to_port`, `from?, from_port?` | `removed` |
| `set_param` | `node` + `name, value`, or `node` + `params: {name: value}` | `changed: [{name, old, new}]` |
| `get_graph` | `node?` (a sub-graph), `full?` | compact `nodes [{name, type, parameters}]`, `connections`; `full: true` = the `.ptex` dict |
| `validate` | – | as `--validate` for one file: `ok, nodes, outputs_checked, errors, warnings` |
| `render_output` | `node, output`, `port?`, `size?` (512, 16..8192) | as `--render-output` |
| `render_preview` | `output`, `mesh?` (`sphere+plane` or a list), `env?` (Studio), `size?` (512, 16..4096 per view) | as `--render-preview` |
| `export` | `output_dir`, `target?` (Unity/URP, strict), `size?` (0 = graph's, max 8192), `prefix?` (file stem), `overwrite?` (true) | `files, deleted, target, size` |
| `shutdown` | – | `bye`; then exit 0 |

Every result also has `seconds`. `add_node` `position` is `[x, y]` or `{"x", "y"}`.
**Warnings instead of silent failures** (5.3): `load` warns about nodes of unknown types and connections the
loader dropped (it skips them silently) and about file parameters (`image` node, text font) naming missing files
(they render blank); `add_node`/`set_param` warn about such missing files, and `validate` (also the CLI
`--validate`) reports them as `missing_file` warnings. **Size limits:** render 16..8192 px, preview ≤ 4096 px per
view (3×4096 ≈ 9 s), export ≤ 8192 (bricks at 8192 ≈ 35 s; 16384 textures need GBs of video memory each; the
CLI `--size` has the same cap). Measured in 5.3, none of these crash the engine: 8192 node render ~5 s, export
at a non-power-of-two size (3000) works.
**Hidden-window renders** (fixed 2026-10-10): the engine's window is 1×1 px; once macOS considers it occluded,
`DisplayServer.window_can_draw()` is false and Godot's main loop keeps running but stops drawing frames, so a
3D preview waiting for `frame_post_draw` waited forever (the "random" `render_preview` timeouts, also CLI
`--render-preview` while another engine window sat on top). `cli_preview.gd draw_frame()` now calls
`RenderingServer.force_draw()` when no frame was drawn within two process frames; outputs are byte-identical.
**Watchdog:** while a server request runs longer than 15 s, the engine log (stderr) gets a report every 5 s:
`mm_deps` queue and each unfinished buffer (status, owner node), the renderer's device owner/thread state, and
frame counters (`process`/`drawn`/`can_draw`). Long first renders after edits on graphs with many buffers (e.g.
the marble's sub-graph normal maps: ~20 s at 2048) are real work, visible there as buffers in `Updating`.
**Parameter values** are checked against the definition: float = number,
numeric string, or an expression of `$` variables (`"$time*0.1"`; other strings would be pasted into GLSL);
enum = index or value name (`"multiply"`); size = exponent within `first..last`; boolean; color =
`{r,g,b,a}` / `[r,g,b(,a)]` / `"#rrggbb"`; gradient/curve/polygon/... = the object as in `get_graph full=true`
(`{"type": "Gradient", ...}`). Floats outside the slider range are set, with a warning.
`export` with `overwrite` deletes `<prefix>.*` and `<prefix>_*` in `output_dir` first (MM silently skips existing
`.mat` files in command-line mode), listed in `deleted`.

**Error codes:** `parse_error`, `bad_request`, `unknown_method`, `no_graph`, `bad_params`, `load_failed`,
`unknown_node`, `unknown_type`, `unknown_parameter`, `bad_value`, `bad_port`, `port_type_mismatch`,
`connection_rejected` (loop), `no_connection`, `cannot_delete` (Material), `save_failed`, `render_failed`,
`no_material`, `export_failed`, `internal` (a script error aborted the method; see stderr).

**Engine gotchas handled by the server** (found in 5.1): freeing a graph or node while `mm_deps` still renders its
buffers leaves `mm_deps.do_update()` waiting forever and every later render hangs, so `load`/`remove_node` first
wait for pending renders (a second `load` takes ~0.3–1.4 s); exporting replaces the Material node's preview
textures (`process_shader` on the target's templates), so `export` rebuilds the preview afterwards, or later edits
would never reach `render_preview`. Not checked: a broken expression only shows up in `validate` (renders just
come out wrong).

### Python client (`agent_tools/mm_client.py`, stdlib only)
```python
import sys; sys.path.insert(0, "agent_tools")
from mm_client import MMClient, MMError
with MMClient(log_path="agent_runs/x/server.log") as mm:   # Godot/project paths from mmx.toml
    mm.load("material_maker/examples/bricks.ptex")          # relative paths are resolved by the client
    mm.set_param("Perlin", scale_x=8, scale_y=8)
    mm.render_preview("agent_runs/x/preview.png")
    mm.export("agent_runs/x/out")                            # target from mmx.toml
```
Each method returns the result dict or raises `MMError(code, message)`; `last_warnings` holds the last
request's warnings, `noise` the engine's recent stdout lines. `close()` / the context manager sends `shutdown`.

**Timeouts:** 180 s per request (mmx.toml `timeout`), capped at 60 s for methods that neither render nor compile
(`set_param`, `connect`, `get_graph`, ...), so a hang there is noticed sooner; a timeout kills the engine.
**Crash recovery** (`auto_restart=True`, the default; Session 5.3): the client remembers the last successfully
loaded/saved graph and the edits made since (`add_node`, `remove_node`, `connect`, `disconnect`, `set_param`).
When a request times out or the engine dies, it starts a new engine, loads that graph and replays the edits, then
raises `MMError("timeout"|"server_died")` for the failed request (not repeated, since it may crash again), with
`e.recovery = {graph, replayed, edits_lost, errors, summary}` and the summary appended to the message. If
replaying crashes the engine again, it retries with the graph alone. An engine that died between requests is
recovered before the next request (`last_recovery`). `restart(reload=True)` does the same on demand.
`auto_restart=False` keeps the old behaviour (`server_died` on every later call). Other guards: Godot binary and
`project.godot` are checked before launching (`start_failed`), parameters that aren't JSON (NaN, objects) or
requests over 4 MiB (the server's line buffer) raise `bad_params` without being sent, and a `parse_error`
without id while a request is pending is taken as its answer (no 180 s wait). CLI:
- `python3 agent_tools/mm_client.py batch <file.jsonl> [--log f]`: one `{"method", "params"}` per line (`#` comments),
  one result line each, through one server; exit 1 if any request failed.
- `python3 agent_tools/mm_client.py bench <ptex> --node N --param P --values 2,4,8 [--render-node M] [--export]
  [--out dir]`: the same sweep through the server and by relaunching the engine (mmx), with md5 comparison of
  the renders; writes `bench.json`.

Tests: `agent_tools/.venv/bin/python -m unittest agent_tools/test_mm_client.py` (fake server for the protocol,
real server ~25 s; `MMX_SKIP_ENGINE=1` skips it); GUT `res://test/test_cli_serve.gd` (request parsing, value coercion).

## MCP server (Session 5.2): `mcp_server.py`

`agent_tools/mcp_server.py` (stdlib only) is a stdio MCP server on top of the engine server: one tool per
`--serve` method (`load`, `save`, `list_nodes`, `describe_node`, `add_node`, `remove_node`, `connect`, `disconnect`,
`set_param`, `get_graph`, `validate`, `render_output`, `render_preview`, `export`) with JSON schemas and descriptions,
plus `batch` (a list of `{"method", "params"}` run in order, stops at the first failure, returns every step's result
and the images of render steps) and `restart`. `render_preview` / `render_output` return the PNG as an MCP
`image` content block (plus the JSON result as text), so the agent sees it without reading a file
(`return_image: false` skips it; a 2×512 preview is ~0.5 MB).
- The engine starts on the first tool call that needs it (~1.3–2 s) and stays up for the session. Engine stderr:
  `agent_runs/mcp/engine.log` (restarts are appended, marked `--- mm_client: engine restart N ---`). A `timeout`
  or crash restarts it at once through MMClient's recovery (reload the last loaded/saved graph, replay the edits
  since): the failed tool call is an error saying what was restored and that the call was not repeated; if the
  engine died between calls, the next result carries a `the engine had exited; ...` warning. `restart` does it on
  demand (`reload: false` = no graph).
- Relative paths resolve against the repo root. Omitted outputs go to `agent_runs/mcp/<graph stem>/`:
  `preview_NNN.png`, `node_<node>_p<port>_NNN.png` (numbered, earlier renders are kept), `export/`
  (prefix = graph stem, target/preview defaults from `mmx.toml`).
- Tool failures are results with `isError: true` and text `code: message` (engine codes as in "Server mode",
  plus `bad_params` for unknown/missing arguments and wrong types/ranges, e.g. `render_preview.size must be <=
  2048 (got 100000)`, checked against the tool schemas before the engine is called); protocol errors are JSON-RPC
  errors (non-object `params`/`arguments` → -32602, empty batch → -32600). Images over 8 MB are written but not
  inlined (`images_not_inlined`: render smaller to see them). Warnings are in the result's `warnings`. Only MCP messages go to stdout.
- MCP: protocol versions 2024-11-05 … 2025-11-25 (echoes the client's), capabilities `tools` only; tool
  annotations mark read-only tools.
- `python3 agent_tools/mcp_server.py --check` starts the engine once and prints its ready info (exit 0/1);
  `--list-tools` prints the tool definitions; `--config`, `--timeout`, `--log`, `--engine-command` (tests).

**Claude Code** (project scope, committed): `.mcp.json` at the repo root (written by
hand; the script path is relative to the repo root, so it is portable but needs Claude Code started in the
repo root) and `"enabledMcpjsonServers": ["material-maker"]` in
`.claude/settings.json` (no approval prompt). Tools appear as `mcp__material-maker__<tool>`; check with
`claude mcp get material-maker` (should say Connected; that doesn't start the engine). Machine-specific
paths (Godot, Unity) live in the gitignored `agent_tools/mmx.local.toml` (`agent_tools/setup.py` writes it). The tools only load when the session's working
directory is the repo (or below it): start Claude Code there, or in the desktop app move an existing session into
the repo folder; the tools appear on the next turn (checked in-chat 2026-10-10: images show inline, preview ~0.5 s,
edit + preview in one `batch` ~0.2 s, MCP export byte-identical to `mmx export`).

**Codex** (user scope, `~/.codex/config.toml`):
```bash
codex mcp add material-maker -- python3 "<absolute path to the repo>/agent_tools/mcp_server.py"
```
then raise the per-tool timeout (Codex default 60 s; a 2048 export of a big graph can take longer) by adding
`tool_timeout_sec = 300` under `[mcp_servers.material-maker]` in `~/.codex/config.toml`. Equivalent by hand:
```toml
[mcp_servers.material-maker]
command = "python3"
args = ["<absolute path to the repo>/agent_tools/mcp_server.py"]
tool_timeout_sec = 300
```
Check with `codex mcp list`. AGENTS.md tells Codex to prefer these tools when present.

Tests: `agent_tools/.venv/bin/python -m unittest agent_tools/test_mcp_server.py` (fake engine for the protocol,
tool mapping, argument checks, batch, crash/timeout recovery and a stdio subprocess session; real-engine tests
(edit/render/export, SIGKILL recovery) ~7 s,
`MMX_SKIP_ENGINE=1` skips it). Design ideas (lazy engine start, `--check` preflight, a batch tool that stops
at the first failing op) came from graysonchalmers/Tool-MaterialMaker-MCP (MIT); no code was copied.

## Other
- `proto_0.3/`: throwaway Session 0.3 helpers (export.sh, g.py, sheet.py), superseded by
  `mmx export/sheet/run`; kept for reference.
