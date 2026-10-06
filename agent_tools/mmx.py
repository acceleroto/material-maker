#!/usr/bin/env python3
"""mmx: Material Maker tools for AI agents (stdlib only).

Subcommands:
  catalog   Parse node definitions (.mmg) and the node library into agent_tools/catalog.json
            and write the condensed reference agent_docs/NODES.md.
  validate  Structurally check a .ptex file; prints {"ok", "errors", "warnings"} JSON,
            exit code 0 (ok) or 1 (errors).
  node      Print one catalog entry as JSON.

Node type resolution mirrors MMLoader.create_gen (addons/material_maker/engine/loader.gd).
See agent_tools/README.md for limitations.
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NODES_DIR = REPO / "addons" / "material_maker" / "nodes"
LIBRARY_DIR = REPO / "material_maker" / "library"
CATALOG_PATH = REPO / "agent_tools" / "catalog.json"
NODES_MD_PATH = REPO / "agent_docs" / "NODES.md"
NODES_MD_MAX_LINES = 600

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def strip_trailing_commas(text):
    """Remove commas directly before ] or } (outside strings); Godot's parser accepts them."""
    out = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "]}":
                i += 1
                continue
            out.append(c)
        else:
            out.append(c)
        i += 1
    return "".join(out)


def load_json_lenient(path):
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(strip_trailing_commas(text))


# ---------------------------------------------------------------------------
# Definition normalisation
# ---------------------------------------------------------------------------

PARAM_KEYS = ("min", "max", "step", "first", "last")


def strip_label(label):
    """Parameter labels like "2:Amount" place the widget next to input 2; drop the prefix."""
    if not isinstance(label, str):
        return ""
    return re.sub(r"^\d+:", "", label).strip()


def norm_param(p):
    q = {"name": p.get("name", ""),
         "label": strip_label(p.get("label", "")) or p.get("shortdesc") or p.get("name", ""),
         "type": p.get("type", "unknown")}
    if "default" in p:
        q["default"] = p["default"]
    for k in PARAM_KEYS:
        if k in p:
            q[k] = p[k]
    if q["type"] == "enum":
        q["values"] = [v.get("name", v.get("value")) if isinstance(v, dict) else v
                       for v in p.get("values", [])]
    for k in ("shortdesc", "longdesc", "widget_type"):
        if p.get(k):
            q[k] = p[k]
    return q


def norm_input(p, i):
    q = {"index": i, "name": p.get("name", ""), "type": p.get("type", "unknown")}
    for k in ("label", "shortdesc", "longdesc"):
        if p.get(k):
            q[k] = p[k]
    if p.get("group_size"):
        q["group_size"] = p["group_size"]
    return q


def norm_output(p, i):
    q = {"index": i, "type": p.get("type", "unknown")}
    for k in ("name", "shortdesc", "longdesc"):
        if p.get(k):
            q[k] = p[k]
    if p.get("group_size"):
        q["group_size"] = p["group_size"]
    return q


def generic_range(items, key_fn):
    """Return (first, last) of the contiguous run of templated ('#') items, as gen_shader.gd does."""
    first = last = -1
    for i, it in enumerate(items):
        if "#" in key_fn(it):
            if first == -1:
                first = i
            elif last != -1:
                return -1, -1
        elif first != -1 and last == -1:
            last = i
    if first != -1 and last == -1:
        last = len(items)
    return first, last


def expand_generic(items, key_fn, rename_fn, size):
    first, last = generic_range(items, key_fn)
    if first == -1:
        return list(items)
    rv = list(items[:first])
    for gi in range(size):
        gv = str(gi + 1)
        for it in items[first:last]:
            rv.append(rename_fn(it, gv))
    rv.extend(items[last:])
    return rv


def _rename(field):
    def fn(it, gv):
        it = dict(it)
        for k in (field, "label", "shortdesc", "longdesc"):
            if isinstance(it.get(k), str):
                it[k] = it[k].replace("#", gv)
        return it
    return fn


