# Acceptance run (Session 6.3, 2026-10-07)

Seven materials made with the skill's tools only (`.claude/skills/material-maker/SKILL.md`): 5 from text and 2 from
reference photos. Each one had a cap of 8 iterations and was delivered into the Unity project `MM-Agent-Test`
(URP, Unity 6000.5.5f1) with `mmx to-unity ... --verify`.

**Tooling actually used.** The `mcp__material-maker__*` tools were not loaded in this session: Claude Code was started
outside the repo root, so `.mcp.json` was never read. The loop therefore ran on the skill's CLI path: per-iteration edit
scripts (`agent_runs/6.3/<run>/edit_NN.py`, using `proto_0.3/g.py`), then `mmx validate`, `mmx run` (export + 3D preview +
sheet), `mmx preview`/`compare`/`palette`, and `mmx to-unity`. MMClient was not needed. Every iteration has a ptex copy,
sheet, 3D preview and `critique.md` in `agent_runs/6.3/<run>/iter_NNN/` (gitignored).

**Times** are wall-clock from copying the start graph to the final `to-unity` (`t_start`/`t_end` in each run folder). They
include reading every sheet and writing every critique, but exclude the shared candidate-preview pass (13 examples, 34 s)
and the photo download. The two photo runs also include the time I spent waiting for your steering answer after
iteration 4. A single `mmx run` took a median of ~5 s for the export, plus ~2–3 s for the preview and sheet.

**Unity:** all 7 are in `Assets/Materials/Generated/<Name>/`, with URP/Lit, every texture resolved, and correct importer
settings (albedo sRGB, data maps linear, normal = NormalMap). `--verify` took 13–27 s per material. One run
(BarkPhotoMatch) first came back `ok: false` with an empty error. The verifier had logged `MMAgentVerify: OK`, but Unity
then crashed during shutdown (exit -10, "fatal error in the mono runtime"). An immediate rerun passed. See Findings.

| # | Material (Unity name) | Request type | Start graph | Iterations | Time | Verdict |
|---|---|---|---|---|---|---|
| 1 | GraniteCliff | text, natural, realistic | rock | 7 | 3.2 min | success |
| 2 | ChippedPaintMetal | text, man-made, realistic | rusted_metal | 6 | 2.1 min | success |
| 3 | StylizedLava | text, natural, stylized | lava | 5 | 1.9 min | success |
| 4 | SciFiFloorPanels | text, man-made, stylized | metal_pattern_3 | 4 | 1.7 min | success |
| 5 | CarraraMarbleTiles | text, man-made, realistic | marble | 6 (+9 rework) | 4.5 min (+27) | success after rework (2026-10-10) |
| 6 | BarkPhotoMatch | photo (ambientCG Bark012, CC0) | dry_earth | 7 | 5.1 min* | convincing match |
| 7 | PlanksPhotoMatch | photo (ambientCG Planks023A, CC0) | wooden_floor | 6 | 2.8 min* | convincing at a glance; layout off |

\* includes waiting for the user's steering answer. Total: 41 iterations (cap 56).

---

## 1. GraniteCliff: "realistic grey granite cliff face"
![GraniteCliff](acceptance/GraniteCliff.jpg)

Target traits: angular fractured facets, irregular dark fractures, fine grey salt-and-pepper granite, a few warm stains,
rough non-metal.
- **Path:** baseline (blobby tan rock, metallic driven by noise) → speckle albedo + metallic 0 → voronoi facets + cracks +
  AO/depth (read as crazy paving) → 3×3 facets with noise-faded cracks (cliff-like) → stronger normal (but the albedo
  regressed into camo blotches) → fine grain via lacunarity 4 → ochre stains + roughness 0.80–0.93.
- **Honest notes:** iteration 5 made the albedo worse (lower fbm persistence left only the coarse octave). The fix was the
  opposite of my first guess. The warped grit gives some streaky ripples in the relief. The facets are faceted voronoi
  cones, so up close it reads more "broken rock face" than real granite cleavage.

