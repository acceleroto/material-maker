# Material Maker × AI Agent — Project Plan

**Goal:** Describe a texture in words (or show a photo), and an AI agent in Claude Code builds it in Material Maker, looks at the result, iterates until it matches, and exports it for Unity.

**Who does what:** Claude Code (Opus 5.5) does the engineering. You do the one-time setup, run a few manual checks, and review results at the checkpoints marked **👤 YOU**.

**Budget:** Built around the $20 Pro plan. Work is split into sessions small enough that hitting the 5-hour limit never loses work.

---

## Read this first: three things that shape the plan

1. **Upstream does not accept AI-written PRs.** Material Maker's `CONTRIBUTING.md` says pull requests that used AI/LLM or agentic coding are not allowed, and PR descriptions must be in your own words. Treat this as **your own fork** permanently. Phase 7 covers what you *can* still give back (bug reports, and small fixes you write by hand).
2. **Rendering needs a real GPU and a window.** Material Maker renders through Godot's GPU pipeline, so Godot's `--headless` mode won't work. Run everything on your normal desktop machine. Godot windows will flash open during exports, which is expected.
3. **Opus on Pro.** Opus models use your 5-hour allowance several times faster than Sonnet. Setup step S5 checks that Opus 5.5 is selectable in Claude Code on your plan and explains what to do if it isn't.

---

## How the sessions work

### The rhythm

Each **session** is one focused task with a ready-to-paste prompt. Sessions are sized so most fit comfortably inside one 5-hour window with room to spare.

- **Start every session fresh.** Run `claude` in a new terminal, or type `/clear`. Long conversations re-send their whole history on every turn and burn quota fast.
- **Check your quota before starting.** Type `/usage` in Claude Code. If you're above ~70% of the 5-hour window, wait for the reset rather than starting a big session.
- **Chat counts too.** Claude.ai chat and Claude Code share one usage pool. Heavy chatting on the same day reduces your coding budget.

### The handoff protocol (why running out is safe)

Claude Code maintains two files in the repo:

- `agent_docs/PROGRESS.md` records which session is current, what's done, what's in progress, and the exact next step.
- `CLAUDE.md` holds the standing project rules, which Claude Code reads automatically at startup.

The agent **commits after every working step**, so if your limit hits mid-session, at most a few minutes of work is lost.

### If you hit the limit mid-session

1. Note the reset time Claude Code shows. Don't buy extra usage unless you want to.
2. After the reset, open a **fresh** session and paste the **Resume prompt** below.

### Resume prompt (keep this handy)

```
Read CLAUDE.md and agent_docs/PROGRESS.md, then run `git log --oneline -15` and `git status`.
A previous session was interrupted by a usage limit. Summarize in 3 lines where things stand,
then continue the current session from the "Next step" in PROGRESS.md. Follow all rules in CLAUDE.md.
```

### Modes to use

- **Plan mode** (press `Shift+Tab` until it says plan mode) is for the **first session of each phase**. Claude proposes a plan without changing anything. Read it, and approve it if it looks right.
- **Auto-accept edits** (press `Shift+Tab` until it says accept edits) is for everything else. Combined with the permission allowlist from setup, Claude can work for long stretches without asking you anything.
- **Avoid `--dangerously-skip-permissions`** unless you're running inside a VM or container you don't mind losing. The allowlist gives you nearly the same autonomy without the risk.

---

## Setup (one time) — 👤 YOU, about 45–60 minutes

### S1. Install the tools