def shader_model_defs(sm, generic_size=1):
    """Raw shader_model -> normalised (params, inputs, outputs), expanding generic '#' items."""
    params = sm.get("parameters", []) or []
    inputs = sm.get("inputs", []) or []
    outputs = sm.get("outputs", []) or []
    params = expand_generic(params, lambda p: p.get("name", ""), _rename("name"), generic_size)
    inputs = expand_generic(inputs, lambda p: p.get("name", ""), _rename("name"), generic_size)

    def out_key(o):
        t = o.get("type", "")
        v = o.get(t, "")
        return v if isinstance(v, str) else ""

    def out_rename(o, gv):
        o = dict(o)
        t = o.get("type", "")
        if isinstance(o.get(t), str):
            o[t] = o[t].replace("#", gv)
        for k in ("shortdesc", "longdesc"):
            if isinstance(o.get(k), str):
                o[k] = o[k].replace("#", gv)
        return o

    outputs = expand_generic(outputs, out_key, out_rename, generic_size)
    return ([norm_param(p) for p in params],
            [norm_input(p, i) for i, p in enumerate(inputs)],
            [norm_output(p, i) for i, p in enumerate(outputs)])


def is_generic_model(sm):
    return any(generic_range(sm.get(k, []) or [], lambda p: p.get("name", ""))[0] != -1
               for k in ("parameters", "inputs"))


# ---------------------------------------------------------------------------
# Built-in generator types (engine/nodes/gen_*.gd) whose ports aren't in .mmg files
# ---------------------------------------------------------------------------

SIZE_PARAM = {"name": "size", "label": "Size", "type": "size", "first": 4, "last": 13, "default": 4}


def _num(v, default):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def builtin_buffer(node):
    version = node.get("version", 0)
    params = [dict(SIZE_PARAM)]
    if version == 0:
        params.append({"name": "lod", "label": "Lod", "type": "float", "min": 0, "max": 10.0, "step": 0.01, "default": 0})
    elif version == 2:
        params += [{"name": "filter", "label": "Filter", "type": "boolean", "default": True},
                   {"name": "mipmap", "label": "Mipmap", "type": "boolean", "default": True},
                   {"name": "f32", "label": "32 bits", "type": "boolean", "default": False}]
    outputs = [{"type": "rgba"}, {"type": "rgba"}] if version == 0 else [{"type": "rgba"}]
    return params, [{"name": "in", "type": "rgba"}], outputs


def builtin_switch(node):
    p = node.get("parameters", {}) or {}
    outs = _num(p.get("outputs", 2), 2)
    choices = _num(p.get("choices", 2), 2)
    params = [{"name": "outputs", "label": "Outputs", "type": "float", "min": 1, "max": 5, "step": 1, "default": 2},
              {"name": "choices", "label": "Choices", "type": "float", "min": 2, "max": 5, "step": 1, "default": 2},
              {"name": "source", "label": "Source", "type": "float", "min": 0, "max": choices - 1, "step": 1, "default": 0}]
    inputs = [{"name": chr(65 + o) + str(c + 1), "type": "any"} for c in range(choices) for o in range(outs)]
    outputs = [{"name": chr(65 + o), "type": "any"} for o in range(outs)]
    return params, inputs, outputs


def builtin_ios(node):
    ports = [{"name": p.get("name", ""), "type": p.get("type", "rgba"), "shortdesc": p.get("shortdesc", ""),
              "longdesc": p.get("longdesc", ""), "group_size": p.get("group_size", 0)}
             for p in node.get("ports", []) or []]
    name = node.get("name")
    return [], ([] if name == "gen_inputs" else ports), ([] if name == "gen_outputs" else ports)


def builtin_reroute(node):
    t = node.get("port_type", "rgba")
    return ([{"name": "preview", "label": "Preview", "type": "enum", "values": ["none", "small", "large", "huge"], "default": 0}],
            [{"name": "in", "type": t}], [{"type": t}])


def builtin_portal(node):
    t = node.get("port_type", "rgba")
    is_in = node.get("io", 0) == 0
    return ([{"name": "link", "label": "Link", "type": "string", "default": "aperture_1"}],
            [{"name": "in", "type": t}] if is_in else [], [] if is_in else [{"type": t}])


def _static(params, inputs, outputs):
    return lambda node: (params, inputs, outputs)