## 2. ChippedPaintMetal: "industrial teal-painted steel, chipped, with rust"
![ChippedPaintMetal](acceptance/ChippedPaintMetal.jpg)

- **Path:** baseline (shiny steel with red rust) → rebuild: one chip noise drives paint / scraped-steel rim / rust in every
  channel → rust grain (colour + recessed bumpy height) + grime (the `dirt` node gave lizard-skin speckles) → broad fbm
  grime driving paint roughness, plus directional-blur rust streaks (they ran **up**) → angle +90 → blur grid 256 for longer
  streaks.
- **Honest notes:** in `directional_blur2`, angle -90 points up in texture space and sigma is in grid pixels; each cost an
  iteration. The streaks lean grey-brown rather than orange. The chip edges are hard-stepped (constant-interpolation
  gradients). Fine at 2048, but aliased if downsized.

## 3. StylizedLava: "cartoon lava: dark crust plates, glowing cracks"
![StylizedLava](acceptance/StylizedLava.jpg)

- **Path:** baseline (realistic noisy lava, metallic from the crack mask) → rebuild on voronoi2: borders → glow, emission,
  bevel, roughness; fill → 3 flat crust tones → perlin-warped borders (organic cracks), emission 2 → 1.3 → crack width
  varied by noise (but cracks got thin overall) → bands 1.5× wider.
- **Honest notes:** the plates are domed or pyramidal rather than flat-topped with a rim, because the bevel rarely reaches
  its plateau on small cells. The glow core clips near-white in the preview. Emission is exported; how it blooms depends on
  the Unity scene's post-processing (not checked).

## 4. SciFiFloorPanels: "stylized sci-fi floor panels with glowing strips"
![SciFiFloorPanels](acceptance/SciFiFloorPanels.jpg)

- **Path:** baseline (light-blue riveted plate, uniform maps) → rebuild on `bricks_uneven4` (mixed panel sizes): per-panel
  tone, dark seams, light rim, cyan emissive inset strips on about 1/3 of panels → wider bevel so the strips aren't
  hairlines → dot-grip tread on another ~30% of panels.
- **Honest notes:** clean, with no wear or grime (fits "stylized"). Metallic is a flat 0.5. No bolts or greebles. The
  quickest run, because the pattern node already gave the layout.

## 5. CarraraMarbleTiles: "polished white Carrara marble floor tiles"
![CarraraMarbleTiles](acceptance/CarraraMarbleTiles.jpg)

- **Path:** baseline (black/white checker, gold metallic grout) → both Marble subgraphs → white/grey, Gold → matte grey
  non-metal grout → softer vein ramp (still curly blotches) → vein source inside the subgraphs replaced by fbm-warped sine
  stripes (flowing, but wide and frayed) → thinner, smoother → faint secondary veins.
- **Honest notes:** this is the weakest text result. It reads as white marble tiles with grey veins, but the veins are
  graphic (even width, flat grey, no translucent depth), the secondary veins look a little like contour lines, and the main
  veins came out slightly wider in the last iteration. It needed edits *inside* sub-graphs (`nodes`/`connections` of a
  `graph` node), which the g.py helper doesn't cover. The tiny white sparkles are the example's scratch normal, kept on
  purpose. Normal/height are flat apart from the grout (correct for polished stone).
- **Rework (2026-10-10, user request, 9 more iterations, ~27 min of which ~10 min were engine hangs):** veins rebuilt
  from ridged simplex noise (thin, continuous, varying width) with a blurred copy lightened over them as a soft grey
  haze, and a cooler blue-grey vein colour; the contour-like secondary veins are gone. The preview above is the new
  version; re-delivered under the same name (GUIDs kept), `--verify` OK. Details: `agent_runs/marble2/summary.md`.
  Still off: veins in each sub-graph run in a similar direction.