| Tool | Where | Notes |
|---|---|---|
| Git | git-scm.com | Accept the defaults. |
| A GitHub account | github.com | Needed for your fork. |
| Python 3.11 or newer | python.org | **Windows:** tick "Add python.exe to PATH" in the installer. |
| Godot **4.7.2** (standard build, not .NET) | godotengine.org → Download → Archive → 4.7.2 | This exact version matches Material Maker's current source. Unzip it somewhere permanent, e.g. `C:\Tools\Godot\` or `~/Tools/Godot/`. |
| Material Maker release (1.5 or newer) | github.com/RodZill4/material-maker/releases or rodzilla.itch.io/material-maker | Unzip to e.g. `C:\Tools\MaterialMaker\`. Used in Phase 0. |
| Unity Hub + a Unity editor | unity.com | You probably have these already. |
| Claude Code | code.claude.com/docs → Quickstart | Follow the install steps for your OS. |

**To verify,** open a new terminal and run:

```
git --version
python --version      (on macOS/Linux this may be python3 --version)
claude --version
```

Each command should print a version number.

### S2. Fork and clone

1. Go to `github.com/RodZill4/material-maker` and click **Fork** (top right). Keep the default name.
2. In a terminal, run these commands. Replace `YOUR-USERNAME`, and choose any parent folder you like:

```
cd ~/Projects                 (Windows: cd C:\Projects)
git clone https://github.com/YOUR-USERNAME/material-maker.git
cd material-maker
git remote add upstream https://github.com/RodZill4/material-maker.git
git checkout -b agent
git push -u origin agent
```

All project work happens on the `agent` branch. `master` stays a clean copy of upstream, which makes pulling in Material Maker updates easy later.

### S3. Create a Unity test project

1. In Unity Hub, click **New project** → **Universal 3D** (URP) template → name it `MM-Agent-Test`.
2. Note the project's full path; you'll need it in S6.

### S4. Write down your paths

Fill these in. You'll paste them into the setup session.

```
Repo path:              ________________________ (e.g. C:\Projects\material-maker)
Godot 4.7.2 binary:     ________________________ (Windows: the ...win64.exe, ideally the *_console.exe one)
Material Maker release: ________________________ (the material_maker executable)
Unity project path:     ________________________
Operating system:       ________________________
```

On **macOS**, the executables sit inside the `.app` bundle, e.g. `Godot.app/Contents/MacOS/Godot`.

### S5. Log in and check the model

1. `cd` into the repo folder and run `claude`.
2. Log in with your Claude account, the same one as your Pro plan. If it offers API credits, decline.
3. Type `/model` and look for **Opus 5.5** in the list.
   - **If it's listed:** select it. You're set.
   - **If it's not listed:** your plan doesn't include Opus in Claude Code right now. You have two options. You can use the default Sonnet model, which handles this whole plan fine with more sessions per window. Or you can use `opusplan` if it's listed, which uses Opus for planning and Sonnet for the hands-on work.
4. **Important:** if you have an `ANTHROPIC_API_KEY` environment variable set, remove it. Otherwise Claude Code bills API rates instead of using your plan.

### S6. Session 0.0 — let Claude set up the project rules

Make sure you're still in the repo, then paste this prompt, filling in your paths from S4:

```
We're starting a multi-session project: making Material Maker usable by AI agents so an agent
can design procedural materials (from text or a reference photo), iterate visually, and export
them to Unity. I'm on a $20 Pro plan, so work is split into sessions and we will hit usage limits.

My environment:
- OS: <OS>
- Repo (my fork, branch `agent`): <REPO PATH>
- Godot 4.7.2 binary: <GODOT PATH>
- Material Maker release binary: <MM RELEASE PATH>
- Unity test project (URP): <UNITY PATH>

Do the following, then stop:
1. Create CLAUDE.md at the repo root with these standing rules:
   - Work only on branch `agent`. Never push to `master`, never force-push, never open PRs upstream.
     (Upstream CONTRIBUTING.md forbids AI-written PRs.)
   - Commit after every working step with clear messages. Never leave more than ~15 minutes of
     uncommitted work.
   - Keep agent_docs/PROGRESS.md current: current session ID, done, in progress, blockers,
     exact "Next step". Update it before every commit.
   - Never run Godot with --headless for rendering or export (it needs a real GPU context).
     Always use --export-material, not --export. Always use --target, never -t (Godot swallows -t).
     Pass absolute paths to the CLI (on macOS the app changes its working directory).
   - Paths for this machine (list them).
   - Follow upstream style for GDScript: Godot style guide, explicit static typing.
   - New Python tooling lives in agent_tools/; docs in agent_docs/.
   - Keep context lean: don't read huge files whole; use grep/head.
   - If a usage limit seems close, finish the current step, commit, update PROGRESS.md.
   Keep CLAUDE.md under 80 lines.
