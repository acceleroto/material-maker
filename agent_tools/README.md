# agent_tools

Python tooling that lets an AI agent work with Material Maker. Python 3.9+, stdlib only.

## mmx.py

```
python3 agent_tools/mmx.py catalog            # rebuild catalog.json + agent_docs/NODES.md
python3 agent_tools/mmx.py validate <file.ptex>
python3 agent_tools/mmx.py node <type>        # one type's params/ports as JSON
python3 -m unittest agent_tools/test_mmx.py -v
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

## Other
- `proto_0.3/`: throwaway Session 0.3 helpers (export.sh, g.py, sheet.py), to be replaced by
  `mmx export/sheet/run` in Session 1.2.