BUILTINS = {
    # type: (function(node) -> (params, inputs, outputs), description, dynamic)
    "buffer": (builtin_buffer, "Renders its input to a texture (cache/LOD). Old files (no 'version') have 2 outputs.", True),
    "image": (_static([{"name": "image", "label": "Image", "type": "image_path", "default": ""},
                       {"name": "fix_ar", "label": "Fix Aspect Ratio", "type": "boolean", "default": False},
                       {"name": "clamp", "label": "Clamp", "type": "boolean", "default": False}],
                      [], [{"type": "rgba"}]), "Loads an image file.", False),
    "text": (_static([{"name": "text", "label": "Text", "type": "string", "default": "Text"},
                      {"name": "font", "label": "Font", "type": "file", "default": ""},
                      {"name": "fg", "label": "Foreground", "type": "color", "default": {"r": 1, "g": 1, "b": 1, "a": 1}},
                      {"name": "bg", "label": "Background", "type": "color", "default": {"r": 0, "g": 0, "b": 0, "a": 1}},
                      {"name": "font_size", "label": "Font size", "type": "float", "min": 0, "max": 128, "step": 1, "default": 32},
                      {"name": "line_spacing", "label": "Line Spacing", "type": "float", "min": -512, "max": 512, "step": 1, "default": 0},
                      {"name": "alignment", "label": "Align", "type": "enum", "values": ["Left", "Center", "Right"], "default": 0},
                      {"name": "center", "label": "Center", "type": "boolean", "default": False},
                      {"name": "x", "label": "X", "type": "float", "min": -0.5, "max": 0.5, "step": 0.001, "default": 0.1},
                      {"name": "y", "label": "Y", "type": "float", "min": -0.5, "max": 0.5, "step": 0.001, "default": 0.1}],
                     [], [{"type": "rgba"}]), "Renders text.", False),
    "iterate_buffer": (_static([dict(SIZE_PARAM),
                                {"name": "shrink", "label": "Shrink", "type": "boolean", "default": False},
                                {"name": "autostop", "label": "Auto stop", "type": "boolean", "default": False},
                                {"name": "iterations", "label": "Iterations", "type": "float", "min": 1, "max": 50, "step": 1, "default": 5},
                                {"name": "filter", "label": "Filter", "type": "boolean", "default": True},
                                {"name": "mipmap", "label": "Mipmap", "type": "boolean", "default": True},
                                {"name": "f32", "label": "32 bits", "type": "boolean", "default": False}],
                               [{"name": "in", "type": "rgba"}, {"name": "loop_in", "type": "rgba"}],
                               [{"type": "rgba"}, {"type": "rgba"}]), "Iterated buffer (feedback loop).", False),
    "ios": (builtin_ios, "Subgraph input/output node: 'gen_inputs' exposes ports as outputs, 'gen_outputs' as inputs (ports list).", True),
    "switch": (builtin_switch, "Selects one of 'choices' input groups; inputs = outputs x choices (A1,B1,A2,B2...).", True),
    "export": (_static([{"name": "size", "label": "Size", "type": "size", "first": 4, "last": 13, "default": 10},
                        {"name": "format", "label": "Format", "type": "enum", "values": ["PNG", "JPG", "WEBP", "EXR"], "default": 0},
                        {"name": "suffix", "label": "Filename", "type": "string", "default": "$project"}],
                       [{"name": "in", "type": "rgba"}], []), "Exports its input as an image file.", False),
    "comment": (_static([], [], []), "Comment box (no ports).", False),
    "comment_line": (_static([], [], []), "Comment line (no ports).", False),
    "webcam": (_static([], [], [{"type": "rgba"}]), "Webcam image.", False),
    "debug": (_static([], [{"name": "in", "type": "rgba"}], []), "Shows generated shader code of its input.", False),
    "reroute": (builtin_reroute, "Pass-through reroute point.", True),
    "portal": (builtin_portal, "Wireless link: io 0 = in (1 input), io 1 = out (1 output), matched by 'link'.", True),
    "meshmap": (None, "Mesh map (ports depend on mesh).", True),
    "sdf": (None, "SDF scene editor node (ports depend on scene).", True),
    "material_export": (None, "Empty material export node.", True),
    # Resolved from node content, not 'type' (listed for documentation):
    "graph": (None, "Subgraph with inline 'nodes'/'connections'. Ports come from its 'gen_inputs'/'gen_outputs' ios "
                    "nodes, parameters from its 'gen_parameters' remote node.", True),
    "remote": (None, "Exposes parameters of sibling nodes as 'widgets' (linked_control / config_control / "
                     "named_parameter); no ports.", True),
}

