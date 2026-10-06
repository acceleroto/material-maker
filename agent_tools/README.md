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
python3 agent_tools/mmx.py catalog            # rebuild catalog.json + agent_docs/NODES.md
python3 agent_tools/mmx.py validate <file.ptex>
python3 agent_tools/mmx.py node <type>        # one type's params/ports as JSON
python3 agent_tools/mmx.py export <file.ptex> --out <dir> [--target "Unity/URP"] [--timeout S] [--keep-meta]
python3 agent_tools/mmx.py sheet <dir> [--out sheet.png]
python3 agent_tools/mmx.py run <file.ptex> --run-name NAME [--note "what changed"]
python3 agent_tools/mmx.py wait (<dir> | --run-name NAME) [--timeout S]
agent_tools/.venv/bin/python -m unittest agent_tools/test_mmx.py -v   # plain python3 skips the sheet test
```

- **catalog**: reads `addons/material_maker/nodes/*.mmg`, `nodes/io_types.mmt` and
  `material_maker/library/*.json`. Writes `agent_tools/catalog.json` (every type: kind, category,
  parameters with type/range/default/enum values, inputs/outputs with 0-based index, type and
  descriptions, port-type conversion table) and the condensed `agent_docs/NODES.md` (~65 types,
  < 600 lines; the curated list is `CURATED` in `mmx.py`). `--nodes-dir DIR` adds another `.mmg`
  dir that overrides repo defs (e.g. the release app's `nodes/` if it differs from the repo).
  Re-run after changing node definitions; commit both outputs.
- **validate**: prints `{"ok": bool, "errors": [...], "warnings": [...]}`; exit 0 if no errors, else 1.
  Each item has `code`, `graph_path` (`/`, `/graph`, ...), `node`, `message`, and often `hint`
  (close-match suggestions, valid ports or the expected parameter format).

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

Type resolution mirrors `MMLoader.create_gen` (`addons/material_maker/engine/loader.gd`): inline
`shader_model` → shader/material; inline `nodes`/`connections` → subgraph (ports from its
`gen_inputs`/`gen_outputs` ios nodes, params from its `gen_parameters` remote); `widgets` → remote;
then built-in types (`buffer`, `switch`, `ios`, `reroute`, `portal`, `image`, `export`, ...; ports
hand-coded from `engine/nodes/gen_*.gd`); then `.mmg` files. Generic nodes expand their `#`
ports/params by the node's `generic_size`, defaulting to the `.mmg`'s own `generic_size`.

### Limitations
- Structural checks only: no shader compilation, expressions in float parameters (`"$time*2"`)
  aren't evaluated, and a valid file can still render nothing useful.
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

**Config** `agent_tools/mmx.toml` (override: `$MMX_CONFIG` or `--config`): `mode` (`release` = the
installed app; `source` = Godot + repo, Phase 2, not implemented), default `target`, `timeout`
(default 180 s; an export takes ~5 s), `[release] binary` and `data_dir` (its `nodes/` is used to
predict outputs).

**export**: `validate` first (errors → exit 1, nothing runs), then plans the expected files from
the Material node's export template for the target (mirrors `MMGenMaterial.export_material`:
`$(connected:x_tex)` conditions vs. the graph's connections into the Material node; an unknown
target fails with close matches). It `mkdir -p`s the out dir, **deletes previous outputs of that
prefix** (MM silently skips existing `.mat`/`.meta` in CLI mode, and old maps would hide a failure;
`--keep-meta` keeps `.meta` files to preserve Unity GUIDs), runs the binary with absolute paths,
`--export-material --target`, stdout+stderr → `<out>/export.log`, and kills it after the timeout.
Success = every expected file exists and is newer than the start (MM's exit code is always 0).
Prints and writes `<out>/mmx_result.json`: `ok`, `stage` (validate/plan/export/done), `error`,
`files` [{file, bytes}], `missing`, `log_errors` (known harmless shutdown noise filtered),
`seconds`, `hints`. Exit 0 ok, 1 validation/plan, 2 export failed.

**sheet**: one PNG of everything in an export dir: `lit` (crude Lambert, light from top-left,
from albedo+normal+AO), `lit tiled 2x2` (seams/repetition), then albedo, normal, height,
roughness, metallic, AO, emission, ... Packed maps are split (Unity `metal_smoothness`: R =
metallic, roughness = 1 − A; Godot `orm`: R/G/B = AO/roughness/metallic). Grayscale tiles are
labeled with min/mean/max so flat or clipped maps are obvious. Default output `<dir>/sheet.png`.

**run**: claims the next `agent_runs/<run>/iter_NNN/` (from 001), copies the ptex there (outputs
are named after it), exports into `iter_NNN/out/`, writes `iter_NNN/sheet.png`,
`mmx_result.json` (export result + `iter_dir`, `sheet`), `mmx_status.json` (running/done) and
`note.md` (`--note`). Validation failures still use up an iteration dir (the result explains why).

**wait**: for when the app has to be launched from the Terminal panel. Start
`mmx run ... --run-name X` with `run_in_terminal`, then from Bash `mmx wait --run-name X` blocks until
the newest iteration has a result (one finished up to `--fresh` 60 s before the call counts), and
prints it. `mmx wait <dir>` waits for a specific out/iteration dir.

**Launching from Claude's Bash tool**: in Phase 0 the app hung forever there (`CAMetalLayer
nextDrawable`). In Session 1.2 it did **not** reproduce: `mmx export`, a plain subprocess and a
direct shell launch all finished in ~5–7 s (6/6). So call `mmx run` from Bash first; if it reports
`error: timeout` (with the hint), use the Terminal panel + `mmx wait`.

Limitations: the lit preview is a flat-plane Lambert approximation (no specular, no parallax) and
assumes OpenGL (+Y) normals; additional `material_export` nodes' files aren't predicted; only the
first material node is checked.

## Other
- `proto_0.3/`: throwaway Session 0.3 helpers (export.sh, g.py, sheet.py), superseded by
  `mmx export/sheet/run`; kept for reference.
