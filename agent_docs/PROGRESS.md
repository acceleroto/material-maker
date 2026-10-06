# Progress

**Current session:** 1.3 (complete)

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
- 1.1 (agent, 2026-10-05): `agent_tools/mmx.py` (stdlib only) with `catalog` (→ `agent_tools/catalog.json`,
  411 types incl. built-ins, port-type table; `agent_docs/NODES.md`, 442 lines, ~65 curated types + .ptex
  primer incl. blend foreground/background/mask semantics), `validate <ptex>` (JSON ok/errors/warnings,
  exit 0/1; codes table in `agent_tools/README.md`), `node <type>`. Subgraph `paramN` resolve to real labels
  (`normal_map.param1` = Strength). Tests `python3 -m unittest agent_tools/test_mmx.py -v`: all 43
  `material_maker/examples/*.ptex` pass; broken copies (bad type / bad port / bad params) fail correctly.
  Findings: old examples carry stale params MM ignores (→ `ignored_parameter` warning via `STALE_PARAMS`);
  `.mmg` files can set a default `generic_size` (mwf_mix = 2); out-of-slider values are common (warning).
  **Phase-0 mystery solved:** `Bricks.repeat/rows/columns` in `bricks.ptex` are driven by the subgraph's
  `gen_parameters.param0` config_control (Pattern), which overwrites them on load; `validate` now warns
  `overridden_parameter` for this.

- 1.2 (agent, 2026-10-05): `mmx export/sheet/run/wait` + `agent_tools/mmx.toml` (mode/target/timeout/binary;
  `source` mode stubbed for Phase 2). `export` validates first, predicts the expected files from the Material
  node's export template (`$(connected:x_tex)` conditions), deletes old outputs (MM silently skips existing
  `.mat`/`.meta` in CLI mode), runs with timeout + `export.log`, writes/prints `mmx_result.json`. `sheet`:
  lit + lit-tiled previews, split packed maps (Unity metal_smoothness, Godot orm), min/mean/max labels.
  `run` → `agent_runs/<run>/iter_NNN/` (ptex copy, out/, sheet.png, note.md). `wait` polls results for the
  Terminal-panel fallback. Pillow lives in gitignored `agent_tools/.venv` (mmx re-execs into it).
  Tests: 19 pass (`agent_tools/.venv/bin/python -m unittest agent_tools/test_mmx.py`), export paths tested
  with a fake MM binary (ok / missing file / hang→timeout / validation refusal).
  **Finding: the Phase-0 Bash-tool hang no longer reproduces** (6/6 exports from Bash, ~5 s, incl. a plain
  direct launch). CLAUDE.md now says: use `mmx run` from Bash; on `error: timeout`, fall back to
  `run_in_terminal` + `mmx wait`. Real runs: `agent_runs/s1.2/iter_001` (bricks, via Terminal panel),
  `iter_002` (improved_brick, via Bash).

- 1.3 (agent, 2026-10-05): `.claude/skills/material-maker/SKILL.md` (when to use, 8-iteration loop: closest example →
  validate → `mmx run` → read sheet → `critique.md` → 1–2 edits; reading the sheet; pitfalls; debug-export technique) and
  root `AGENTS.md` (project rules + a verbatim copy of the skill body; keep in sync). `agent_docs/examples_annotated.md`
  (dry_earth, wooden_floor, wood, metal_pattern_2). End-to-end test in `agent_runs/1.3/{desert,steel,oak}/` (6 iterations
  each): desert **success**, steel **success**, oak **partial**; export ~3.8 s, ~18 s median wall per iteration.
  Report: `agent_docs/phase1_report.md` (recommends Phase 4 > 3 > 2 > 5).
  **Fixes:** `mmx sheet` lit preview lit from the bottom-left (y-sign bug; older sheets show bumps as dents) → top-left
  + test; `mmx run --run-name` may nest (`1.3/desert`) + test (21 tests pass). **Findings:** Material in 6 is *depth*
  (Unity `_height.png` = 1 − depth); `tiler.scale_x/y` are fractions of the whole texture; unconnected inputs read as 0
  and `validate` doesn't flag them (cheap follow-up: warn on used nodes with unconnected inputs).

## In progress
- None.

## Blockers
- None. Exports run fine from the Bash tool (Terminal-panel fallback via `mmx wait` if `mmx` reports a timeout).

## Next step
- **Checkpoint 1 (👤 user, ~15 min)** per ROADMAP.md "### Checkpoint 1": look at the final sheets
  `agent_runs/1.3/{desert,steel,oak}/iter_006/sheet.png` (+ each `summary.md`), read `agent_docs/phase1_report.md`,
  and try the skill in a fresh Claude Code session ("make me a <material>"). Then decide: stop here, or continue to
  Setup B + Session 2.1 (Phase 2). Optional small agent task before 2.1: `mmx validate` warning for nodes whose output
  is used but which have unconnected inputs.
