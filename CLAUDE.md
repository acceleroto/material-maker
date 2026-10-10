# CLAUDE.md — Material Maker Agent project

Goal: make Material Maker usable by AI agents (design procedural materials from text or a
reference photo, iterate visually, export to Unity). Work is split across sessions; see
`agent_docs/ROADMAP.md` for the full plan (phases + session prompts) and `agent_docs/PROGRESS.md` for current state.

## Start of every session
1. Read `agent_docs/PROGRESS.md` and do its "Next step".
2. `git status` and confirm you are on branch `agent`.

## Git rules (hard rules)
- Work only on branch `agent`. Push only with `git push origin agent`.
- Never push to `master`, never force-push, never push to `upstream`, never open PRs upstream.
  (Upstream CONTRIBUTING.md forbids AI-written PRs.)
- Commit after every working step with a clear message (`Session X.Y: <what>`).
  Never leave more than ~15 minutes of uncommitted work.
- Update `agent_docs/PROGRESS.md` before every commit.

## PROGRESS.md format
Keep it current: current session ID, Done, In progress, Blockers, and an exact
"Next step" that a fresh session could execute without other context.

## Usage limits
The user is on a Pro plan; limits will hit. If a limit seems close: finish the current
step, update PROGRESS.md, commit, push. Don't start large new steps late in a session.

