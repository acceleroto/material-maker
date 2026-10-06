# Progress

**Current session:** 0.2 (complete)

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

## In progress
- None.

## Blockers
- None hard. Open question: why `Bricks.repeat`/`rows`/`columns` edits are ignored on export
  (check in GUI when convenient). Exports must run via `run_in_terminal`.

## Next step
- Session 0.3 per ROADMAP.md "### 0.3": read CLAUDE.md, PROGRESS.md and
  `agent_docs/phase0_notes.md`; goal "weathered red roof tiles, slightly mossy, stylized";
  start from the closest release example, max 5 iterations in `agent_runs/0.3/iter_N/` with a
  `critique.md` each; export via the Terminal panel with absolute paths; append findings to
  phase0_notes.md; commit; next = 0.4 (human decision).
