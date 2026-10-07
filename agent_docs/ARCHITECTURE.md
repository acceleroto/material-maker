# Architecture

How the agent tooling around Material Maker (MM) fits together. Details: `agent_tools/README.md`;
plan and history: `ROADMAP.md`, `PROGRESS.md`.

```
 Agent (Claude Code / Codex)
   │  reads SKILL.md / AGENTS.md (the loop), NODES.md + catalog.json (node reference)
   │
   ├── MCP tools (preferred) ──► agent_tools/mcp_server.py ──┐   stdio MCP, schemas, image results
   │                                                          ▼
   │                                           agent_tools/mm_client.py (MMClient)   restart + restore
   │                                                          │  JSON lines on stdin/stdout
   │                                                          ▼
   │                                 Godot --path <repo> --serve  ─► cli_serve.gd  (one graph in memory)
   │
   └── shell ──► agent_tools/mmx.py ──► one Godot launch per step:
                   validate (Python + --validate)      --export-material  (parse_args.gd)
                   export / run / preview / node-preview   --validate --render-output --render-preview
                   sheet (Pillow), catalog, node, wait      --list-nodes --describe-node (cli_inspect.gd)
                                                          ▼
                       MM engine (upstream addons/material_maker: MMGenGraph, mm_loader, mm_deps,
                       MMGenMaterial export, compute-shader renderer, 3D preview scene)
                                                          ▼
              agent_runs/ (gitignored: renders, sheets, exports, logs) ──► Unity project (.mat + PNG maps)
```

## Engine side (GDScript, repo root; runs inside MM's Godot project, never `--headless` for rendering)
- **`parse_args.gd`** (upstream, minimally changed): command-line entry. `--export-material` (exit codes, `--json`,
  `--size` ≤ 8192, `--strict-target`); dispatches `--serve` to `cli_serve.gd` and the inspection/render modes to
  `cli_inspect.gd`.
- **`cli_inspect.gd`**: `--list-nodes`, `--describe-node`, `--validate` (structure, connections, missing files,
  SPIR-V compile of every output), `--render-output` (one node output → PNG via `render_output_to_texture`).
  Also the shared helpers (`load`, `validate_gen`, `render_node`, size limits) used by the server.
- **`cli_preview.gd`**: `--render-preview`: the editor's 3D preview scene (sphere/plane/cube, HDRI environment)
  in an own-world SubViewport, deterministic output.
- **`cli_serve.gd`**: `--serve`: one long-running process, JSON-RPC lines on stdin/stdout, requests handled in
  order; keeps one graph and edits it through MMGenGraph methods (`add_generator`, `connect_children`,
  `set_parameter`); load/save/validate/render/export reuse the CLI code, so outputs are byte-identical. Works
  around two engine hangs (freeing nodes during renders; export replacing the Material preview textures).
- Tests: GUT `test/test_parse_args.gd`, `test_cli_inspect.gd`, `test_cli_serve.gd` (parsing and value coercion).

## Python side (`agent_tools/`, stdlib only except Pillow for sheets/palettes in `.venv`)
- **`mmx.toml`**: Godot/MM paths, mode (`source`), target (Unity/URP), timeouts, preview defaults.
- **`mmx.py`**: file-based workflow, one engine launch per step: `validate` (Python schema checks against
  `catalog.json`, then engine `--validate`), `export`, `preview`, `node-preview`, `sheet` (contact sheet: 3D preview
  + maps), `run` (an `iter_NNN/` folder per iteration), `wait`, `catalog` (regenerates `catalog.json` + `NODES.md`
  from `--list-nodes`/`--describe-node`), `node`; reference photos (Pillow only, no engine): `palette`, `compare`,
  `run --ref` (the run's `reference.*` beside the 3D preview + palette strips on every sheet).
- **`mm_client.py`**: `MMClient` drives one `--serve` process: request ids, noise filtering, per-method timeouts,
  and crash recovery: on a timeout or crash it restarts the engine, reloads the last loaded/saved graph and replays
  the edits made since. CLI `batch` and `bench`.
- **`mcp_server.py`**: MCP over stdio (registered in `.mcp.json` for Claude Code; Codex via `codex mcp add`).
  One tool per server method + `batch` + `restart`; checks arguments against the tool schemas, resolves repo-relative
  paths, picks default output paths under `agent_runs/mcp/<graph>/`, returns renders as image content. Starts the
  engine lazily on the first call.
- Tests: `test_mmx.py`, `test_mm_client.py`, `test_mcp_server.py` (fake engines for protocol and failure paths, plus
  real-engine tests; `MMX_SKIP_ENGINE=1` skips the latter).

## Knowledge for the agent (`agent_docs/`, `.claude/skills/`)
- **`.claude/skills/material-maker/SKILL.md`** (copied into **`AGENTS.md`** for Codex): the iteration loop (closest
  example → edit → render the 3D preview → critique → repeat, cap 8), pitfalls, MCP vs `mmx` usage.
- **`NODES.md`** (curated node reference + .ptex primer), `catalog.json` (all node types, ports, parameters),
  `examples_annotated.md`; phase reports and `phase0_notes.md` hold findings.

## Data flow of one iteration (MCP path)
`load` example `.ptex` → `set_param`/`add_node`/`connect` (in memory, ~0.01 s) → `render_preview` (~0.5 s,
image returned) → critique → `save` to `agent_runs/<run>/iter_NNN.ptex` (also the crash-recovery point) →
at the end `validate` + `export` → Unity/URP `.mat` + PNG maps → copied into the Unity project.