## Running Godot / Material Maker
- Never run Godot with `--headless` for rendering or export (it needs a real GPU context).
- Always use `--export-material`, not `--export` (the latter is Godot's project export).
- Always use `--target`, never `-t`: Godot swallows `-t` ("always on top"), so MM silently
  falls back to the Godot export (a `.tres`, no `.mat`).
- Pass absolute paths to the CLI (input `.ptex`, `-o` dir): on macOS the app changes its
  working directory at startup, so relative paths break.
- If the app quits instantly with no output, add `steam_appid.txt` containing `4110830`
  next to the executable (release) or at the repo root (source).
- Iteration outputs go in `agent_runs/` (gitignored).
- Export with `python3 agent_tools/mmx.py run <ptex> --run-name X` (or `mmx export`); it handles
  absolute paths, `mkdir -p`, timeout, logging and output checks. In Phase 0 the app hung forever
  when launched from the Bash tool (`CAMetalLayer nextDrawable`); since Session 1.2 it works from
  Bash. If `mmx` reports `error: timeout`, launch it via the Terminal panel (`run_in_terminal`) and
  poll with `mmx wait --run-name X` from Bash. Verify edits took effect by md5-diffing outputs
  against a baseline.

## Paths on this machine
- Repo:              `/Volumes/External1/Users/bryan/Documents/Material Maker Agent/material-maker`
- Godot 4.7.2:       `/Applications/Godot.app/Contents/MacOS/Godot`
- Material Maker:    `/Applications/Material Maker.app/Contents/MacOS/Material Maker`
- From source (since Setup B; mmx default `mode = "source"` since 2.1):
  `<Godot> --path <Repo> --export-material --target "Unity/URP" -o <abs dir> <abs .ptex>`
  (works from Bash, ~5 s, output identical to the release). Since 2.1 also `--size N`, `--json`
  (one summary line), `--strict-target`; exit codes 0 ok / 1 bad args / 2 load / 3 export; errors on
  stderr (details in `agent_tools/README.md`). macOS has no `timeout` command.
- MM release data:   `/Applications/Material Maker.app/Contents/MacOS/` (library, nodes, export, ...)
- Unity project:     `/Volumes/External1/Users/bryan/Documents/MM-Agent-Test`
- OS: macOS Tahoe 26.3.1(a). Note `$HOME` is `/Volumes/External1/Users/bryan`.

## Agent tools
- Node reference: `agent_docs/NODES.md`; full data `agent_tools/catalog.json`; one type:
  `python3 agent_tools/mmx.py node <type>`.
- Run `python3 agent_tools/mmx.py validate <file.ptex>` after every `.ptex` edit, before exporting
  (Python checks, then the engine's `--validate`: types, connections, shader compile; `--fast` = Python only).
  See `agent_tools/README.md` for error codes and limitations.
- Engine inspection (source mode, since 3.1; `cli_inspect.gd`): `<Godot> --path <Repo> --list-nodes --json`,
  `--describe-node <type>...|--all --json`, `--validate <abs ptex>... --json` (exit 0/1/2/4). `mmx catalog`
  regenerates `catalog.json` + `NODES.md` from them (`--static` = Python-only).
- Lit 3D preview (since 4.2): `python3 agent_tools/mmx.py preview <ptex>` (engine `--render-preview <abs ptex>
  [--mesh sphere+plane] [--env Studio] [--size px] -o <abs png> --json`); `mmx run` renders it into
  `iter_NNN/preview_3d.png` and the top row of `sheet.png`. It is the primary image to judge.
- Per-node preview (since 4.1): `python3 agent_tools/mmx.py node-preview <ptex> --node <name> [--port N]`
  (engine `--render-output <abs ptex> --node <name> [--port n] [--size px] -o <abs png> --json`, exit 0/1/2/3).
- Engine server (since 5.1): `<Godot> --path <Repo> --serve` (`cli_serve.gd`, JSON-RPC lines on stdin/stdout:
  load/save/list_nodes/describe_node/add_node/remove_node/connect/disconnect/set_param/get_graph/validate/
  render_output/render_preview/export/shutdown); Python client `agent_tools/mm_client.py` (`MMClient`, `batch`, `bench`).
  ~0.5 s per edit+preview vs ~4–7 s relaunching; outputs byte-identical to the CLI. README "Server mode".
- MCP server (since 5.2): `agent_tools/mcp_server.py` wraps `--serve` as MCP tools (`mcp__material-maker__*`,
  registered in `.mcp.json`); render tools return images. Prefer it for material iteration when loaded;
  `python3 agent_tools/mcp_server.py --check` tests the engine start. README "MCP server" (also Codex setup).
  Since 5.3 a crash/timeout restarts the engine and restores the last loaded/saved graph + edits (MMClient).
- Reference photos (since 6.1): `mmx palette <photo>` (dominant colours + paste-ready colorize gradient),
  `mmx run ... --ref <photo>` (photo beside the 3D preview + palette strips on every sheet of the run),
  `mmx compare <preview png> --ref <photo>`. The photo is a target, never a graph input; user photos in
  `agent_refs/` (gitignored). Workflow: SKILL.md "Matching a reference photo".
- Unity hand-off (since 6.2): `python3 agent_tools/mmx.py to-unity <ptex> --project <Unity root> --name <Name>
  [--verify]` → `Assets/Materials/Generated/<Name>/` with the target matching the project's pipeline; GUIDs kept
  on re-export; clean texture metas. `--verify` = Unity batchmode check (editor must be closed on that project).
  Unity 6000.5.5f1: `/Applications/Unity/Hub/Editor/6000.5.5f1/Unity.app/Contents/MacOS/Unity` (`mmx.toml [unity]`).
- Component overview: `agent_docs/ARCHITECTURE.md`.
- After editing `.claude/skills/material-maker/SKILL.md`, run `python3 agent_tools/sync_agents_md.py` (AGENTS.md
  mirrors the skill body; `--check` reports drift).
- `mmx export` / `sheet` / `run` / `wait`: see `agent_tools/README.md`; config in `agent_tools/mmx.toml`.
  `sheet`/`run` need Pillow in `agent_tools/.venv` (setup line in the README).

## Code style
- GDScript: follow upstream style and the Godot style guide; explicit static typing
  (`var x: int`, typed function args and return types).
- New Python tooling lives in `agent_tools/`; docs live in `agent_docs/`.
- Keep changes to upstream files minimal and isolated so they stay easy to rebase.

## Context hygiene
- Don't read huge files whole (e.g. `.mmg`/`.ptex` JSON, large `.gd`/`.tscn`); use
  `grep -n`, `head`, `sed -n 'A,Bp'`, or Read with offset/limit.
- Prefer targeted searches over directory dumps.
