# CLAUDE.md — Material Maker Agent project

Goal: make Material Maker usable by AI agents (design procedural materials from text or a
reference photo, iterate visually, export to Unity). Work is split across sessions; see
`agent_docs/ROADMAP.md` for phases and `agent_docs/PROGRESS.md` for current state.

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
- Iteration outputs go in `agent_runs/` (gitignored).

## Paths on this machine
- Repo:              `/Volumes/External1/Users/bryan/Documents/Material Maker Agent/material-maker`
- Godot 4.7.2:       `/Applications/Godot.app/Contents/MacOS/Godot`
- Material Maker:    `/Applications/Material Maker.app/Contents/MacOS/Material Maker`
- MM release data:   `/Applications/Material Maker.app/Contents/MacOS/` (library, nodes, export, ...)
- Unity project:     `/Volumes/External1/Users/bryan/Documents/MM-Agent-Test`
- OS: macOS Tahoe 26.3.1(a). Note `$HOME` is `/Volumes/External1/Users/bryan`.

## Code style
- GDScript: follow upstream style and the Godot style guide; explicit static typing
  (`var x: int`, typed function args and return types).
- New Python tooling lives in `agent_tools/`; docs live in `agent_docs/`.
- Keep changes to upstream files minimal and isolated so they stay easy to rebase.

## Context hygiene
- Don't read huge files whole (e.g. `.mmg`/`.ptex` JSON, large `.gd`/`.tscn`); use
  `grep -n`, `head`, `sed -n 'A,Bp'`, or Read with offset/limit.
- Prefer targeted searches over directory dumps.