# Ports/params not knowable without running MM: None means "skip that check".
UNKNOWN = None

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class Catalog:
    def __init__(self, entries):
        self.entries = entries  # type name -> entry dict

    @classmethod
    def load(cls, path=CATALOG_PATH):
        if not Path(path).exists():
            return build_catalog()[0]
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["types"])

    # -- resolution, mirroring MMLoader.create_gen ----------------------------
    def node_defs(self, node, siblings=None):
        """Return dict(kind, params, inputs, outputs) for a node dict, or None if the type is unknown.

        params/inputs/outputs may be UNKNOWN (None) when they cannot be derived offline.
        `siblings` (name -> node) is the enclosing graph, needed for remote widgets.
        """
        siblings = siblings or {}
        if isinstance(node.get("shader_model"), dict):
            sm = node["shader_model"]
            params, inputs, outputs = shader_model_defs(sm, _num(node.get("generic_size", 1), 1))
            if "preview_shader" in sm:
                return {"kind": "material", "params": params, "inputs": inputs, "outputs": []}
            return {"kind": "shader", "params": params, "inputs": inputs, "outputs": outputs}
        if "connections" in node or "nodes" in node:
            return graph_defs(node, self)
        if "is_brush" in node or "sdf_scene" in node or "model_data" in node:
            return {"kind": "dynamic", "params": UNKNOWN, "inputs": UNKNOWN, "outputs": UNKNOWN}
        if "widgets" in node:
            return {"kind": "remote", "params": remote_param_defs(node, siblings, self), "inputs": [], "outputs": []}
        t = node.get("type")
        if not isinstance(t, str):
            return None
        if t in BUILTINS:
            fn = BUILTINS[t][0]
            if fn is None:
                return {"kind": "builtin", "params": UNKNOWN, "inputs": UNKNOWN, "outputs": UNKNOWN}
            params, inputs, outputs = fn(node)
            return {"kind": "builtin", "params": [norm_param(p) for p in params],
                    "inputs": [norm_input(p, i) for i, p in enumerate(inputs)],
                    "outputs": [norm_output(p, i) for i, p in enumerate(outputs)]}
        e = self.entries.get(t)
        if e is None or e.get("kind") == "builtin":
            return None
        if e.get("generic"):
            sm = e["template"]
            params, inputs, outputs = shader_model_defs(sm, _num(node.get("generic_size", 1), 1))
            if e["kind"] == "material":
                outputs = []
            return {"kind": e["kind"], "params": params, "inputs": inputs, "outputs": outputs}
        return {"kind": e["kind"], "params": e["parameters"], "inputs": e["inputs"], "outputs": e["outputs"]}


def graph_defs(node, catalog):
    inner = {n.get("name"): n for n in node.get("nodes", []) or [] if isinstance(n, dict)}
    params, inputs, outputs = [], [], []
    if "gen_parameters" in inner:
        params = remote_param_defs(inner["gen_parameters"], inner, catalog)
        values = node.get("parameters") or {}
        for p in params:  # the graph's own values are its defaults (inner defs are the linked node's)
            if p["name"] in values:
                p["default"] = values[p["name"]]
    if "gen_inputs" in inner:
        inputs = [norm_input(p, i) for i, p in enumerate(builtin_ios(inner["gen_inputs"])[2])]
    if "gen_outputs" in inner:
        outputs = [norm_output(p, i) for i, p in enumerate(builtin_ios(inner["gen_outputs"])[1])]
    return {"kind": "graph", "params": params, "inputs": inputs, "outputs": outputs}


