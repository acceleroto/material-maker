# usage: sheet.py <outdir>  -> <outdir>/../sheet.png  (maps + crude Lambert-lit preview)
import sys, glob, os
from PIL import Image, ImageDraw, ImageChops
import numpy as np
d = sys.argv[1]; S = 400
maps = {}
for p in sorted(glob.glob(os.path.join(d, "*.png"))):
    k = p.rsplit("_", 1)[-1][:-4]
    if p.endswith("metal_smoothness.png"): k = "metal_smoothness"
    maps[k] = Image.open(p).convert("RGB" if k != "metal_smoothness" else "RGBA")
tiles = []
if "albedo" in maps and "normal" in maps:
    a = np.asarray(maps["albedo"].resize((1024, 1024)), dtype=np.float32) / 255
    n = np.asarray(maps["normal"].resize((1024, 1024)), dtype=np.float32) / 255 * 2 - 1
    n[..., 1] *= -1  # Unity normal is OpenGL (+Y up); image y goes down
    L = np.array([-0.5, 0.6, 0.62]); L /= np.linalg.norm(L)
    lam = np.clip((n * L).sum(-1) / np.linalg.norm(n, axis=-1), 0, 1)
    ao = np.asarray(maps["occlusion"].convert("L").resize((1024, 1024)), dtype=np.float32)[..., None] / 255 if "occlusion" in maps else 1
    lit = np.clip(a * (0.25 + 0.85 * lam[..., None]) * (0.5 + 0.5 * ao), 0, 1)
    li = Image.fromarray((lit * 255).astype(np.uint8))
    tiles.append(("lit (1x)", li.resize((S, S))))
    t2 = Image.new("RGB", (2048, 2048)); [t2.paste(li.resize((1024,1024)), (x, y)) for x in (0, 1024) for y in (0, 1024)]
    tiles.append(("lit tiled 2x2", t2.resize((S, S))))
    tiles.append(("lit crop 1/4", li.crop((0, 0, 512, 512)).resize((S, S))))
for k in ("albedo", "normal", "height", "occlusion"):
    if k in maps: tiles.append((k, maps[k].resize((S, S))))
if "metal_smoothness" in maps:
    tiles.append(("smoothness (A)", maps["metal_smoothness"].split()[3].convert("RGB").resize((S, S))))
cols = 4; rows = (len(tiles) + cols - 1) // cols
sheet = Image.new("RGB", (cols * S, rows * (S + 20)), (30, 30, 30)); dr = ImageDraw.Draw(sheet)
for i, (lab, im) in enumerate(tiles):
    x, y = (i % cols) * S, (i // cols) * (S + 20)
    sheet.paste(im, (x, y + 20)); dr.text((x + 4, y + 4), lab, fill=(255, 255, 255))
out = os.path.join(os.path.dirname(os.path.abspath(d)), "sheet.png"); sheet.save(out); print(out)
