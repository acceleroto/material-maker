# Four example graphs, annotated

Release examples from `material_maker/examples/`, read node by node so an agent can reuse their
tricks. Notation: `node.port`, ports 0-based; `G[pos:colour ...]` is a colorize gradient. Port
and parameter details: `agent_docs/NODES.md` or `python3 agent_tools/mmx.py node <type>`.

All four are flat graphs (no subgraphs except the predefined `normal_map`), use some legacy node
types (`voronoi`, `bricks`, `transform`, `normal_map`), and carry stale parameters that `mmx validate`
flags as `ignored_parameter` (e.g. `normal_map.amount`, `normal_map.size`, `Material.normal_scale`).
**Those stale names look meaningful but do nothing**: the normal strength is `normal_map.param1`.

Recurring idea in all of them: build one or two **grayscale masks/height fields** first, then derive
every channel from them with `colorize` (a gradient is a remap curve + palette in one node).

---

## 1. `dry_earth.ptex`: cracked mud (13 nodes)

Good base for: cracked ground, dried mud, crackle glaze, cell/plate patterns.

| node | type | role |
|---|---|---|
| `voronoi_0` | voronoi (legacy), scale 4×4, randomness 1 | out 1 **Borders**: distance to cell edges, the crack network |
| `colorize_1` | colorize `G[0:black 0.06:white]` | thresholds the borders into a thin black crack line on white |
| `perlin_1` | perlin 4×4, 3 octaves | low-frequency noise used as a warp field |
| `warp_0` | warp, amount 0.4 | bends the straight Voronoi edges into wobbly cracks (in 0 image, in 1 height field) |
| `perlin_0` | perlin 2×2, 10 octaves, persistence 0.9 | high-detail grit for the soil surface |
| `colorize_0` | colorize `G[0.25:tan 0.65:dark brown]` | soil palette from the grit |
| `blend_0` | blend Multiply, amount 0.4 | albedo = soil (bg, in 1) × crack mask (fg, in 0): cracks darken |
| `colorize_4` | colorize white→black (invert) | inverts the warped cracks: cracks become white |
| `blend_1` | blend Normal, amount 0.5 | depth = 50% grit (fg, in 0) over the inverted cracks (bg, in 1) |
| `colorize` | colorize white→black (invert) | flips depth into a height field (cracks dark = low) for the normal |
| `normal_map_0` | normal_map, param1 0.99 | normal from that height |
| `colorize_3` | colorize `G[0:black 1:0.52]` from perlin_1 | wired to **metallic** (0–0.5): an odd choice; set metallic to 0 for soil |
| `Material` | material, depth_scale 0.1 | albedo ← blend_0, metallic ← colorize_3, normal ← normal_map_0, depth (in 6) ← blend_1 |

Notes: the Material's in 6 is **depth** (white = deeper; the Unity export writes `_height.png` as
1 − depth). `blend_1` has white cracks, so the cracks are deep; the normal is built from the inverted
copy (cracks dark = low in a height field), so both agree. No roughness input → exported roughness is the
Material scalar (1.0). Crack width is set by the `colorize_1` threshold (0.06); crack count by
`voronoi_0.scale_x/y`; wobble by `warp_0.amount` and `perlin_1` scale.

---

## 2. `wooden_floor.ptex`: plank floor (11 nodes)

Good base for: planks, floorboards, decking, any staggered rectangle layout with per-board variation.

