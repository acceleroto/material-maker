# Phase 4 report (Session 4.3: the Phase 1.3 requests again, judged from the 3D preview)

Date: 2026-10-06. Agent: Claude Code (Opus 5.5), following `.claude/skills/material-maker/SKILL.md` (now with the
3D preview as the main image, `node-preview` for debugging and engine `validate`), running Material Maker from
source, Unity/URP target. Runs: `agent_runs/4.3/{desert,steel,oak}/` (gitignored). Each has `iter_NNN/` (ptex,
`out/`, `preview_3d.png`, `sheet.png`, `critique.md`), the `edit_NN.py` scripts, and `summary.md`.
Side by side: `agent_runs/4.3/compare/phase1_vs_phase4.png`. It shows Phase 1's final graphs rendered **now** with
the same 3D preview (same camera, Studio environment) next to the Phase 4 finals.

**Caveats.** (1) The agent had read `phase1_report.md` and the 1.3 summaries before starting, so it already knew
some pitfalls (anisotropic grain, the risk of overshooting with Voronoi/crack thresholds). That favours Phase 4,
mostly on desert and oak. (2) The cap went from 6 to 8 (the skill's current cap). Phase 1 used all 6 on every
request, and Phase 4 stopped by itself each time. (3) Same starting examples except steel (see below).

## Results

| request | Phase 1 (1.3) | Phase 4 (4.3) | quality, both finals under the same 3D preview |
|---|---|---|---|
| dry cracked desert ground | 6/6, success | **5/8, success** (`iter_005`) | about equal. Phase 4 adds per-plate tone and crisper cracks; Phase 1 has more, smaller plates. Neither has curled plate edges. |
| brushed steel panel with rivets | 6/6 + 2 debug exports, success | **4/8, success** (`iter_004`), no debug renders | **Phase 4 clearly better.** Phase 1's final, seen in 3D for the first time, is a noisy, rippled chrome with a watery normal. It was judged a success from flat maps only. Phase 4 reads as brushed steel: streaks in the highlight, domed rivets. |
| old oak planks, stylized | 6/6, partial | **7/8, success** (`iter_007`) | Phase 4 has every requested trait (stylized stepped grain, bevelled boards, worn edges, scratches along the grain, knots, height map). Phase 1's is calmer and more realistic but lacks the "old" and relief. Phase 4 is somewhat busy, especially on the sphere. Better match to the request, not prettier in every way. |
| **total** | **18 iterations, 1 partial** | **16 iterations, 0 partial** | |

Iteration count fell for desert (6→5) and steel (6→4). Oak used one more (6→7), but on traits Phase 1 never reached
(relief, wear, knots), so it went further rather than slower.

## What the 3D preview changed

1. **It caught errors that flat maps hide.**
   - Steel iter_002: the rivets looked like pits in the sphere's highlight. The example maps rivet peaks to black,
     so they were holes. One gradient-point flip fixed it, checked with a zoomed crop. In Phase 1 this kind of
     sign question cost a whole debug export (and the Lambert sheet had its own sign bug).
   - Oak iter_001: roughness = albedo showed up as glossy specks right away.
   - Desert iter_001: the warp-folded loops were obvious on the plane.
2. **It made the Phase 1 steel verdict look wrong in hindsight.** Rendered now, Phase 1's final steel is not
   what its flat sheet suggested. The specular look Phase 1 said it "can't judge" was in fact bad. That is the
   strongest evidence the previews matter.
3. **It made judging gloss and metal possible at all.** The steel roughness range (0.28–0.45 → 0.30–0.40) was
   tuned by looking at the streaks in the highlight, not by reading numbers.
4. **Choosing a start by looking.** `mmx preview` on three `metal_pattern*` examples (~2 s each, `candidates.png`)
   showed `metal_pattern_3` is already a riveted panel. Phase 1 picked `metal_pattern_2` blind and rebuilt almost
   everything. That alone saved steel ~2 iterations. (Now in the skill, step 2.)
5. **`node-preview` replaced debug exports.** Oak iter_005: two renders (`wear_m`, `scr`, ~2 s each) showed the
   wear band was a hairline and the scratches' `randomness` spreads their angle in every direction. Phase 1 needed
   two hand-wired debug exports for the same kind of question. (Pitfall added to the skill.)

What it did **not** fix: calibrating values still costs iterations. Desert iter_004 overshot a crack threshold
(wide mortar-like channels) and was reverted in iter_005, the same failure as Phase 1's desert iter_004. A
side-by-side parameter sweep would help here (Phase 5 server makes it cheap).

## Time

| | Phase 1 | Phase 4 |
|---|---|---|
| per `mmx run` | 3.8 s export + ~1 s sheet | 5–9 s (export 2.1–5.3 s + preview ~2 s + sheet) |
| wall per iteration (edit + run + read + critique) | ~26 s mean, ~18 s median | ~25 s (desert ~25 s, steel ~24 s incl. picking the start, oak ~24 s) |
| whole request, wall | ~2.5–3.5 min each | desert ~2.1 min, steel ~1.6 min (+0.3 min candidates), oak ~2.8 min |

The preview adds ~2 s per iteration, small next to the agent's reading and editing time. Fewer iterations more
than make up for it. Running from source worked from the Bash tool every time (no timeouts, no Terminal fallback).

## Remaining weaknesses

- Fine-detail judging at sheet resolution: rivets and scratches are a few pixels wide in the 512 px views. The
  agent zoomed by cropping `preview_3d.png` with Pillow. A `--zoom`/closer camera option or a crop helper in mmx
  would make that one command.
- The sphere wraps the texture 4×2, so busy patterns (oak grain) look busier there than on a real floor. The plane
  is the better view for floors and walls.
- `validate` warns `parameter_out_of_range` for legitimate values (voronoi `stretch_x` 1.8 works fine).
- Leftovers from 4.1/4.2: none blocking. Skipped the optional `--texture-size` for faster previews of 4096 graphs:
  every graph here was ≤2048 and previews took ~2 s.

## Verdict for Checkpoint 4

The previews made a clear difference where Phase 1 was weakest: metals/gloss (steel went from a hidden failure to
a convincing result in 4 iterations) and diagnosing "why does this look wrong" (no more debug exports). For matte
materials (desert) the gain is mostly speed and confidence, not a better result. Recommendation: the core loop is
in good shape. Phase 5 (persistent server) is worth doing mainly to make parameter sweeps and multiple per-node
renders per iteration cheap, since calibration is now the main cost.