def remote_param_defs(node, siblings, catalog, _depth=0):
    rv = []
    for w in node.get("widgets", []) or []:
        wt = w.get("type")
        if wt == "config_control":
            confs = sorted((w.get("configurations") or {}).keys())
            if confs == ["False", "True"]:
                p = {"name": w.get("name"), "label": w.get("label"), "type": "boolean"}
            else:
                p = {"name": w.get("name"), "label": w.get("label"), "type": "enum", "values": confs}
        elif wt == "linked_control":
            p = {"type": "unknown"}
            linked = (w.get("linked_widgets") or [None])[0]
            if linked and _depth < 8:
                target = siblings.get(linked.get("node"))
                if target is not None:
                    d = catalog.node_defs(target, siblings) if target is not node else None
                    for pd in (d or {}).get("params") or []:
                        if pd["name"] == linked.get("widget"):
                            p = dict(pd)
                            break
            p["name"] = w.get("name")
            p["label"] = w.get("label")
        elif wt == "named_parameter":
            p = {"name": w.get("name"), "label": w.get("label"), "type": "float",
                 "min": w.get("min"), "max": w.get("max"), "step": w.get("step"), "default": w.get("default")}
        else:
            continue
        p["widget_type"] = wt
        for k in ("shortdesc", "longdesc"):
            if w.get(k):
                p[k] = w[k]
        rv.append(norm_param(p))
    return rv


