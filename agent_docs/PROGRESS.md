# Progress

**Current session:** 1.1 (in progress)

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

## In progress
- 1.1: `mmx catalog` + `mmx validate` + `mmx node` done; tests pass (`agent_tools/test_mmx.py`, 43 examples +
  broken copies). Remaining: `agent_tools/README.md` (usage + limitations), final PROGRESS update.

## Blockers
- None hard. Open question: why `Bricks.repeat`/`rows`/`columns` edits are ignored on export
  (check in GUI when convenient). Exports must run via `run_in_terminal`.

## Next step
- Session 1.1 per ROADMAP.md "### 1.1" (use plan mode first; user approves): build
  `agent_tools/mmx.py` with `mmx catalog` (→ `agent_tools/catalog.json` + `agent_docs/NODES.md`,
  <600 lines) and `mmx validate <ptex>` (JSON `{"ok","errors"}`, exit 0/1). Test against all
  release examples + 3 broken copies. Lessons from 0.3 to fold in: include port shortdesc/longdesc
  (esp. which `blend` input is the top layer), and resolve subgraph nodes' `paramN` (e.g.
  `normal_map.param1` = amount) to real labels. Prototype helpers in `agent_tools/proto_0.3/`.
  Then update PROGRESS.md (next: 1.2).
