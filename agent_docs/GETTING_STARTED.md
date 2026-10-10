# Getting started: Material Maker for AI agents

This fork lets an AI coding agent (Claude Code, Codex, or anything that speaks MCP or can run shell commands)
**design procedural PBR materials from a text description or a reference photo**, look at its own results in a
lit 3D preview, iterate, and **deliver the finished material into a Unity project**. The material stays
procedural: a Material Maker `.ptex` graph you can keep editing in Material Maker's own editor.

This page is written so you can hand it to your agent: *"Read agent_docs/GETTING_STARTED.md in
https://github.com/acceleroto/material-maker (branch `agent`), install it, and make me a mossy stone wall."*

## Requirements

| | |
|---|---|
| OS | **macOS** (tested: macOS 26, Apple Silicon). Linux probably works but is untested; Windows is untested (some paths assume a POSIX venv layout). |
| Desktop session | Material Maker renders on the GPU through Godot, so it needs a logged-in desktop session with a GPU. It cannot run on a headless server or in a container without a display. Godot briefly opens a 1×1 px window per render. |
| Godot | **Godot 4.7** standard build (not .NET), from <https://godotengine.org/download>. On macOS put `Godot.app` in `/Applications` or pass `--godot` to setup. |
| Python | **3.11+** (`python3 --version`). Setup creates a private venv with Pillow; nothing else is installed globally. |
| Git | to clone the repo. |
| Unity (optional) | Unity 6 (tested 6000.5) via Unity Hub, only if you want `to-unity` hand-off. URP, HDRP and Built-in projects are detected automatically. |

No Material Maker install is needed: the fork runs Material Maker from source inside Godot.

## Install (agent: do these steps)

```bash
git clone -b agent https://github.com/acceleroto/material-maker.git
cd material-maker
python3 agent_tools/setup.py
```

Optional: `--godot /path/to/Godot` (if auto-detection fails) and `--unity-project /path/to/UnityProject` (the default
target for `to-unity`; the matching Unity Hub editor is found automatically).

`setup.py` finds Godot, creates `agent_tools/.venv` with Pillow, imports the Godot project once (a few minutes the
first time), writes your machine's paths to `agent_tools/mmx.local.toml` (gitignored), and runs a smoke test:
export `bricks.ptex`, render its 3D preview (`agent_runs/setup_check/preview.png`; look at it, it should be a lit
brick sphere and plane), and start the MCP engine. It prints a JSON summary and exits 0 when everything works.
Re-running it is safe.

## Connect your agent

**Claude Code:** start `claude` **in the repo root**. The committed `.mcp.json` registers the `material-maker` MCP
server and `.claude/settings.json` enables it; the `material-maker` skill (`.claude/skills/material-maker/`) loads
automatically and tells Claude how to work. Check with `claude mcp get material-maker` (should say Connected).
In the Claude desktop app, open a session in (or move it into) the repo folder; the tools appear on the next turn.

**Codex:** `AGENTS.md` (repo root) holds the same workflow. Add the MCP server once:
```bash
codex mcp add material-maker -- python3 "$PWD/agent_tools/mcp_server.py"
```
and add `tool_timeout_sec = 300` under `[mcp_servers.material-maker]` in `~/.codex/config.toml` (large exports can
take over a minute). Details: `agent_tools/README.md` "MCP server".

