# Phase 1 report (Session 1.3 end-to-end test)

Date: 2026-10-05. Agent: Claude Code (Opus 5.5), following only `.claude/skills/material-maker/SKILL.md`
and `agent_tools/mmx.py` (release Material Maker binary, Unity/URP target, 2048² maps).
Runs: `agent_runs/1.3/{desert,steel,oak}/` (gitignored). Each has `iter_001..006/` (ptex copy, `out/`, `sheet.png`,
`critique.md`, `note.md`), the `edit_NN.py` scripts that made each change, and `summary.md`. Iteration 001 is always
the unmodified starting example. Cap was 6 iterations; all three used all 6.

## Results per request

| request | start from | final | verdict | what's still off |
|---|---|---|---|---|
| dry cracked desert ground | `dry_earth.ptex` | `desert/iter_006` | **Success** | plates are flat (no curled edges), little per-plate colour variation, no dust in cracks |
| brushed steel panel with rivets | `metal_pattern_2.ptex` (only its Material/normal skeleton survived) | `steel/iter_006` | **Success** | pristine: no wear/dirt, perfectly regular rivets; specular look can't be judged on the sheet |
| old oak planks, stylized | `wooden_floor.ptex` | `oak/iter_006` | **Partial success** | no knots or oak figure, scratches a bit busy, no height/AO maps |

All three finals tile seamlessly, have metallic/roughness values that make sense for the material, and export a
Unity/URP set (albedo, metal_smoothness, normal; desert and steel also height).
Desert and oak improved steadily. Steel took three iterations to get the rivets right (see problems 1 and 2).

## Time per iteration

| | export + sheet (mmx) | wall clock per iteration (steady state) |
|---|---|---|
| desert | 5.7 s avg export (4.7–7.5) | ~17 s |
| steel | 2.4 s avg export (1.6–3.5) | ~44 s (includes two debug exports) |
| oak | 3.3 s avg export (2.3–4.4) | ~17 s |
| **all 18 iterations** | **3.8 s export, ~1 s sheet** | **~26 s mean, ~18 s median** |

Wall clock = time between consecutive `mmx run` starts (edit + validate + export + sheet + reading the sheet +
writing the critique). It leaves out each run's first iteration, which also covered setup. The 15 edited
iterations across all three requests took about 7 minutes of wall time in total (23:49–23:56). Launching from the Bash tool worked every time (18 runs plus
debug exports, no hangs, no Terminal-panel fallback needed). **Export speed is not the bottleneck.**

## Top 3 problems

1. **Graph mistakes that fail silently.** Validation is structural only, so a wrong but valid graph renders
   black or flat without any error. Steel iteration 2 had two unwired inputs: a `tiler` with no input renders
   nothing, and an unwired `colorize` renders its gradient across U. Iterations 3–4 then got the tiler's
   `scale_x/y` wrong: the scale is a fraction of the *whole texture*, not of one cell, which only reading
   `tiler.mmg`'s GLSL revealed. Stale names like `normal_map.amount` look real but do nothing. Each of these
   took a **debug export** to find: wire the suspect node into albedo, export and look. That is a hand-made
   per-node preview. *Fixes:* a validator warning for "node used but has unconnected inputs" (cheap, Phase 1
   follow-up); engine-backed describe/validate (Phase 3); real single-node render (Phase 4.1).
2. **Judging from a crude 2D preview.** The sheet's Lambert "lit" view was the only way to judge relief.
   It had a **sign bug that lit everything from the bottom-left**, so the first steel rivets looked like
   dents. It's fixed now (`mmx.py lit_preview`, with a test), and every 1.3 sheet was re-rendered, but
   Phase 0/1.2 sheets were misleading. Even fixed, the preview shows no specular, anisotropy or parallax. For
   brushed steel, the property that matters most (the anisotropic sheen) can't be judged at all, and roughness
   and metal are judged as numbers. *Fix:* lit 3D preview on sphere + plane (Phase 4.2).
3. **Calibrating parameters costs iterations.** Many parameter scales are only learned by trying them. The
   Voronoi border distance grows with cell size, so changing `voronoi.scale` together with the crack threshold
   overshot (desert iteration 4). Gradient thresholds, `scratches2` length/angle, and `bricks` bevel width
   each took one try to calibrate. About 1 in 6 iterations went on finding a number's scale. *Mitigation now:*
   the skill says to change scale *or* width per iteration, not both. *Later:* render a few parameter values
   side by side in one call (fits Phase 4.1/5).

Smaller: the examples carry odd choices that have to be undone first (`dry_earth` wires noise into metallic,
`wooden_floor` reuses albedo as roughness, `metal_pattern_2` exports only a normal map). The Material's `depth`
input is depth (white = deep) and the Unity `_height.png` is `1 − depth`. That is easy to get backwards, so it's
now written down in the skill and in `examples_annotated.md`.

## Which of Phases 2–5 matter most

1. **Phase 4 (preview rendering): most important.** 4.1 (render any node) directly fixes problem 1: the
   debug-export workaround becomes one command. 4.2 (lit 3D preview) fixes problem 2, and it's the only way to
   judge metals, gloss and parallax. Every request in this test would have converged faster with both.
2. **Phase 3 (ask the engine): second.** Engine-backed `describe-node` and `validate`, especially shader-compile
   checks and the real port and parameter semantics of dynamic and subgraph nodes, address the rest of problem 1.
   Add the unconnected-input warning there or earlier.
3. **Phase 2 (fix the CLI): do it, but only as the base for 3 and 4.** The release binary was reliable here:
   exit codes are faked by mmx's file checks, and `--size` hasn't mattered yet. Its value is moving to running
   from source, which Phases 3 and 4 need.
4. **Phase 5 (persistent server/MCP): least important for now.** Exports take ~4 s against ~20 s or more of
   agent time per iteration, so cutting launch time saves little. Come back to it once Phase 4 previews exist,
   if many renders per iteration (parameter sweeps, per-node previews) make launch overhead add up.

## Tooling changes made during this session
- `mmx run --run-name` accepts nested names (`1.3/desert`); `..`, absolute and empty parts are rejected (test added).
- `mmx sheet` lit preview: light direction fixed to the top-left (test added). All `agent_runs/1.3` sheets
  were re-rendered.
- Skill and `AGENTS.md`: debug-export technique, unconnected-input and tiler/Voronoi scale pitfalls,
  depth vs height, stale parameter names.
