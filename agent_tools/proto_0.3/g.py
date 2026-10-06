# tiny .ptex edit helpers
import json
def C(r, g, b, a=1.0): return {"type": "Color", "r": r, "g": g, "b": b, "a": a}
def G(*pts, interp=1):  # pts: (pos, r, g, b[, a])
    return {"type": "Gradient", "interpolation": interp,
            "points": [{"pos": p[0], "r": p[1], "g": p[2], "b": p[3], "a": p[4] if len(p) > 4 else 1} for p in pts]}
class Graph:
    def __init__(s, path): s.d = json.load(open(path))
    def n(s, name): return next(x for x in s.d["nodes"] if x["name"] == name)
    def set(s, name, **kw): s.n(name)["parameters"].update(kw)
    def add(s, name, type, x=0, y=0, **params):
        s.d["nodes"] = [x_ for x_ in s.d["nodes"] if x_["name"] != name]
        s.d["nodes"].append({"name": name, "type": type, "node_position": {"x": x, "y": y}, "parameters": params})
    def wire(s, frm, fp, to, tp):  # replaces whatever fed (to, tp)
        s.d["connections"] = [c for c in s.d["connections"] if not (c["to"] == to and c["to_port"] == tp)]
        s.d["connections"].append({"from": frm, "from_port": fp, "to": to, "to_port": tp})
    def save(s, path): json.dump(s.d, open(path, "w"), indent=1)