**Other MCP clients:** stdio server, command `python3 <repo>/agent_tools/mcp_server.py`. 16 tools: `load`, `save`,
`get_graph`, `describe_node`, `list_nodes`, `add_node`, `remove_node`, `connect`, `disconnect`, `set_param`,
`validate`, `render_preview` (returns the lit 3D image), `render_output` (one node's output, for debugging),
`export`, `batch`, `restart`. Give the agent `AGENTS.md` (or the skill file) as its instructions.

**No MCP:** everything also works from the shell with `python3 agent_tools/mmx.py ...` (about 10 s per
iteration instead of under a second). See "Commands" below.

## Use it

Ask in plain words. Examples that worked in testing (`agent_docs/ACCEPTANCE.md` has the results with images):

- "Make a realistic grey granite cliff face material."
- "Industrial teal painted steel, chipped, with rust in the chips and rust streaks. Put it in my Unity project
  as ChippedPaintMetal."
- "Stylized cartoon lava: dark crust plates and glowing cracks."
- "Polished white Carrara marble floor tiles."
- "Match this photo: agent_refs/my_bark.jpg" (put your photos in `agent_refs/`, which is gitignored).

What the agent does (the skill/AGENTS.md describe it in detail): picks the closest of the 43 example graphs in
`material_maker/examples/`, edits it (or builds new parts), renders the lit 3D preview after every change,
writes a short critique per iteration, and stops when the material matches (usually 4–8 iterations, up to ~20).
For a photo it matches scale, layout, palette (numerically) and roughness, and asks you to steer after ~4
iterations. Iteration files go to `agent_runs/` (gitignored): every iteration's `.ptex`, preview and notes.

**Steering helps.** "Veins too graphic, make them softer and wispy", "seams should fall at random positions",
"more rust, less paint" are all things the agent can act on. You can also open any `.ptex` in Material Maker's
editor yourself.

## Unity hand-off

```bash
python3 agent_tools/mmx.py to-unity <final .ptex> --project <Unity project root> --name MossyStoneWall --verify
```
writes `Assets/Materials/Generated/MossyStoneWall/` (a `.mat` for the project's render pipeline + PNG maps with
correct import settings: albedo sRGB, data maps linear, normal map type). Re-running with the same name updates
the material in place and keeps its GUIDs, so scenes using it stay linked. `--verify` opens the project in
Unity batchmode to check the material, shader and textures; **close the Unity editor on that project first**
(otherwise it reports `editor_open`; without `--verify`, the open editor imports the files when focused).
Floors usually want a higher Tiling (e.g. 4×4) on the Unity material; emissive materials only bloom if the
scene's post-processing Volume has Bloom.

## Commands

All from the repo root; `python3 agent_tools/mmx.py <command> --help` for options.

| Command | What it does |
|---|---|
| `mmx validate <ptex>` | static checks + shader compile (run after every edit) |
| `mmx run <ptex> --run-name <name> [--ref photo]` | one iteration: export Unity maps, 3D preview, contact sheet, notes |
| `mmx preview <ptex>` | just the lit 3D preview PNG |
| `mmx node-preview <ptex> --node <name>` | one node's output (debugging) |
| `mmx palette <photo>` | dominant colours of a reference photo + a ready gradient |
| `mmx compare <preview png> --ref <photo>` | photo beside a preview with palette strips |
| `mmx to-unity <ptex> --project P --name N [--verify]` | deliver into a Unity project |
| `mmx node <type>` | one node type's ports and parameters |

Reference docs: `agent_docs/NODES.md` (node primer), `agent_tools/README.md` (every tool in detail),
`agent_docs/ARCHITECTURE.md` (how the pieces fit), `agent_docs/examples_annotated.md` (example graphs explained).

## Troubleshooting

| Symptom | Fix |
|---|---|
| setup: `godot` step fails | Install Godot 4.7 (standard build) or pass `--godot /path/to/Godot` (on macOS the executable is `Godot.app/Contents/MacOS/Godot`). |
| setup: preview/export test fails right after install | Re-run `setup.py --reimport`; make sure you're in a desktop session (not SSH-only). |
| MCP tools don't appear in Claude Code | Start Claude Code in the repo root; approve the `material-maker` server if asked; `claude mcp get material-maker`. |
| A render "hangs" | The first render after edits on big graphs can take ~20 s (real work). If a call times out, the engine restarts itself and restores the graph; `agent_runs/mcp/engine.log` shows `watchdog:` lines explaining what it waited for. |
| Steam / `SteamAPI_Init` errors in logs | Harmless: the source build looks for Steam and carries on without it. |
| `to-unity --verify` says `editor_open` | Close the Unity editor on that project (or skip `--verify`). |
| `stage: license` from `--verify` | Sign in to Unity Hub / activate a license once. |

## What's in this fork

`agent_tools/` (Python: `mmx.py` CLI, `mm_client.py` engine client, `mcp_server.py`, `unity_handoff.py`,
`setup.py`, tests), `cli_*.gd` + small hooks in `parse_args.gd` (engine command-line modes and the JSON-RPC
server), `.claude/skills/material-maker/` (the agent workflow), `AGENTS.md`, `agent_docs/` (docs, acceptance
results). Everything else is upstream Material Maker, merged regularly.
