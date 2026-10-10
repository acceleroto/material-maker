"""Replace bricks_0 in the planks graph with a custom 'Random Planks' shader node:
per row a random offset and 1 or 2 planks (random split), so seams fall at random positions.
out 0 (f): seam pattern, 0 on a seam rising to 1 over `mortar` (uv units) - like the bricks pattern output
out 1 (rgb): random per plank (r, g = grain offset, b = tone) - like the bricks random-colour output.
Usage: make_layout.py src dst [json params]"""
import json, sys
src, dst = sys.argv[1], sys.argv[2]
params = {"rows": 12, "seed": 0.37, "two": 0.55, "split_min": 0.35, "split_max": 0.65, "mortar": 0.004}
if len(sys.argv) > 3: params.update(json.loads(sys.argv[3]))
GLOBAL = """vec4 rnd_planks_info(vec2 uv, float rows, float seed, float two, float smin, float smax) {
	float r = floor(uv.y*rows);
	float fy = fract(uv.y*rows);
	vec2 h = rand2(vec2(r+0.5, seed));
	vec2 h2 = rand2(vec2(seed, r+0.5)+vec2(3.7, 1.3));
	float x = fract(uv.x - h.x);
	float a = h2.x < two ? mix(smin, smax, h.y) : 1.0;
	float second = step(a, x);
	float start = second*a;
	float len = mix(a, 1.0-a, second);
	float lx = x - start;
	float d = min(min(lx, len-lx), min(fy, 1.0-fy)/rows);
	vec2 id = rand2(vec2(r*1.731+second*0.513+h.x, seed+0.29));
	return vec4(d, id.x, id.y, fract(id.x*7.13+id.y*3.31));
}
"""
model = {"code": "vec4 $(name_uv)_p = rnd_planks_info($uv, $rows, $seed, $two, $split_min, $split_max);\n",
    "global": GLOBAL, "inputs": [], "instance": "", "name": "Random Planks",
    "longdesc": "Rows of planks with a random offset and 1 or 2 planks of random length per row",
    "outputs": [{"f": "clamp($(name_uv)_p.x/$mortar, 0.0, 1.0)", "type": "f", "shortdesc": "Seam pattern"},
                {"rgb": "$(name_uv)_p.yzw", "type": "rgb", "shortdesc": "Random per plank"}],
    "parameters": [
        {"name": "rows", "label": "Rows", "type": "float", "default": 12, "min": 1, "max": 64, "step": 1, "control": "None"},
        {"name": "seed", "label": "Seed", "type": "float", "default": 0.37, "min": 0, "max": 1, "step": 0.001, "control": "None"},
        {"name": "two", "label": "2-plank rows", "type": "float", "default": 0.55, "min": 0, "max": 1, "step": 0.01, "control": "None"},
        {"name": "split_min", "label": "Split min", "type": "float", "default": 0.35, "min": 0.05, "max": 0.95, "step": 0.01, "control": "None"},
        {"name": "split_max", "label": "Split max", "type": "float", "default": 0.65, "min": 0.05, "max": 0.95, "step": 0.01, "control": "None"},
        {"name": "mortar", "label": "Seam width", "type": "float", "default": 0.004, "min": 0.0005, "max": 0.05, "step": 0.0005, "control": "None"}]}
d = json.load(open(src))
old = next(n for n in d["nodes"] if n["name"] in ("bricks_0", "planks_0"))
pos = old.get("node_position", {"x": 0, "y": 0})
d["nodes"] = [n for n in d["nodes"] if n["name"] not in ("bricks_0", "planks_0")]
d["nodes"].append({"name": "planks_0", "type": "shader", "node_position": pos, "parameters": params, "shader_model": model})
for c in d["connections"]:
    if c["from"] == "bricks_0": c["from"] = "planks_0"
json.dump(d, open(dst, "w"), indent=1)