def build_catalog(nodes_dirs=None, library_dir=LIBRARY_DIR):
    nodes_dirs = [Path(d) for d in (nodes_dirs or [NODES_DIR])]
    raw = {}
    sources = {}
    load_errors = []
    for d in nodes_dirs:  # later dirs override earlier ones, like MMPaths.get_nodes_paths
        for f in sorted(d.glob("*.mmg")):
            try:
                raw[f.stem] = load_json_lenient(f)
                sources[f.stem] = str(f.relative_to(REPO)) if f.is_relative_to(REPO) else str(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                load_errors.append({"file": str(f), "error": str(e)})

    entries = {}
    catalog = Catalog(entries)
    # Pass 1: shader/material nodes (graphs may link to their params).
    for t, d in raw.items():
        sm = d.get("shader_model")
        if not isinstance(sm, dict) or "nodes" in d:
            continue
        kind = "material" if "preview_shader" in sm else "shader"
        params, inputs, outputs = shader_model_defs(sm)
        e = {"type": t, "kind": kind, "label": sm.get("name") or d.get("label") or t,
             "shortdesc": sm.get("shortdesc", ""), "longdesc": sm.get("longdesc", ""),
             "parameters": params, "inputs": inputs, "outputs": [] if kind == "material" else outputs,
             "source": sources[t]}
        if is_generic_model(sm):
            e["generic"] = True
            e["template"] = {k: sm.get(k, []) for k in ("parameters", "inputs", "outputs")}
        entries[t] = e
    # Pass 2: graph nodes; resolve in rounds so graphs referencing other graphs get filled in.
    graph_types = [t for t, d in raw.items() if t not in entries]
    for _ in range(3):
        for t in graph_types:
            d = raw[t]
            defs = graph_defs(d, catalog) if ("nodes" in d or "connections" in d) else None
            if defs is None:
                continue
            entries[t] = {"type": t, "kind": "graph", "label": d.get("label") or t,
                          "shortdesc": d.get("shortdesc", ""), "longdesc": d.get("longdesc", ""),
                          "parameters": defs["params"], "inputs": defs["inputs"], "outputs": defs["outputs"],
                          "source": sources[t]}
    for t, (fn, desc, dynamic) in BUILTINS.items():
        e = {"type": t, "kind": "builtin", "label": t, "shortdesc": desc, "longdesc": "", "dynamic": dynamic,
             "source": "addons/material_maker/engine/nodes/gen_%s.gd" % t}
        if fn is not None:
            params, inputs, outputs = fn({"name": "", "parameters": {}})
            e["parameters"] = [norm_param(p) for p in params]
            e["inputs"] = [norm_input(p, i) for i, p in enumerate(inputs)]
            e["outputs"] = [norm_output(p, i) for i, p in enumerate(outputs)]
        else:
            e["parameters"] = e["inputs"] = e["outputs"] = []
        entries.setdefault(t, e)

    # Library: categories, preset names, search keywords.
    aliases = {}
    alias_file = Path(library_dir) / "aliases.json"
    if alias_file.exists():
        aliases = load_json_lenient(alias_file)
    library_graphs = []
    for lf in sorted(Path(library_dir).glob("*.json")):
        if lf.name == "aliases.json":
            continue
        lib = load_json_lenient(lf)
        for item in lib.get("lib", []) if isinstance(lib, dict) else []:
            tree = item.get("tree_item", "")
            t = item.get("type")
            if "nodes" in item or "shader_model" in item:
                library_graphs.append(tree)
                continue
            e = entries.get(t)
            if e is None:
                continue
            e.setdefault("library", []).append(tree)
            if "category" not in e:
                e["category"] = tree.rsplit("/", 1)[0] if "/" in tree else tree
            if tree in aliases:
                kws = set(e.get("keywords", [])) | {k.strip() for k in aliases[tree].split(",") if k.strip()}
                e["keywords"] = sorted(kws)
    # Types not in the library menu are legacy/internal but still load; point at newer variants.
    def base(t):
        return re.sub(r"(_?\d+)+$", "", t)
    in_lib = {t for t, e in entries.items() if e.get("library")}
    for t, e in entries.items():
        e["in_library"] = t in in_lib
        if t in in_lib:
            continue
        newer = sorted(o for o in in_lib if o != t and base(o) == base(t))
        if newer:
            e["superseded_by"] = newer
            e.setdefault("category", entries[newer[0]]["category"])
        elif e["kind"] == "material":
            e.setdefault("category", "Material")
        e.setdefault("category", "Builtin" if e["kind"] == "builtin" else "Uncategorized")

    return Catalog(dict(sorted(entries.items()))), {"load_errors": load_errors, "library_graphs": library_graphs}


def cmd_catalog(args):
    dirs = [NODES_DIR] + [Path(d) for d in (args.nodes_dir or [])]
    catalog, info = build_catalog(dirs)
    data = {
        "generated_by": "agent_tools/mmx.py catalog",
        "nodes_dirs": [str(d.relative_to(REPO)) if d.is_relative_to(REPO) else str(d) for d in dirs],
        "notes": [
            "Ports are 0-based indices into inputs/outputs; connections are {from, from_port, to, to_port}.",
            "generic=true types repeat '#' items per node 'generic_size' (default 1); see 'template'.",
            "builtin types with dynamic=true derive ports from node fields (see shortdesc).",
            "Library items that are inline graphs (not node types) are listed in library_graphs.",
        ],
        "load_errors": info["load_errors"],
        "library_graphs": info["library_graphs"],
        "types": catalog.entries,
    }
    CATALOG_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n_lines = write_nodes_md(catalog)
    print(json.dumps({"catalog": str(CATALOG_PATH.relative_to(REPO)), "types": len(catalog.entries),
                      "nodes_md": str(NODES_MD_PATH.relative_to(REPO)), "nodes_md_lines": n_lines,
                      "load_errors": info["load_errors"]}, indent=1))
    return 0


# ---------------------------------------------------------------------------
# NODES.md
# ---------------------------------------------------------------------------

# ~65 most useful types, chosen from library categories + usage in material_maker/examples.
CURATED = [
    ("Material and workflow", ["material", "mwf_create_map", "mwf_mix", "mwf_map", "mwf_output"]),
    ("Simple", ["uniform", "uniform_greyscale", "shape", "gradient"]),
    ("Patterns", ["pattern", "bricks3", "bricks_uneven4", "weave2", "beehive2", "sine_wave", "scratches2"]),
    ("Noise", ["noise2", "perlin", "voronoi2", "fbm4", "color_noise", "noise_anisotropic", "dirt"]),
    ("Color and adjust", ["colorize", "invert", "brightness_contrast", "adjust_hsv", "tones", "tones_map",
                          "greyscale", "math", "combine", "decompose"]),
    ("Blend", ["blend", "blend2", "normal_blend2"]),
    ("Filters", ["gaussian_blur", "fast_blur", "directional_blur2", "slope_blur2", "edge_detect", "dilate",
                 "bevel", "occlusion2", "make_tileable"]),
    ("Normal and height", ["normal_map2", "normal_map", "normal2height"]),
    ("Fill (per-tile randomisation)", ["fill2", "fill_to_random_grey2", "fill_to_random_color3", "fill_to_uv2"]),
    ("Transforms and warps", ["transform2", "translate", "rotate", "scale", "mirror", "tile2x2", "kaleidoscope2",
                              "warp", "tiler", "splatter", "multi_warp2"]),
    ("Graph utilities", ["buffer", "switch", "reroute"]),
]

NODES_MD_PRIMER = """\
# Material Maker node reference (condensed)

Generated by `python3 agent_tools/mmx.py catalog` from `addons/material_maker/nodes/*.mmg` and
`material_maker/library/*.json`. Do not edit by hand. Full data for all {n_types} types:
`agent_tools/catalog.json`; one type: `python3 agent_tools/mmx.py node <type>`; check a file:
`python3 agent_tools/mmx.py validate <file.ptex>`.

## .ptex essentials
- A `.ptex` is JSON: a top-level graph `{{"nodes": [...], "connections": [...]}}`.
- Node: `{{"name": unique, "type": <type>, "parameters": {{...}}, "node_position": {{"x","y"}}}}`
  (+ optional `seed_int`, `seed_locked`, `generic_size`). Missing parameters use defaults.
- Connection: `{{"from": node, "from_port": i, "to": node, "to_port": j}}`. Ports are **0-based**
  indices into the lists below. An input takes **one** source; an output can fan out.
- Port types: `f` grayscale, `rgb`, `rgba` convert automatically. `sdf2d`, `sdf3d`, `tex3d`, ... don't.
- Values: float = number or expression string; enum = 0-based index; boolean = true/false;
  size = log2 pixels (10 = 1024); color = `{{"type":"Color","r","g","b","a"}}`; gradient =
  `{{"type":"Gradient","interpolation":1,"points":[{{"pos","r","g","b","a"}}]}}`.
- `blend`: in 0 `s1` = **foreground (top)**, in 1 `s2` = background, in 2 `a` = mask.
  Result = mix(s2, blend(s1,s2), amount*mask): mask 1 shows the foreground, 0 the background.
  Unconnected mask = 1. Lowering `amount` fades the foreground out.
- Generic nodes (`blend2`, ...) repeat their `#` ports/params `generic_size` times (default 1):
  `blend2` with generic_size 2 has inputs b, l1, a1, l2, a2.
- Subgraphs: a node with inline `nodes`/`connections` (type usually `graph`). Its ports are the
  `ports` of its inner `gen_inputs`/`gen_outputs` (`ios`) nodes; its parameters are the widgets of
  its inner `gen_parameters` (`remote`) node, named `param0..N`. Predefined subgraph types
  (e.g. `normal_map`) show the real labels below.
- Material node (name usually `Material`, type `material`): only inputs. Unity/URP export reads
  albedo, metallic, roughness, normal, ao, depth (height). Without a roughness input the export
  writes no `metal_smoothness` map.
- Parameter lines: `name` (Label) type range =default. Ports: index `name` type description.
"""

LEGACY_NOTE = [("transform", "transform2"), ("bricks", "bricks3"), ("voronoi", "voronoi2"), ("fbm", "fbm4"),
               ("noise", "noise2"), ("occlusion", "occlusion2"), ("scratches", "scratches2"),
               ("kaleidoscope", "kaleidoscope2"), ("beehive", "beehive2"), ("weave", "weave2")]


def _short(text, limit=90):
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(",;:") + "…"
    return text


def _fmt_num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, float):
        return ("%.4f" % v).rstrip("0").rstrip(".")
    return str(v)