## 6. BarkPhotoMatch: photo reference, ambientCG Bark012
![BarkPhotoMatch](acceptance/BarkPhotoMatch.jpg) *(photo centre square | 3D preview)*

- **Path:** baseline dry_earth (big round cracks, red-brown) → voronoi 24×8 tall plates + metallic 0 → photo palette
  gradient → broken fissures + vertical streaks (blocky bars) → **asked you to steer: "surface texture first"** → fibrous
  stretched-simplex micro-detail in albedo + height → pale flakes + red-brown flecks (too many) → sparser, darker flecks.
- **Numbers:** albedo luma 0.478 ± 0.046 vs photo 0.477 ± 0.052; the palette strips are nearly identical.
- **Left on purpose / still off:** the photo's scales are deeper and sharper, with dark pockets (ours is shallower); the pale
  flakes are slightly camo-patchy; no greenish lichen tint; roughness is a constant 1.0.

## 7. PlanksPhotoMatch: photo reference, ambientCG Planks023A
![PlanksPhotoMatch](acceptance/PlanksPhotoMatch.jpg) *(photo centre square | 3D preview)*

- **Path:** baseline wooden_floor (orange, blobby, glossy) → 12 rows, offset 0.37 → photo palette on the grain + matte
  roughness (flat: std 0.01) → anisotropic grain + per-plank tone (too ridged) → **asked you to steer: "grain look
  first"** → seam-mask multiply instead of 55% flat colour, grain contrast → Material.normal 0.4, fainter seams.
- **Numbers:** albedo luma 0.310 ± 0.025 vs photo 0.318 ± 0.024.
- **Still off:** the seams follow a regular alternating stagger, because legacy `bricks` and `bricks3` only offset every
  other row, while the photo has random plank lengths. No knots. The grain is a little finer and more uniform than the
  photo's soft streaks. `normal_map.param1` (0.2 → 0.08) made no visible difference; `Material.normal` did.

---

## Findings for maintenance
- **Render hangs on the marble graph (2026-10-10):** through the MCP server, `render_preview` hung (180 s timeout,
  automatic restart) on the first render after loading the 6.3 marble and again after sub-graph edits; the hung
  engine stalls in `cli_preview.gd render_meshes`. While that `--serve` engine process was still alive, a CLI
  `mmx preview` of the same graph also hung (bricks rendered fine); after killing it, CLI renders of this graph worked
  (8–11 s, one transient `ok: false`). Likely buffer/GPU contention specific to this graph (fast_blur/normal_map buffers
  inside sub-graphs); not reproduced on simple graphs. The rework was finished with the CLI tools.
- **MCP not exercised in-chat (again).** Start Claude Code in the repo root to load `.mcp.json`. This is still the one
  untested path.
- **`to-unity --verify` false failure:** Unity can crash during batchmode shutdown *after* the verifier wrote an OK report
  (exit -10). The wrapper then reports `ok: false` with an empty "verification found problems:" message. Suggested
  follow-up: when the report is ok and has no errors but the exit code is non-zero, say "Unity exited with code N after an
  OK report" (and maybe retry once). Log excerpt: `agent_runs/6.3/bark/unity_crash_excerpt.txt`.
- **Skill gaps that cost iterations:** directional-blur angle sign and grid-relative sigma; editing nodes inside sub-graphs
  (no helper); random-length plank layouts (no generator found quickly); `fbm4` scale capped at 32, so fine grain needs
  lacunarity/persistence tricks.
- **What worked well:** starting from the example for the pipeline but rebuilding the core from one driving noise with
  per-channel colorize ramps (paint, lava, sci-fi); `mmx palette` gradients landing 1:1 in the albedo (both photo runs hit
  the luma within 0.01 on the first palette pass); the 3D preview caught problems the flat maps hid (too-strong grain
  relief, glow clipping, plastic-looking paint).
