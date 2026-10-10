# Example graphs (`material_maker/examples/`)

Start a new material from the closest of these (copy it to `agent_runs/<run>/` first; never edit the originals).
Compare candidates in one image: `python3 agent_tools/mmx.py preview material_maker/examples/{a,b,c}.ptex`
(→ `agent_runs/preview/contact.png`, labelled). All 43 rendered: `mmx preview material_maker/examples/*.ptex --size 192 --cols 6` (~2 min).

Columns: **maps** = Material inputs that are wired (only these export as texture maps; the rest come from the
Material node's scalar values). **metal** = the Material's fixed metallic value when no metallic map is wired:
a non-metal started from an example with metal 1 looks like shiny plastic/metal until you set it to 0 or wire a
map. **stale** = `ignored_parameter` warnings (leftover parameter names MM ignores; harmless noise, see
`mmx validate --hide ignored_parameter`).

| example | what it is | maps | metal | stale |
|---|---|---|---|---|
| `3d_shapes` | abstract black/white grid of raised 3D bumps (shape demo) | albedo,normal,ao,depth | **1** |  |
| `beehive` | golden honeycomb hexagon cells | albedo,metal,rough,normal,depth |  |  |
| `biohazard` | red biohazard symbols on black (decal pattern) | albedo,metal,rough,normal |  | 9 |
| `brick_rotated` | rotated bricks relief only: no albedo wired (renders white), normal + depth | normal,depth | **1** |  |
| `bricks` | red bricks in a basket-weave layout, grey mortar (bricks sub-graph with a Pattern control) | albedo,metal,rough,normal,ao,depth |  |  |
| `clump_of_grass` | green surface with grass clumps, stylized | albedo,normal | 0 | 7 |
| `crocodile_skin` | green scaly reptile skin | albedo,metal,rough,normal |  | 7 |
| `doc_tools` | colourful test pattern for the docs (has GLSL errors): not a material | albedo | **1** |  |
| `dry_earth` | brown cracked dry earth / mud plates | albedo,metal,normal,depth |  | 8 |
| `emmental` | pale yellow cheese with holes | albedo,normal,depth | **0.3** |  |
| `floor1` | brown stone floor tiles with red diamond insets | albedo,metal,rough,normal,depth |  | 7 |
| `floor2` | white tiles in a mixed-size layout, dark grout | albedo,metal,rough,normal |  | 7 |
| `grass_with_flowers` | stylized grass with small flowers | albedo,rough,normal | 0 | 7 |
| `halloween` | glossy orange pumpkin skin with ribs | albedo,emission,normal,depth | **1** | 6 |
| `improved_brick` | realistic dark red brick wall, running bond | albedo,normal,ao,depth | 0 | 12 |
| `lava` | realistic lava: dark crust, glowing cracks (emission) | albedo,metal,rough,emission,normal,ao,depth |  | 8 |
| `load_effect` | grey noise effect demo: not a material | - |  | 1 |
| `mandala` | grey carved-stone mandala relief | albedo,normal,depth | **0.25** | 3 |
| `mandelbrot` | Mandelbrot fractal colours (math demo) | emission | **1** | 4 |
| `marble` | black/white checkerboard marble floor tiles, gold metallic grout (workflow/mwf graph with sub-graphs) | albedo,metal,rough,emission,normal,ao,depth |  |  |
| `materials` | white with black speckle (material-workflow demo) | albedo,metal,rough,emission,normal,ao,depth |  |  |
| `medieval_wall` | layered medieval facade: stone wall, arches, blue windows | albedo,metal,rough,emission,normal,ao,depth |  |  |
| `metal_pattern` | grungy rusty steel with a pattern | albedo,rough,normal | **1** |  |
| `metal_pattern_2` | engraved metal pattern, light blue-white (normal map only) | normal | **1** | 7 |
| `metal_pattern_3` | light blue riveted metal panel | albedo,metal,rough,normal |  | 7 |
| `mmm_donuts` | donuts with sprinkles (fun pattern) | albedo,metal,rough,emission,normal,ao,depth |  |  |
| `mosaic` | random multicolour pixel mosaic | albedo,metal,rough,normal |  | 7 |
| `paper` | white paper with light blue ruled pattern | albedo | **1** | 4 |
| `pentagram` | red pentagram circles on black (decal pattern) | emission | **1** | 3 |
| `pile_of_bricks` | orange chunky scattered brick pile, stylized | albedo,normal,ao,depth | **1** |  |
| `planet` | planet terrain map: water, land, snow | albedo,rough,normal,depth | **0.05** |  |
| `radiation` | yellow/black radiation symbols (decal pattern) | albedo | **1** | 4 |
| `raymarching` | blue raymarched shapes (demo) | albedo,metal,normal |  | 21 |
| `rock` | tan-grey blobby rock surface | albedo,metal,rough,normal |  | 8 |
| `rusted_metal` | shiny steel with red-orange rust patches | albedo,metal,rough |  |  |
| `skulls` | beige pile of skulls / bones pattern | albedo,metal,rough,normal,ao,depth |  |  |
| `splatter` | pink flowers splattered on dark green | albedo,normal,depth | **1** | 4 |
| `stone_wall` | grey irregular stone-block wall, realistic (good wall start) | albedo,metal,rough,normal,ao,depth |  |  |
| `stylized_wall` | stylized small red brick wall (uses a buffer) | albedo,normal,ao,depth | 0 | 1 |
| `tiles` | orange fish-scale (beaver-tail) ROOF TILES; defaults are odd: metallic 1, no roughness or depth | albedo,normal | **1** | 6 |
| `wood` | brown wood with flowing grain | albedo,metal,rough,normal |  | 3 |
| `wood_with_blood` | orange wood planks with red stains | albedo,metal,rough,normal |  | 9 |
| `wooden_floor` | light wood plank floor (feeds albedo into roughness) | albedo,metal,rough,normal |  | 9 |

Good starting points by kind: walls `stone_wall`, `improved_brick`, `stylized_wall`, `medieval_wall`; floors
`floor1`, `floor2`, `wooden_floor`, `marble`; roofs `tiles`; ground `dry_earth`, `rock`, `grass_with_flowers`;
metal `metal_pattern_3` (panels), `rusted_metal`, `metal_pattern`; wood `wood`, `wooden_floor`; organic
`crocodile_skin`, `beehive`; glowing `lava`. Descriptions come from the 3D previews (2026-10-10).