| node | type | role |
|---|---|---|
| `bricks_0` | bricks (legacy), 10 rows × 1 column, mortar 0.02, bevel 0 | out 0: board mask (white boards, thin black gaps); out 1: **random colour per board** |
| `decompose_0` | decompose | splits the random colour into R, G: two independent random values per board |
| `perlin_0` | perlin 4×20, 6 octaves | stretched noise = grain streaks |
| `transform_1` | transform (legacy), repeat true | shifts the grain per board: in 1 (x offset) ← random R, in 2 (y offset) ← random G, so neighbouring boards don't share grain |
| `colorize_0` | colorize `G[0:black 0.15:brown]` | board mask → brown boards, black gaps |
| `blend_0` | blend Normal, amount 0.555 | colour boards (fg) over the offset grain (bg): albedo |
| `normal_map_0` | normal_map, param1 0.2 | weak normal from the albedo luminance (gaps + grain) |
| `uniform_0` | uniform black | metallic = 0 |
| `combine_0` | combine | dangling (output unused); ignore |
| `Material` | material | albedo ← blend_0, metallic ← uniform_0, roughness ← blend_0 (albedo reused!), normal ← normal_map_0 |

Notes: the per-brick random colour → decompose → transform-offset trick is the key reusable idea.
Roughness = albedo luminance is a shortcut that makes dark wood shinier; give it its own map.
Plank count: `bricks_0.rows`; staggering: `row_offset`; gap width: `mortar`. No height output.

---

## 3. `wood.ptex`: wood grain with knots (12 nodes)

Good base for: close-up wood grain, rings, knots; combine with #2 for planks.

| node | type | role |
|---|---|---|
| `perlin_0` | perlin 32×4, 3 octaves | horizontally stretched noise: base grain lines |
| `perlin_1` | perlin 4×4 | low-frequency warp field |
| `warp_0` | warp, amount 0.1 | gently bends the grain (in 0 grain, in 1 perlin_1) |
| `voronoi_0` | voronoi (legacy), 5×4 | out 0 Nodes: distance to cell centres, used as knot spots |
| `colorize_1` | colorize `G[0:0.43 grey 0.35:black]` | keeps only small bright blobs around cell centres: knot field |
| `warp_1` | warp, amount 0.1 | warps the grain around the knots (in 1 ← knot field) |
| `perlin_2` | perlin 32×4, 6 octaves, persistence 1 | fine fibre noise |
| `blend_0` | blend Multiply, amount 1 | grain × fibres = the master grayscale |
| `colorize_2` | colorize, 5 stops alternating light/dark brown | the master → **ring bands** (repeating light/dark stops make rings) |
| `colorize_0` | colorize `G[0:0.53 1:0.71]` | master → roughness 0.53–0.71 |
| `normal_map_0` | normal_map, param1 0.99 | normal from the master |
| `Material` | material | albedo ← colorize_2, metallic ← blend_0 (!), roughness ← colorize_0, normal ← normal_map_0 |

Notes: multi-stop gradients turn a smooth field into bands (rings, strata). Metallic is wired to
the grain master by mistake-or-shortcut; set it to 0 for wood.

---

## 4. `metal_pattern_2.ptex`: tread/diamond plate (7 nodes)

Good base for: embossed metal patterns; also an example of a minimal "normal-only" material.

| node | type | role |
|---|---|---|
| `pattern_0` | pattern, X triangle ×40, Y triangle ×8, Multiply | grid of elongated pyramids |
| `colorize_0` | colorize `G[0.18:white 0.44:black]` | thresholds pyramids into lens-shaped bumps |
| `transform_2` | transform (legacy), rotate 90, repeat true | the same bumps rotated 90° |
| `pattern_1` | pattern, square × square ×4, Xor | checkerboard mask |
| `blend_0` | blend Normal, amount 1 | checker picks rotated (fg, mask 1) vs unrotated bumps (bg): alternating tread |
| `normal_map_0` | normal_map, param1 0.99 | normal from the bump height |
| `Material` | material, albedo_color (0.82,0.83,0.95), metallic 1, roughness 0.75 | only normal ← normal_map_0 |

Notes: only the normal input is wired, so the Unity/URP export contains **just** `_normal.png` plus
the `.mat`; colour/metal/roughness exist only as Material scalars. Wire `uniform` nodes into
albedo/metallic/roughness to get a full texture set. `pattern` + `colorize` threshold is the
cheapest way to make repeated studs, holes, rivets or slots (any `x_scale`/`y_scale` keeps tiling
as long as the repeat counts are integers).