2. Create agent_docs/PROGRESS.md (current session: 0.0 done, next: 0.2) and copy this plan's
   phase list into agent_docs/ROADMAP.md (I'll paste it if you ask).
3. Create .claude/settings.json with a permission allowlist so you can work without prompting me:
   allow file edits in the repo, git status/diff/log/add/commit/checkout/branch/stash,
   python and pip, and running the Godot and Material Maker binaries above.
   Deny: git push --force, git push to master, rm -rf outside the repo, anything touching
   my home directory outside the repo and the Unity project.
4. Add a .gitignore entry for agent_runs/ (iteration outputs).
5. Commit as "Session 0.0: project rules and progress tracking", then push the agent branch.
Show me the final CLAUDE.md and settings.json.
```

👤 **Review:** read `CLAUDE.md` and `.claude/settings.json`. If anything in the deny list looks too loose, or the allow list too tight, tell Claude to fix it. You can also check permissions anytime with `/permissions`.

Optionally, save a copy of this plan into the repo as `agent_docs/ROADMAP.md` so the agent can always refer to it.

---

## Phase 0 — Smoke test (no code changes)

**Goal:** prove that the existing CLI → Unity pipeline works on your machine, and see how well the agent handles `.ptex` files before building anything.

### 0.1 Manual export — 👤 YOU, about 15 minutes

1. Open a terminal in your Material Maker release folder. It contains an `examples` folder.
2. Run the export.

   **Windows (PowerShell):**
   ```
   .\material_maker.exe --export-material --target "Unity/URP" -o C:\mm-test\out examples\bricks.ptex
   ```
   If there's a `material_maker.console.exe`, use that instead; it shows log output.

   **macOS / Linux:**
   ```
   ./material_maker --export-material --target "Unity/URP" -o ~/mm-test/out examples/bricks.ptex
   ```
3. A window may flash open and close; that's normal. Check the `out` folder for PNG textures plus a `.mat` file.
4. Copy the whole `out` folder into your Unity project's `Assets` folder. In Unity, drag the material onto a sphere (GameObject → 3D Object → Sphere).

**Did it work?**
- ✅ The sphere shows bricks → you're done with 0.1.
- ❌ The app closes immediately with no output → create a text file named `steam_appid.txt` containing just `4110830` next to the executable and try again. (A Steam integration in the app can otherwise restart and quit it.)
- ❌ Magenta or pink material in Unity → you exported the wrong target for your pipeline. Try `Unity/3D` for the Built-in pipeline, or `Unity/HDRP`.
- ❌ Anything else → paste the terminal output into Claude Code and ask it to diagnose.

Note: the `--size` flag currently has no effect; exports always come out at 2048. Phase 2 fixes this.

Also: always write `--target`, never `-t`. Godot itself claims `-t` (its "always on top" flag), so the target never reaches Material Maker and it silently falls back to the Godot export (you get a `.tres` file and no `.mat`). On macOS, give the `.ptex` file as a full absolute path, because the app switches its working folder at startup.

Tell Claude Code what happened. It records the result in PROGRESS.md.

### 0.2 Agent edits an existing graph — 🤖 one short session

```
Session 0.2. Read CLAUDE.md and agent_docs/PROGRESS.md.
Using the Material Maker RELEASE binary (not source), take examples/bricks.ptex from the release
folder, copy it to agent_runs/0.2/, and:
1. Read the .ptex JSON and explain its structure in 10 lines (nodes, parameters, connections,
   the Material node and its ports).
2. Make two visible changes by editing parameters only (e.g. brick size and mortar color).
3. Export with --export-material --target "Unity/URP" into agent_runs/0.2/out/.
4. Look at the exported albedo and normal PNGs and say whether your changes show up as expected.
5. Write agent_docs/phase0_notes.md: what was easy, what was confusing, how long one export
   took, any errors.
Commit and update PROGRESS.md (next: 0.3).
```

👤 **Check:** open the PNGs in `agent_runs/0.2/out/`. Do the changes look right?

### 0.3 A tiny real loop — 🤖 one session

```
Session 0.3. Read CLAUDE.md, PROGRESS.md and agent_docs/phase0_notes.md.
Goal: "weathered red roof tiles, slightly mossy, stylized". Start from the closest example in
the release's examples/ folder. Iterate at most 5 times: edit the .ptex, export (Unity/URP),
view the PNGs, critique against the goal, adjust. Save every iteration to agent_runs/0.3/iter_N/
with a one-paragraph critique.md each. Do not exceed 5 iterations.
Then append to phase0_notes.md: did the loop converge? What blocked you most (judging flat maps,
graph wiring, slow exports, unknown node types)? Which tools would have helped most?
Commit, update PROGRESS.md (next: 0.4 — human decision).
```

### 0.4 Decision — 👤 YOU, about 10 minutes

Open `agent_runs/0.3/`, look through the iterations, and read `phase0_notes.md`. Then decide:

- **Pipeline works and the agent made reasonable progress** → continue to Phase 1 (the normal path).
- **The agent couldn't judge results from flat maps** → still do Phase 1, then prioritize Phase 4 (preview rendering).
- **Export failed on your machine** → stop and troubleshoot with Claude before going further.

---

## Phase 1 — Wrapper and skill (no changes to Material Maker itself)

**Goal:** get as much of the loop as possible working by wrapping the existing CLI. Everything lives in `agent_tools/` and `.claude/skills/`. Expect about 3 sessions.

### 1.1 Node catalog and validator — 🤖 (use plan mode first)

```
Session 1.1. Read CLAUDE.md and PROGRESS.md. Use plan mode first; I'll approve.
Build agent_tools/mmx.py (Python, stdlib + Pillow only) with:
- `mmx catalog`: parse addons/material_maker/nodes/*.mmg and material_maker/library/*.json
  into agent_tools/catalog.json (node type, category, parameters with types/ranges/defaults,
  inputs, outputs). Also write agent_docs/NODES.md: a condensed, human/agent-readable reference
  of the ~60 most useful node types (patterns, noise, filters, transforms, blend, colorize,
  normal map, material). Keep NODES.md under 600 lines.
- `mmx validate <file.ptex>`: check every node type exists, every connection references real
  ports, parameter names/types are valid. Output JSON: {"ok": bool, "errors": [...]} so an
  agent can self-correct. Exit code 0/1.
Test validate against all .ptex files in material_maker/examples (they should all pass) and on
3 deliberately broken copies. Note: dynamic node types (graphs, remote, ios) may not be in .mmg
files — handle them gracefully and document limitations.
Commit often. Update PROGRESS.md (next: 1.2).
```

### 1.2 Export wrapper and review sheets — 🤖

```
Session 1.2. Read CLAUDE.md and PROGRESS.md.
Extend agent_tools/mmx.py:
- `mmx export <ptex> --target "Unity/URP" --out <dir>`: run validate first; call the Material
  Maker binary with --export-material; enforce a timeout; capture stdout/stderr to a log; detect
  failures by checking expected output files exist (the CLI doesn't return error codes yet);
  print a JSON summary of files written.
- `mmx sheet <dir>`: build one labeled contact-sheet PNG (albedo, normal, roughness, metallic,
  AO, height — whatever exists) so a single image shows the whole material.
- `mmx run <ptex> --run-name X`: create agent_runs/X/iter_NNN/ automatically, copy the ptex,
  export, make the sheet. One command per iteration.
- Config file agent_tools/mmx.toml for binary paths (default to the release binary; Phase 2 will
  add a "source" mode using Godot + repo).
Write short tests. Commit often. Update PROGRESS.md (next: 1.3).
```

### 1.3 The agent skill and an end-to-end test — 🤖

```
Session 1.3. Read CLAUDE.md and PROGRESS.md.
1. Create .claude/skills/material-maker/SKILL.md: when to use it; the iteration workflow
   (start from the closest example/library material → mmx validate → mmx run → view sheet →
   critique against the request → change one or two things → repeat; cap iterations at 8;
   save critiques); how to read the contact sheet; common pitfalls you've seen in this project.
   Point to agent_docs/NODES.md rather than inlining it. Also create AGENTS.md at the repo
   root with the same workflow so Codex can use it too.
2. Add agent_docs/examples_annotated.md: 4 example graphs explained (what each node does and why).
3. End-to-end test, 3 requests, max 6 iterations each:
   "dry cracked desert ground", "brushed steel panel with rivets", "old oak planks, stylized".
   Use only the skill + mmx. Save to agent_runs/1.3/.
4. Write agent_docs/phase1_report.md: success per request, average seconds per iteration,
   top 3 problems, recommendation for which of Phases 2–5 matter most.
Commit, update PROGRESS.md (next: checkpoint 1).
```

### Checkpoint 1 — 👤 YOU, about 15 minutes

1. Look at the final contact sheets in `agent_runs/1.3/`.
2. Read `phase1_report.md`.
3. **Try it yourself:** in a fresh Claude Code session, ask for any material in plain words and watch it work.

If you're happy with it, you could stop here. Everything after this point improves speed and judgment.

---

## Phase 2 — Fork basics: fix the CLI

**Goal:** make the CLI reliable for machines: correct sizes, real exit codes, JSON output. From here on, Material Maker runs **from source** via Godot.

### Setup B — 👤 YOU, about 15 minutes (once)

1. Open Godot 4.7.2. In the project manager, click **Import**, select `project.godot` in your repo, and open it. The first import takes a few minutes.
2. In the editor, go to **Editor → Editor Settings → Run → Window Placement → Game Embed Mode** and set it to **Disabled**. Material Maker's contributing guide says the app may not launch otherwise.
3. Press **F5** (Run). Material Maker should open. Close it and close Godot.
4. Tell Claude Code: "Setup B done; Material Maker runs from source."

### 2.1 Fix `--size`, add exit codes and JSON output — 🤖 (plan mode first)

```
Session 2.1. Read CLAUDE.md and PROGRESS.md. Use plan mode first.
We now run Material Maker from source: <GODOT> --path <REPO> --export-material ...
(Confirm this invocation works first with examples/bricks.ptex.)
In parse_args.gd (the project's main scene):
1. Bug: --size is parsed into texture_size but export_files() is always passed image_size=2048.
   Fix so --size is honored (0 = use the graph's own size).
2. Exit codes: 0 success, 1 bad arguments, 2 load/parse failure, 3 export failure.
   Use get_tree().quit(code).
3. `--json`: print one machine-readable summary line at the end (files written, target actually
   used, warnings, errors). Note the target "similarity" fallback silently picks a different
   profile when the name doesn't match — report that as a warning, and add `--strict-target`
   to fail instead.
4. Errors to stderr, not stdout.
Keep changes minimal and isolated to parse_args.gd where possible. Add GUT tests under test/
for argument parsing (GUT is in addons/gut; run via its command-line script). Update mmx to
support "source" mode and use the exit codes/JSON. Commit often. Update PROGRESS.md (next: 3.1).
```

---

## Phase 3 — Ask the engine itself

**Goal:** replace guesswork from parsing JSON files with answers from Material Maker's own engine, which also understands dynamic nodes.

### 3.1 List, describe, and validate via the engine — 🤖 (plan mode first)

```
Session 3.1. Read CLAUDE.md and PROGRESS.md. Use plan mode first.
Add CLI modes (in parse_args.gd or a new script it delegates to):
- --list-nodes --json: every available node type with category and short description,
  from the same source the editor's "add node" menu uses.
- --describe-node <type> --json: parameters (name, type, range, default), input and output
  ports with types, as reported by the instantiated generator.
- --validate <ptex> --json: load via mm_loader, report missing types, bad connections, and
  shader compile errors for every output (use the engine's shader generation, not rendering).
Regenerate agent_tools/catalog.json and NODES.md from these. Make mmx validate call the engine
version (keep the Python one as a fast pre-check). Add tests. Commit often.
Update PROGRESS.md (next: 4.1).
```

If this session runs long, it's fine for it to span two windows; the handoff protocol covers it.

---

## Phase 4 — Preview rendering (the biggest upgrade for judging results)

**Goal:** the agent sees what the material looks like **lit on a 3D shape**, not just as flat maps. Expect 2–3 sessions.

### 4.1 Render any node's output — 🤖 (plan mode first)

```
Session 4.1. Read CLAUDE.md and PROGRESS.md. Use plan mode first.
Add --render-output <ptex> --node <name> --port <n> --size <px> -o <png>: render a single
node's output to PNG using the existing renderer (addons/material_maker/engine/renderer.gd,
multi_renderer.gd). This lets the agent debug a graph stage by stage.
Add `mmx node-preview`. Test on 5 nodes in 2 example graphs. Commit. Update PROGRESS.md (next: 4.2).
```

### 4.2 Lit 3D preview — 🤖 (plan mode first)

```
Session 4.2. Read CLAUDE.md and PROGRESS.md. Use plan mode first.
Add --render-preview <ptex> --mesh sphere|plane|cube --env <name> --size <px> -o <png>:
apply the material to a mesh (see material_maker/meshes and material_maker/environments)
with a fixed camera and lighting, render one frame, save PNG. Default: sphere + plane side
by side under one consistent, neutral environment, so iterations are comparable.
Study how the editor's 3D preview panel does this and reuse it rather than reinventing it.
Add `mmx preview` and include the 3D render as the top row of `mmx sheet`.
Update SKILL.md and AGENTS.md: the 3D preview is now the primary image to judge.
Commit often. Update PROGRESS.md (next: 4.3).
```

### 4.3 Buffer and polish — 🤖

```
Session 4.3. Read CLAUDE.md and PROGRESS.md. Finish anything left from 4.1/4.2, then re-run
the three Phase 1.3 test requests using the 3D preview. Write agent_docs/phase4_report.md
comparing quality and iteration count with phase1_report.md. Commit. Update PROGRESS.md (next: 5.1).
```

### Checkpoint 4 — 👤 YOU

Compare the Phase 1 and Phase 4 results. If the previews made a clear difference, the core of the project is done. Phase 5 is about speed.

---

## Phase 5 — Persistent server (speed) and MCP

**Goal:** stop relaunching Godot for every iteration. A long-running process holds the graph in memory and accepts commands. Expect about 3 sessions.

### 5.1 Server mode — 🤖 (plan mode first)

```
Session 5.1. Read CLAUDE.md and PROGRESS.md. Use plan mode first.
Add --serve: a long-running mode reading JSON-RPC requests line-by-line on stdin, replying on
stdout (logs to stderr). Methods: load, save, list_nodes, describe_node, add_node, remove_node,
connect, disconnect, set_param, get_graph, validate, render_output, render_preview, export,
shutdown. Use MMGenGraph methods (add_generator, connect_children, set_parameter, ...) rather
than editing JSON. Every response: {"ok":..., "result"|"error":...}.
Add a Python client in agent_tools/mm_client.py and tests. Measure: seconds per iteration,
server vs relaunch. Commit often. Update PROGRESS.md (next: 5.2).
```

### 5.2 MCP server — 🤖

```
Session 5.2. Read CLAUDE.md and PROGRESS.md.
Wrap the --serve process as a stdio MCP server (agent_tools/mcp_server.py) exposing the same
operations as tools, with clear descriptions and JSON schemas, and returning preview images so
the agent can see them. Register it for this project in Claude Code (project-scoped config) and
document how to add it to Codex. Reference: the community project "Tool-MaterialMaker-MCP" by
graysonchalmers takes a similar approach — read it for ideas only; do not copy its code unless
you've confirmed its license allows it. Update SKILL.md/AGENTS.md to prefer MCP tools when
available. Commit. Update PROGRESS.md (next: 5.3).
```

### 5.3 Hardening — 🤖

```
Session 5.3. Read CLAUDE.md and PROGRESS.md. Robustness pass: server crash recovery (client
restarts it and reloads the last saved graph), timeouts, malformed requests, very large sizes,
missing files. Add tests. Run the full test suite. Write agent_docs/ARCHITECTURE.md (one page:
components and how they connect). Commit. Update PROGRESS.md (next: 6.1).
```

---

## Phase 6 — The finished workflow

### 6.1 Photo references — 🤖

```
Session 6.1. Read CLAUDE.md and PROGRESS.md.
Support a reference photo as the TARGET to match (do not feed the photo into the graph):
- `mmx palette <photo>`: extract 5–8 dominant colors as hex + share, for setting
  gradient/colorize nodes.
- Contact sheet option that places the reference photo beside the 3D preview.
- SKILL.md/AGENTS.md: a photo workflow — compare scale, shape, coverage, palette, roughness;
  expect a convincing match, not a pixel copy; ask the user to steer after ~4 iterations.
Test with any free CC0 photo texture you can find in the repo's examples, or ask me for one.
Commit. Update PROGRESS.md (next: 6.2).
```

👤 **Tip:** keep a folder of your own reference photos. They work best when shot straight-on in soft, even light. Put them in `agent_refs/` (Claude adds it to `.gitignore` if you want).

### 6.2 Unity hand-off — 🤖 (with one 👤 step)

👤 **Before this session:** find your Unity editor's executable path (Unity Hub → Installs → ⚙ → Show in Explorer/Finder) and tell Claude Code. Close the Unity editor during this session.

```
Session 6.2. Read CLAUDE.md and PROGRESS.md. Unity editor path: <UNITY EDITOR PATH>.
- `mmx to-unity <ptex> --project <UNITY PATH> --name <MaterialName>`: export with the right
  pipeline target into Assets/Materials/Generated/<MaterialName>/.
- Optional verification: a tiny Editor script + Unity -batchmode -quit -executeMethod run that
  imports the folder and reports whether the material, its shader, and its textures resolved
  (logs to a file). If batchmode needs a license step I must do, stop and tell me exactly what.
Commit. Update PROGRESS.md (next: 6.3).
```

### 6.3 Acceptance test — 🤖 then 👤

```
Session 6.3. Read CLAUDE.md and PROGRESS.md. Final acceptance run using only the skill/MCP tools:
5 text requests (mix of natural, man-made, stylized, realistic) + 2 photo-reference requests
(ask me for photos). Max 8 iterations each, all delivered into the Unity project.
Write agent_docs/ACCEPTANCE.md with each final preview, iteration count, time, and honest notes.
Commit. Update PROGRESS.md (next: done; maintenance mode).
```

👤 **Grade it:** open the Unity project and look at all 7 materials. Note anything you'd want improved and give it to Claude as a short follow-up session.

---

## Phase 7 — Giving back to upstream (optional, and limited)

Because upstream doesn't allow AI-written pull requests, **don't submit this fork's code as a PR.** What you *can* do:

1. **File bug reports in your own words.** The `--size` bug in `parse_args.gd` is a clear, useful one. Follow their issue template: Material Maker version, OS and GPU, expected vs. actual behavior, and the command you ran.
2. **Write small fixes yourself.** The `--size` fix is a few lines. If you write it by hand, you could submit that as a normal PR under their rules.
3. **Suggest features.** An issue describing the use case (scriptable export with exit codes, a preview-render CLI) lets the maintainer decide whether they want it and how.
4. **Keep your fork current:** `git fetch upstream`, then merge or rebase `upstream/master` into `agent`. Claude Code can do this, as a maintenance session, whenever upstream releases.

---

## Appendix

### Session count at a glance

| Phase | Agent sessions | Your time |
|---|---|---|
| Setup | 1 | about 1 hour |
| 0 Smoke test | 2 | about 30 minutes |
| 1 Wrapper + skill | 3 | about 15 minutes |
| 2 CLI basics | 1 | about 15 minutes |
| 3 Engine introspection | 1–2 | minimal |
| 4 Preview rendering | 2–3 | about 10 minutes |
| 5 Server + MCP | 3 | minimal |
| 6 Workflow | 3 | about 30 minutes |
| **Total** | **about 16–18** | **about 3 hours** |

On Pro with Opus, plan on roughly one to two sessions per 5-hour window, and you'll likely hit the weekly limit at some point too. Phases 1, 5.3, and 6.1 are fairly mechanical; switching those to Sonnet with `/model` stretches your quota if needed.

### Troubleshooting

- **The app quits instantly with no output** → put `steam_appid.txt` containing `4110830` next to the executable (release) or at the repo root (source).
- **"Unknown option" or a Godot build error** → you used `--export`. Use `--export-material`.
- **Nothing renders or textures come out black** → something launched Godot with `--headless`. Remove it.
- **Godot errors when running from source** → wrong Godot version. Use exactly 4.7.2 (check `config/features` in `project.godot`).
- **Claude keeps asking permission** → run `/permissions` and approve the command pattern. Ask Claude to update `.claude/settings.json`.
- **You're being billed API rates** → an `ANTHROPIC_API_KEY` environment variable is set. Remove it, run `/logout`, then `/login` with your plan account.
- **The agent seems lost after a reset** → use the Resume prompt, and make sure PROGRESS.md's "Next step" is specific.