def _fmt_default(p):
    d = p.get("default")
    if d is None:
        return ""
    t = p["type"]
    if t == "color" and isinstance(d, dict):
        return "=(" + ",".join(_fmt_num(d.get(k, 1)) for k in "rgba") + ")"
    if t == "boolean":
        return "=" + ("true" if d else "false")
    if t == "size":
        return "=%s(%dpx)" % (_fmt_num(d), 2 ** int(d)) if isinstance(d, (int, float)) else ""
    if t in ("float", "enum"):
        return "=" + _fmt_num(d)
    if isinstance(d, str):
        return '="%s"' % _short(d, 20)
    return ""


def _norm_word(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def fmt_param(p):
    s = "`%s`" % p["name"]
    if _norm_word(p.get("label", "")) != _norm_word(p["name"]):
        s += " (%s)" % p["label"]
    t = p["type"]
    if t == "float":
        s += " float"
        if "min" in p and "max" in p:
            s += " %s..%s" % (_fmt_num(p["min"]), _fmt_num(p["max"]))
    elif t == "enum":
        s += " enum[" + ", ".join("%d %s" % (i, v) for i, v in enumerate(p.get("values", []))) + "]"
    elif t == "size":
        s += " size %d..%dpx" % (2 ** int(p.get("first", 4)), 2 ** int(p.get("last", 13)))
    elif t == "boolean":
        s += " bool"
    else:
        s += " " + t
    return s + _fmt_default(p)


def fmt_port(p, is_input):
    s = "%d" % p["index"]
    if is_input and p.get("name"):
        s += " `%s`" % p["name"]
    s += " " + p.get("type", "?")
    desc = p.get("shortdesc") or p.get("label") or ""
    long = p.get("longdesc", "")
    if long and _norm_word(long) != _norm_word(desc):
        desc = (desc + ": " if desc else "") + _short(long, 70)
    if desc:
        s += " " + desc
    return s


def node_md(e):
    lines = []
    cat = "/".join(e["library"][0].split("/")) if e.get("library") else e.get("category", "")
    title = "### `%s` — %s" % (e["type"], e.get("label") or e["type"])
    if cat:
        title += " · " + cat
    if e.get("superseded_by"):
        title += " · legacy (newer: %s)" % ", ".join(e["superseded_by"])
    lines.append(title)
    desc = e.get("longdesc") or e.get("shortdesc") or ""
    if e.get("generic"):
        desc = (desc + " " if desc else "") + "(generic: '#' items repeat generic_size times)"
    if desc:
        lines.append(_short(desc, 220))
    ins = e.get("inputs") or []
    outs = e.get("outputs") or []
    lines.append("- in: " + (" · ".join(fmt_port(p, True) for p in ins) if ins else "none"))
    lines.append("- out: " + (" · ".join(fmt_port(p, False) for p in outs) if outs else "none"))
    params = e.get("parameters") or []
    if params:
        lines.append("- params: " + " · ".join(fmt_param(p) for p in params))
    lines.append("")
    return lines


def write_nodes_md(catalog):
    entries = catalog.entries
    out = NODES_MD_PRIMER.format(n_types=len(entries)).splitlines()
    out.append("- Legacy types still load (common in examples): " +
               ", ".join("`%s`→`%s`" % (a, b) for a, b in LEGACY_NOTE if a in entries and b in entries) +
               ". Prefer the newer ones; check ports with `mmx node`.")
    out.append("")
    missing = []
    for section, types in CURATED:
        out.append("## " + section)
        out.append("")
        for t in types:
            e = entries.get(t)
            if e is None:
                missing.append(t)
                continue
            out.extend(node_md(e))
    if missing:
        raise SystemExit("NODES.md: curated types missing from catalog: %s" % missing)
    if len(out) > NODES_MD_MAX_LINES:
        raise SystemExit("NODES.md would be %d lines (max %d); trim CURATED" % (len(out), NODES_MD_MAX_LINES))
    NODES_MD_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return len(out)


# ---------------------------------------------------------------------------
# node
# ---------------------------------------------------------------------------


def cmd_node(args):
    catalog = Catalog.load()
    e = catalog.entries.get(args.type)
    if e is None:
        close = difflib.get_close_matches(args.type, catalog.entries.keys(), n=5, cutoff=0.5)
        print(json.dumps({"error": "unknown type %r" % args.type, "did_you_mean": close}))
        return 1
    e = {k: v for k, v in e.items() if k != "template"}
    print(json.dumps(e, indent=1, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def cmd_validate(args):
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mmx", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("catalog", help="build agent_tools/catalog.json and agent_docs/NODES.md")
    p.add_argument("--nodes-dir", action="append", help="extra .mmg dir (e.g. the release app's nodes/); overrides repo defs")
    p.set_defaults(fn=cmd_catalog)
    p = sub.add_parser("validate", help="validate a .ptex file; JSON result, exit 0/1")
    p.add_argument("ptex")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("node", help="print one node type's catalog entry")
    p.add_argument("type")
    p.set_defaults(fn=cmd_node)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
