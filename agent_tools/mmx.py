#!/usr/bin/env python3
"""mmx: Material Maker tools for AI agents (stdlib only).

Subcommands:
  catalog   Parse node definitions (.mmg) and the node library into agent_tools/catalog.json
            and write the condensed reference agent_docs/NODES.md.
  validate  Structurally check a .ptex file; prints {"ok", "errors", "warnings"} JSON,
            exit code 0 (ok) or 1 (errors).
  node      Print one catalog entry as JSON.
  export    Validate, then export a .ptex with the Material Maker binary (config: mmx.toml);
            JSON summary of files written, exit 0 (ok) / 1 (validation/plan) / 2 (export failed).
  preview   Lit 3D preview PNG of a .ptex (engine --render-preview: the editor's 3D preview scene,
            sphere + plane, Studio environment, fixed camera); JSON, exit 0/1.
  node-preview  Render one output of one node to a PNG (engine --render-output, source mode),
            to debug a graph stage by stage; JSON, exit 0/1.
  sheet     Labeled contact-sheet PNG of an export dir (needs Pillow, agent_tools/.venv).
  run       One iteration: agent_runs/<run>/iter_NNN/ with ptex copy, out/, sheet.png.
            --ref <photo> sets the run's target photo (shown beside the 3D preview on every sheet).
  palette   Dominant colours of a reference photo (hex + share) and a ready colorize gradient.
  compare   [reference photo | 3D preview] + palette strips as one PNG.
  to-unity  Export into a Unity project (Assets/Materials/Generated/<Name>/) with the target that matches
            the project's render pipeline; keeps GUIDs on re-export; --verify runs a Unity batchmode check.
  wait      Poll for the result of an export/run started elsewhere (e.g. the Terminal panel).

Node type resolution mirrors MMLoader.create_gen (addons/material_maker/engine/loader.gd).
See agent_tools/README.md for limitations.
"""

import argparse
import difflib
import json
import re
import shutil
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
    "comment": (_static(None, [], []), "Comment box (no ports; free-form fields not checked).", False),
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
    def __init__(self, entries, port_types=None):
        self.entries = entries  # type name -> entry dict
        self.port_types = port_types or {}  # io_types.mmt: name -> {slot_type, converts_to}

    @classmethod
    def load(cls, path=CATALOG_PATH):
        if not Path(path).exists():
            return build_catalog()[0]
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["types"], data.get("port_types"))

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
            return {"kind": "builtin", "params": None if params is None else [norm_param(p) for p in params],
                    "inputs": [norm_input(p, i) for i, p in enumerate(inputs)],
                    "outputs": [norm_output(p, i) for i, p in enumerate(outputs)]}
        e = self.entries.get(t)
        if e is None or e.get("kind") == "builtin":
            return None
        if e.get("generic"):
            sm = e["template"]
            size = _num(node.get("generic_size", e.get("generic_size_default", 1)), 1)
            params, inputs, outputs = shader_model_defs(sm, size)
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
        gsize = _num(d.get("generic_size", 1), 1)  # nodes inherit the .mmg's generic_size unless they set one
        params, inputs, outputs = shader_model_defs(sm, gsize)
        e = {"type": t, "kind": kind, "label": sm.get("name") or d.get("label") or t,
             "shortdesc": sm.get("shortdesc", ""), "longdesc": sm.get("longdesc", ""),
             "parameters": params, "inputs": inputs, "outputs": [] if kind == "material" else outputs,
             "source": sources[t]}
        if is_generic_model(sm):
            e["generic"] = True
            e["generic_size_default"] = gsize
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
            e["parameters"] = [norm_param(p) for p in params or []]
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

    port_types = {}
    for d in nodes_dirs:
        f = d / "io_types.mmt"
        if f.exists():
            for pt in load_json_lenient(f):
                port_types[pt["name"]] = {"label": pt.get("label", ""), "slot_type": pt.get("slot_type"),
                                          "converts_to": [c["type"] for c in pt.get("convert", [])]}
    rv = Catalog(dict(sorted(entries.items())), port_types)
    return rv, {"load_errors": load_errors, "library_graphs": library_graphs}


KIND_BY_GENERATOR = {"MMGenShader": "shader", "MMGenGraph": "graph", "MMGenMaterial": "material"}


def _port_sig(ports):
    return [p.get("type") for p in ports or []]


def merge_engine_catalog(catalog, listing, described):
    """Overlay what the engine reports (--list-nodes, --describe-node --all) on the static catalog.
    The engine is authoritative for labels, descriptions, parameters, ports, categories and keywords; the
    static catalog keeps generic templates, sources and `dynamic`/`superseded_by` hints.
    Returns (entries, diffs): diffs lists the types where the static parse disagreed."""
    entries = json.loads(json.dumps(catalog.entries))
    diffs = []
    lib = {}
    for item in listing.get("items", []):
        if item.get("inline_graph") or not item.get("type"):
            continue
        lib.setdefault(item["type"], []).append(item)
    for n in described.get("nodes", []):
        t = n["type"]
        old = entries.get(t)
        e = dict(old) if old else {"type": t, "source": "addons/material_maker/nodes/%s.mmg" % t}
        e["kind"] = (old or {}).get("kind") or KIND_BY_GENERATOR.get(n.get("generator"), "builtin")
        e["generator"] = n.get("generator")
        if n.get("label") and n["label"] != "Unnamed":
            e["label"] = n["label"]
        for k in ("shortdesc", "longdesc"):
            if n.get(k):
                e[k] = n[k]
            e.setdefault(k, "")
        e["parameters"] = [norm_param(p) for p in n.get("parameters", [])]
        e["inputs"] = [norm_input(p, i) for i, p in enumerate(n.get("inputs", []))]
        e["outputs"] = [] if e["kind"] == "material" else [norm_output(p, i) for i, p in enumerate(n.get("outputs", []))]
        items = lib.get(t, [])
        if items:
            e["library"] = [i["tree_item"] for i in items]
            tree = items[0]["tree_item"]
            e["category"] = tree.rsplit("/", 1)[0] if "/" in tree else tree
            e["section"] = items[0]["category"]
            kws = set()
            for i in items:
                kws.update(i.get("keywords", []))
            if kws:
                e["keywords"] = sorted(kws)
        if old and not old.get("dynamic"):
            changed = [f for f, a, b in (
                ("parameters", [p["name"] for p in old.get("parameters", [])], [p["name"] for p in e["parameters"]]),
                ("inputs", _port_sig(old.get("inputs")), _port_sig(e["inputs"])),
                ("outputs", _port_sig(old.get("outputs")), _port_sig(e["outputs"]))) if a != b]
            if changed:
                diffs.append({"type": t, "fields": changed})
        entries[t] = e
    in_lib = {t for t, e in entries.items() if e.get("library")}
    for t, e in entries.items():
        e["in_library"] = t in in_lib
    return dict(sorted(entries.items())), diffs


def cmd_catalog(args):
    dirs = [NODES_DIR] + [Path(d) for d in (args.nodes_dir or [])]
    catalog, info = build_catalog(dirs)
    generated_by = "agent_tools/mmx.py catalog --static"
    diffs = None
    if not args.static:
        if args.nodes_dir:
            raise SystemExit("mmx: --nodes-dir needs --static (the engine reads its own node dirs)")
        cfg = load_config(args.config)
        listing, li = run_engine(["--list-nodes"], cfg)
        described, di = run_engine(["--describe-node", "--all"], cfg) if listing else (None, {})
        if not listing or not described or not listing.get("ok") or not described.get("ok"):
            err = li.get("error") or di.get("error") or "; ".join(((listing or {}).get("errors") or []) +
                                                                  ((described or {}).get("errors") or []))
            raise SystemExit("mmx: engine catalog failed (%s); use --static for the Python-only catalog" % err)
        entries, diffs = merge_engine_catalog(catalog, listing, described)
        catalog = Catalog(entries, catalog.port_types)
        generated_by = "agent_tools/mmx.py catalog (engine: --list-nodes, --describe-node --all)"
    data = {
        "generated_by": generated_by,
        "nodes_dirs": [str(d.relative_to(REPO)) if d.is_relative_to(REPO) else str(d) for d in dirs],
        "notes": [
            "Ports are 0-based indices into inputs/outputs; connections are {from, from_port, to, to_port}.",
            "generic=true types repeat '#' items per node 'generic_size' (default 1); see 'template'.",
            "builtin types with dynamic=true derive ports from node fields (see shortdesc).",
            "Library items that are inline graphs (not node types) are listed in library_graphs.",
        ],
        "load_errors": info["load_errors"],
        "library_graphs": info["library_graphs"],
        **({"engine_vs_static": diffs} if diffs is not None else {}),
        "port_types": catalog.port_types,
        "types": catalog.entries,
    }
    CATALOG_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n_lines = write_nodes_md(catalog)
    print(json.dumps({"catalog": str(CATALOG_PATH.relative_to(REPO)), "types": len(catalog.entries),
                      "nodes_md": str(NODES_MD_PATH.relative_to(REPO)), "nodes_md_lines": n_lines,
                      "load_errors": info["load_errors"],
                      **({"engine_vs_static_diffs": len(diffs)} if diffs is not None else {})}, indent=1))
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
        desc = (desc + " " if desc else "") + "(generic: '#' items repeat generic_size times, default %d; shown at default)" % e.get("generic_size_default", 1)
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


# Parameters that older MM versions wrote and the current node defs no longer have. MM ignores them on
# load, so they're warnings, not errors (found by validating material_maker/examples/*.ptex).
STALE_PARAMS = {
    "material": {"ao_light_affect", "normal_scale", "subsurf_scatter_strength", "resolution"},
    "normal_map": {"amount", "param3", "size"},
    "combine": {"color", "name"},
    "warp": {"epsilon"},
    "tiler": {"select_inputs"},
    "sdrhombus": {"r"},
    "sdboolean": {"bevel", "cx", "cy", "h", "r", "w"},
}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _as_index(v):
    """Ports/enums are ints; Godot writes them as floats (e.g. 2.0)."""
    if _is_num(v) and float(v).is_integer():
        return int(v)
    return None


class Validator:
    def __init__(self, catalog):
        self.catalog = catalog
        self.errors = []
        self.warnings = []

    def report(self, level, code, path, node, message, hint=None):
        item = {"code": code, "graph_path": path, "node": node, "message": message}
        if hint:
            item["hint"] = hint
        (self.errors if level == "error" else self.warnings).append(item)

    def err(self, *a, **kw):
        self.report("error", *a, **kw)

    def warn(self, *a, **kw):
        self.report("warning", *a, **kw)

    # -- top level -----------------------------------------------------------
    def validate_file(self, path):
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.err("unreadable_file", "/", None, str(e))
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            self.err("invalid_json", "/", None, "Not valid JSON: %s (line %d, column %d)" % (e.msg, e.lineno, e.colno))
            return
        if not isinstance(data, dict):
            self.err("bad_structure", "/", None, "Top level must be a JSON object with 'nodes' and 'connections'.")
            return
        self.check_graph(data, "/")

    # -- graphs --------------------------------------------------------------
    def check_graph(self, graph, path):
        nodes = graph.get("nodes")
        conns = graph.get("connections", [])
        if not isinstance(nodes, list):
            self.err("bad_structure", path, None, "'nodes' must be a list.")
            return
        if not isinstance(conns, list):
            self.err("bad_structure", path, None, "'connections' must be a list.")
            conns = []
        siblings = {}
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                self.err("bad_structure", path, None, "nodes[%d] is not an object." % i)
                continue
            name = n.get("name")
            if not isinstance(name, str) or not name:
                self.err("missing_name", path, None, "nodes[%d] has no 'name'." % i)
                continue
            if name in siblings:
                self.err("duplicate_node_name", path, name, "Node name %r is used more than once in this graph." % name,
                         "Node names must be unique within a graph; connections refer to nodes by name.")
            siblings[name] = n
        defs = {}
        for name, n in siblings.items():
            defs[name] = self.check_node(n, siblings, path)
        for name, n in siblings.items():
            if isinstance(n.get("nodes"), list):
                self.check_graph(n, path.rstrip("/") + "/" + name)
        self.check_connections(conns, siblings, defs, path)
        for name, n in siblings.items():
            if defs.get(name) and defs[name]["kind"] == "remote":
                self.check_remote_overrides(n, siblings, graph, path)

    def check_node(self, node, siblings, path):
        name = node["name"]
        t = node.get("type")
        content_typed = any(k in node for k in ("shader_model", "nodes", "connections", "widgets", "is_brush",
                                                "sdf_scene", "model_data"))
        if not isinstance(t, str) and not content_typed:
            self.err("missing_type", path, name, "Node %r has no 'type'." % name)
            return None
        if "generic_size" in node and (_as_index(node["generic_size"]) is None or node["generic_size"] < 1):
            self.err("bad_generic_size", path, name, "'generic_size' must be an integer >= 1.")
        d = self.catalog.node_defs(node, siblings)
        if d is None:
            if isinstance(t, str) and t.startswith("website:"):
                self.warn("unresolved_type", path, name, "Type %r is downloaded from the MM website at load time; "
                          "not checked offline." % t)
            else:
                close = difflib.get_close_matches(str(t), [k for k, e in self.catalog.entries.items()
                                                      if e["kind"] != "builtin" or e.get("parameters")], n=5, cutoff=0.6)
                self.err("unknown_type", path, name, "Unknown node type %r." % (t,),
                         ("Did you mean: %s? " % ", ".join(close) if close else "") +
                         "See agent_docs/NODES.md or agent_tools/catalog.json for valid types.")
            return None
        params = node.get("parameters", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            self.err("bad_structure", path, name, "'parameters' must be an object.")
        elif d["params"] is not None:
            self.check_params(node, params, d["params"], path)
        if d["kind"] == "remote":
            self.check_remote(node, siblings, path)
        return d

    # -- parameters ----------------------------------------------------------
    def check_params(self, node, values, pdefs, path):
        name = node["name"]
        by_name = {p["name"]: p for p in pdefs}
        for k, v in values.items():
            p = by_name.get(k)
            if p is None:
                if k in STALE_PARAMS.get(node.get("type"), ()) or isinstance(node.get("shader_model"), dict):
                    self.warn("ignored_parameter", path, name, "%s.%s is not a parameter of %s; MM ignores it "
                              "(left over from an older version or an edited inline shader)." % (name, k, node.get("type")))
                    continue
                close = difflib.get_close_matches(k, by_name.keys(), n=3, cutoff=0.6)
                valid = ", ".join(sorted(by_name)) or "(none)"
                self.err("unknown_parameter", path, name, "Node %r (%s) has no parameter %r." % (name, node.get("type"), k),
                         ("Did you mean: %s? " % ", ".join(close) if close else "") + "Valid: " + _short(valid, 300))
                continue
            self.check_value(node, k, v, p, path)

    def check_value(self, node, k, v, p, path):
        name = node["name"]
        t = p.get("type")
        where = "%s.%s" % (name, k)

        def bad(expected):
            self.err("bad_parameter_type", path, name, "%s should be %s, got %s." % (where, expected, json.dumps(v)[:80]),
                     _param_hint(p))

        if t == "float":
            if isinstance(v, str):
                return  # expression, e.g. "$time" or "2*$param"; not evaluated
            if not _is_num(v):
                return bad("a number (or an expression string)")
            lo, hi = p.get("min"), p.get("max")
            if _is_num(lo) and _is_num(hi) and not (lo <= v <= hi):
                self.warn("parameter_out_of_range", path, name, "%s = %s is outside the slider range %s..%s." %
                          (where, _fmt_num(v), _fmt_num(lo), _fmt_num(hi)), "Allowed, but usually a mistake.")
        elif t == "enum":
            i = _as_index(v)
            n = len(p.get("values", []))
            if i is None:
                return bad("an integer enum index")
            if n and not (0 <= i < n):
                self.err("bad_enum_value", path, name, "%s = %d is not a valid index (0..%d)." % (where, i, n - 1),
                         _param_hint(p))
        elif t == "boolean":
            if not (isinstance(v, bool) or v in (0, 1)):
                return bad("true or false")
        elif t == "size":
            i = _as_index(v)
            if i is None:
                return bad("an integer size exponent (log2 pixels, e.g. 10 = 1024)")
            lo, hi = p.get("first", 4), p.get("last", 13)
            if not (lo <= i <= hi):
                self.warn("parameter_out_of_range", path, name, "%s = %d is outside %d..%d (log2 pixels)." %
                          (where, i, lo, hi))
        elif t == "color":
            if isinstance(v, dict):
                if not all(_is_num(v.get(c)) for c in "rgb"):
                    return bad('a color {"type":"Color","r":..,"g":..,"b":..,"a":..}')
            elif not isinstance(v, str):
                return bad('a color {"type":"Color","r":..,"g":..,"b":..,"a":..}')
        elif t == "gradient":
            if isinstance(v, dict):
                pts = v.get("points")
                if not isinstance(pts, list) or not all(isinstance(q, dict) and _is_num(q.get("pos")) for q in pts):
                    return bad('a gradient {"type":"Gradient","interpolation":1,"points":[{"pos":0,"r":..,"g":..,"b":..,"a":..}]}')
            elif not isinstance(v, list):
                return bad("a gradient object")
        elif t in ("curve", "polygon", "polyline", "splines", "pixels", "lattice"):
            if not isinstance(v, (dict, list)):
                return bad("a %s object" % t)
        elif t in ("string", "file", "image_path"):
            if not isinstance(v, str):
                return bad("a string")

    # -- remote widgets ------------------------------------------------------
    def check_remote(self, node, siblings, path):
        name = node["name"]
        for w in node.get("widgets", []) or []:
            links = list(w.get("linked_widgets") or [])
            for conf in (w.get("configurations") or {}).values():
                links += [c for c in conf if isinstance(c, dict)]
            for l in links:
                target = siblings.get(l.get("node"))
                if target is None:
                    self.err("bad_linked_widget", path, name, "Widget %r links to missing node %r." %
                             (w.get("name"), l.get("node")))
                    continue
                td = self.catalog.node_defs(target, siblings) if target is not node else None
                if td and td["params"] is not None and l.get("widget") not in {p["name"] for p in td["params"]}:
                    self.err("bad_linked_widget", path, name, "Widget %r links to %s.%s, which is not a parameter." %
                             (w.get("name"), l.get("node"), l.get("widget")))

    def check_remote_overrides(self, node, siblings, graph, path):
        """Remote widgets push their value onto linked parameters on load, so editing a linked
        parameter directly has no effect (Phase 0: Bricks.repeat edits were silently ignored)."""
        values = dict(node.get("parameters") or {})
        if node["name"] == "gen_parameters" and isinstance(graph.get("parameters"), dict):
            values.update(graph["parameters"])  # the subgraph node's own paramN values win
        gname = path.rstrip("/").rsplit("/", 1)[-1] or "(top level)"
        for w in node.get("widgets", []) or []:
            wname = w.get("name")
            if wname not in values:
                continue
            v = values[wname]
            if w.get("type") == "linked_control":
                targets = [(l, v) for l in w.get("linked_widgets") or []]
                why = "%s = %s" % (wname, json.dumps(v))
            elif w.get("type") == "config_control":
                keys = sorted((w.get("configurations") or {}).keys())
                i = (1 if v else 0) if isinstance(v, bool) else _as_index(v)
                if i is None or not (0 <= i < len(keys)):
                    continue
                targets = [(l, l.get("value")) for l in w["configurations"][keys[i]]]
                why = "%s = %d (%r)" % (wname, i, keys[i])
            else:
                continue
            for l, expected in targets:
                target = siblings.get(l.get("node"))
                if target is None or not isinstance(target.get("parameters"), dict):
                    continue
                actual = target["parameters"].get(l.get("widget"))
                if actual is None or _same_value(actual, expected):
                    continue
                where = "on the subgraph node (%s.%s)" % (gname, wname) if node["name"] == "gen_parameters" \
                    else "on remote %r" % node["name"]
                self.warn("overridden_parameter", path, l.get("node"),
                          "%s.%s = %s will be overwritten with %s by remote %r widget %s (%s)." %
                          (l.get("node"), l.get("widget"), json.dumps(actual)[:60], json.dumps(expected)[:60],
                           node["name"], wname, why),
                          "Edit the remote parameter instead, %s." % where)

    # -- connections ---------------------------------------------------------
    def check_connections(self, conns, siblings, defs, path):
        fed = {}
        for i, c in enumerate(conns):
            if not isinstance(c, dict) or not all(k in c for k in ("from", "from_port", "to", "to_port")):
                self.err("bad_connection", path, None, "connections[%d] must have from, from_port, to, to_port." % i)
                continue
            label = "%s:%s -> %s:%s" % (c["from"], c["from_port"], c["to"], c["to_port"])
            fp, tp = _as_index(c["from_port"]), _as_index(c["to_port"])
            if fp is None or tp is None or fp < 0 or tp < 0:
                self.err("bad_connection", path, None, "Connection %s: ports must be integers >= 0." % label)
                continue
            out_t = in_t = None
            ok = True
            for end, port, key, word in ((c["from"], fp, "outputs", "output"), (c["to"], tp, "inputs", "input")):
                if end not in siblings:
                    close = difflib.get_close_matches(str(end), siblings.keys(), n=3, cutoff=0.6)
                    self.err("unknown_node", path, None, "Connection %s refers to missing node %r." % (label, end),
                             "Did you mean: %s?" % ", ".join(close) if close else None)
                    ok = False
                    continue
                d = defs.get(end)
                if d is None or d[key] is None:
                    continue  # unknown type (already reported) or dynamic ports
                ports = d[key]
                if port >= len(ports):
                    listing = ", ".join("%d %s%s" % (p["index"], (p.get("name") + " ") if p.get("name") else "",
                                                     p.get("type", "")) for p in ports) or "none"
                    self.err("bad_%s_port" % word, path, end, "Connection %s: %r (%s) has no %s port %d." %
                             (label, end, siblings[end].get("type"), word, port), "%ss: %s" % (word.capitalize(), listing))
                    ok = False
                    continue
                if word == "output":
                    out_t = ports[port].get("type")
                else:
                    in_t = ports[port].get("type")
            if not ok:
                continue
            key = (c["to"], tp)
            if key in fed:
                self.err("input_multiply_connected", path, c["to"], "Input %s:%d is fed by both %s and %s:%s." %
                         (c["to"], tp, fed[key], c["from"], fp), "An input takes exactly one connection; remove one.")
            else:
                fed[key] = "%s:%s" % (c["from"], fp)
            if out_t and in_t and not self.compatible(out_t, in_t):
                self.err("port_type_mismatch", path, c["to"], "Connection %s connects a %s output to a %s input." % (label, out_t, in_t),
                         "f, rgb and rgba convert freely; sdf2d, sdf3d, tex3d, fill etc. only connect to their own kind.")

    def compatible(self, a, b):
        if a == b or "any" in (a, b):
            return True
        pa, pb = self.catalog.port_types.get(a), self.catalog.port_types.get(b)
        if pa is None or pb is None:
            return True  # unknown port type: don't guess
        return b in pa["converts_to"] or pa["slot_type"] == pb["slot_type"]


def _same_value(a, b):
    if _is_num(a) and _is_num(b):
        return abs(a - b) < 1e-6
    return a == b


def _param_hint(p):
    s = fmt_param(p)
    return "Expected: " + s


def validate_file(path, catalog=None):
    v = Validator(catalog or Catalog.load())
    v.validate_file(path)
    return {"ok": not v.errors, "errors": v.errors, "warnings": v.warnings}


def validate_full(path, cfg=None, fast=False, timeout=None):
    """Python validation (fast pre-check), then, if that passed, the engine's --validate (unknown types,
    connections, shader compilation). Engine problems (no Godot, timeout) only add a warning."""
    cfg = cfg or load_config()
    result = validate_file(path)
    result["checks"] = ["static"]
    if fast or not cfg.get("validate_engine", True):
        return result
    if not result["ok"]:
        result["warnings"].append({"code": "engine_check_skipped", "graph_path": "/", "node": None,
                                   "message": "Engine validation not run: fix the errors above first."})
        return result
    e = engine_validate(path, cfg, timeout)
    if not e["available"]:
        result["warnings"].append({"code": "engine_unavailable", "graph_path": "/", "node": None,
                                   "message": "Engine validation not run: %s" % e["error"]})
        return result
    result["checks"].append("engine")
    result["engine"] = {k: e[k] for k in ("seconds", "nodes", "outputs_checked")}
    result["errors"] += e["errors"]
    result["warnings"] += e["warnings"]
    result["ok"] = not result["errors"]
    return result


def cmd_validate(args):
    result = validate_full(args.ptex, load_config(args.config), args.fast, args.timeout)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------------------
# Config (agent_tools/mmx.toml)
# ---------------------------------------------------------------------------

CONFIG_PATH = REPO / "agent_tools" / "mmx.toml"
RUNS_DIR = REPO / "agent_runs"
VENV_PYTHON = REPO / "agent_tools" / ".venv" / "bin" / "python"
RESULT_NAME = "mmx_result.json"   # written by export/run; polled by `mmx wait`
STATUS_NAME = "mmx_status.json"   # written by run while in progress
PREVIEW_NAME = "preview_3d.png"   # 3D preview written by run; top row of the sheet

DEFAULT_CONFIG = {
    "mode": "release",
    "target": "Unity/URP",
    "timeout": 180,
    "preview_3d": True,          # mmx run renders iter_NNN/preview_3d.png (source mode)
    "preview_mesh": "sphere+plane",
    "preview_env": "Studio",
    "preview_size": 512,
    "release": {
        "binary": "/Applications/Material Maker.app/Contents/MacOS/Material Maker",
        "data_dir": "/Applications/Material Maker.app/Contents/MacOS",
    },
    "source": {
        "godot": "/Applications/Godot.app/Contents/MacOS/Godot",
        "project": str(REPO),
    },
    "unity": {
        "editor": "",            # Unity executable (…/Unity.app/Contents/MacOS/Unity) for to-unity --verify
        "project": "",           # default --project
        "verify_timeout": 900,   # seconds (a first batchmode launch imports the whole project)
    },
}


def load_config(path=None):
    """Defaults merged with mmx.toml (or $MMX_CONFIG / --config)."""
    import os
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = Path(path or os.environ.get("MMX_CONFIG") or CONFIG_PATH)
    if path.exists():
        import tomllib  # Python 3.11+
        with open(path, "rb") as f:
            user = tomllib.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def export_command(cfg, ptex, out_dir, target, size=None, output_name=None):
    """argv for one CLI export. Paths must be absolute (the app changes its cwd on macOS).
    size: texture size in pixels (source mode only; None/0 = the graph's own size).
    output_name: file prefix instead of the .ptex stem (source mode only; --output-file)."""
    mode = cfg["mode"]
    # --target, never -t (Godot swallows -t); --export-material, never --export (Godot project export).
    if mode == "release":
        if size:
            raise SystemExit("mmx: --size needs mode = \"source\" (the release app ignores --size)")
        if output_name:
            raise SystemExit("mmx: a custom output name needs mode = \"source\"")
        return [cfg["release"]["binary"], "--export-material", "--target", target, "-o", str(out_dir), str(ptex)]
    elif mode == "source":
        # Our parse_args.gd: --json summary line, exit codes 0/1/2/3, no silent target fallback.
        cmd = [cfg["source"]["godot"], "--path", cfg["source"]["project"], "--export-material", "--json",
               "--strict-target", "--target", target]
        if size:
            cmd += ["--size", str(int(size))]
        if output_name:
            cmd += ["--output-file", output_name]
        return cmd + ["-o", str(out_dir), str(ptex)]
    else:
        raise SystemExit("mmx: unknown mode %r in config" % mode)


def mmg_dirs(cfg):
    dirs = []
    if cfg["mode"] == "release":
        dirs.append(Path(cfg["release"]["data_dir"]) / "nodes")
    dirs.append(NODES_DIR)
    return [d for d in dirs if d.is_dir()]


# ---------------------------------------------------------------------------
# Expected export files (mirrors MMGenMaterial.export_material)
# ---------------------------------------------------------------------------

_COND_TOKEN = re.compile(r"\(|\)|\w+")


def eval_condition(cond, connected):
    """Evaluate an export `conditions` string such as "$(connected:a_tex) or $(connected:b_tex)".
    Returns True/False, or None if it uses something we don't model."""
    s = re.sub(r"\$\(connected:(\w+)\)", lambda m: "True" if m.group(1) in connected else "False", cond)
    if "$(" in s or any(t not in ("True", "False", "and", "or", "not", "(", ")") for t in _COND_TOKEN.findall(s)):
        return None
    try:
        return bool(eval(s, {"__builtins__": {}}, {}))
    except Exception:
        return None


def find_material_node(ptex_data, cfg):
    """(node, shader_model) of the first top-level node with export profiles, else (None, None)."""
    for n in ptex_data.get("nodes", []):
        sm = n.get("shader_model")
        if not (isinstance(sm, dict) and "exports" in sm):
            sm = None
            for d in mmg_dirs(cfg):
                f = d / (str(n.get("type", "")) + ".mmg")
                if f.exists():
                    sm = load_json_lenient(f).get("shader_model")
                    break
        if isinstance(sm, dict) and sm.get("exports"):
            return n, sm
    return None, None


def expected_files(ptex_path, out_dir, target, cfg, output_name=None):
    """{"required": [...], "optional": [...], "targets": [...], "material_node": name} or {"error": ...}.
    output_name: file prefix instead of the .ptex stem."""
    data = load_json_lenient(ptex_path)
    node, sm = find_material_node(data, cfg)
    if node is None:
        return {"error": "no material node with export targets found at the top level of the graph"}
    targets = sorted(sm["exports"])
    if target not in sm["exports"]:
        close = difflib.get_close_matches(target, targets, n=3, cutoff=0.3)
        return {"error": "material node %r (type %s) has no export target %r; did you mean %s? Available: %s"
                % (node["name"], node.get("type"), target, close, targets)}
    inputs = sm.get("inputs", [])
    ports = {c.get("to_port") for c in data.get("connections", []) if c.get("to") == node["name"]}
    connected = {inputs[i]["name"] for i in ports if isinstance(i, int) and 0 <= i < len(inputs)}
    stem = output_name or Path(ptex_path).stem
    prefix = str(Path(out_dir) / stem)
    ctx = {"$(path_prefix)": prefix, "$(file_prefix)": stem,
           "$(dir_prefix)": str(out_dir), "$(path_separator)": "/"}
    required, optional = [], []
    for f in sm["exports"][target].get("files", []):
        name = f.get("file_name", "")
        for k, v in ctx.items():
            name = name.replace(k, v)
        if "$(" in name:
            continue
        cond = eval_condition(f["conditions"], connected) if "conditions" in f else True
        if cond is False:
            continue
        (required if cond else optional).append(name)
    return {"required": required, "optional": optional, "targets": targets,
            "material_node": node["name"], "connected_inputs": sorted(connected)}


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(path)  # atomic, so `mmx wait` never reads half a file


# Printed on every successful run (see agent_docs/phase0_notes.md).
HARMLESS_LOG = ("resources still in use at exit", "ObjectDB instances were leaked", "user://export_targets",
                "Steam", "SteamAPI")

# parse_args.gd exit codes (source mode)
MM_EXIT_CODES = {1: "bad arguments", 2: "load/parse failure", 3: "export failure"}


def parse_mm_summary(text):
    """The last `--json` summary line ({"mm_cli": 1, ...}) printed by parse_args.gd, or None."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"mm_cli"' in line:
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def run_export(ptex, out_dir, target=None, cfg=None, timeout=None, keep_meta=False, skip_validate=False,
               size=None, output_name=None):
    """Validate, export with the MM binary, check outputs. Returns a JSON-able summary
    (also written to <out_dir>/mmx_result.json)."""
    import os
    import signal
    import subprocess
    import time
    cfg = cfg or load_config()
    target = target or cfg["target"]
    timeout = float(timeout or cfg["timeout"])
    ptex = Path(ptex).resolve()
    out_dir = Path(out_dir).resolve()
    res = {"ok": False, "stage": "validate", "ptex": str(ptex), "out_dir": str(out_dir), "target": target,
           "mode": cfg["mode"]}
    if size:
        res["size"] = size

    def done(**kw):
        res.update(kw)
        if out_dir.is_dir():
            _write_json(out_dir / RESULT_NAME, res)
        return res

    if not ptex.exists():
        return done(error="ptex not found")
    if not skip_validate:
        v = validate_file(ptex)
        res["validation"] = {"errors": v["errors"], "warnings": len(v["warnings"])}
        if not v["ok"]:
            return done(error="validation failed; fix the errors (mmx validate %s)" % ptex)
    res["stage"] = "plan"
    exp = expected_files(ptex, out_dir, target, cfg, output_name)
    if "error" in exp:
        return done(error=exp["error"])
    res["connected_inputs"] = exp["connected_inputs"]

    out_dir.mkdir(parents=True, exist_ok=True)  # MM only creates the last level, and hangs on failure
    (out_dir / RESULT_NAME).unlink(missing_ok=True)
    # MM skips existing `prompt_overwrite` files (.mat, .meta) in CLI mode, and old maps would hide
    # a failed export: remove previous outputs first.
    for f in exp["required"] + exp["optional"]:
        if not (keep_meta and f.endswith(".meta")):
            Path(f).unlink(missing_ok=True)

    res["stage"] = "export"
    cmd = export_command(cfg, ptex, out_dir, target, size, output_name)
    log_path = out_dir / "export.log"
    err_path = out_dir / "export.stderr.log"
    res["log"] = str(log_path)
    res["stderr_log"] = str(err_path)
    res["command"] = cmd
    start = time.time()
    with open(log_path, "w") as log, open(err_path, "w") as err:
        proc = subprocess.Popen(cmd, stdout=log, stderr=err, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            rc = proc.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            rc = proc.wait()
            timed_out = True
    res["seconds"] = round(time.time() - start, 2)
    res["exit_code"] = rc

    log_text = log_path.read_text(errors="replace")
    err_text = err_path.read_text(errors="replace")
    mm = parse_mm_summary(log_text) if cfg["mode"] == "source" else None
    if mm is not None:
        res["mm"] = {k: mm.get(k) for k in ("exit_code", "warnings", "errors")}
        res["mm"]["targets"] = sorted({m.get("target") for m in mm.get("materials", []) if m.get("target")})
        res["mm"]["sizes"] = sorted({m.get("size") for m in mm.get("materials", []) if m.get("size")})
        res["mm"]["files_written"] = len(mm.get("files", []))
        if mm.get("warnings"):
            res["warnings"] = mm["warnings"]
    res["log_errors"] = [l.strip() for l in (log_text + "\n" + err_text).splitlines()
                         if re.search(r"\bERROR\b|Error in expression|SCRIPT ERROR|Failed", l)
                         and not any(h in l for h in HARMLESS_LOG)][:20]
    written, missing = [], []
    for f in exp["required"] + exp["optional"]:
        p = Path(f)
        if p.exists() and (p.stat().st_mtime >= start - 1 or (keep_meta and f.endswith(".meta"))):
            written.append({"file": p.name, "bytes": p.stat().st_size})
        elif f in exp["required"]:
            missing.append(p.name)
    res["files"] = written
    res["missing"] = missing
    hints = []
    if timed_out:
        hints.append("timed out after %ss. If launched from Claude's Bash tool the app hangs in "
                     "CAMetalLayer nextDrawable: run mmx via the Terminal panel (run_in_terminal)." % timeout)
    elif not (log_text + err_text).strip() and res["seconds"] < 3:
        hints.append("app quit instantly with no output: add steam_appid.txt (4110830) next to the binary")
    if hints:
        res["hints"] = hints
    if timed_out:
        return done(error="timeout")
    if cfg["mode"] == "source":
        if rc != 0:
            what = MM_EXIT_CODES.get(rc, "app exited with code %s" % rc)
            detail = "; ".join((mm or {}).get("errors") or []) or "see %s" % err_path
            return done(error="%s: %s" % (what, detail))
        if mm is None:
            return done(error="no JSON summary from Material Maker (is parse_args.gd up to date?); see %s" % log_path)
    if missing:
        return done(error="expected output files missing (see log_errors / %s)" % log_path)
    return done(ok=True, stage="done")


def cmd_export(args):
    res = run_export(args.ptex, args.out, args.target, load_config(args.config), args.timeout,
                     args.keep_meta, args.no_validate, args.size)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else (1 if res["stage"] in ("validate", "plan") else 2)


# ---------------------------------------------------------------------------
# engine CLI modes (cli_inspect.gd: --list-nodes, --describe-node, --validate; source mode only)
# ---------------------------------------------------------------------------

ENGINE_EXIT_CODES = {1: "bad arguments", 2: "load failure", 4: "validation errors"}


def run_engine(mm_args, cfg=None, timeout=None):
    """Run one engine inspection mode with --json. Returns (summary or None, info).
    info: {"seconds", "exit_code", "error"?}; summary is the parsed {"mm_cli": 1, ...} line."""
    import os
    import signal
    import subprocess
    import tempfile
    import time
    cfg = cfg or load_config()
    if cfg["mode"] != "source":
        return None, {"error": "engine checks need mode = \"source\" in mmx.toml (the release app lacks them)"}
    cmd = [cfg["source"]["godot"], "--path", cfg["source"]["project"]] + list(mm_args) + ["--json"]
    timeout = float(timeout or cfg["timeout"])
    start = time.time()
    with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
        try:
            proc = subprocess.Popen(cmd, stdout=out, stderr=err, stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            return None, {"error": "cannot start Godot: %s" % e}
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return None, {"error": "timeout after %ss" % timeout, "seconds": round(time.time() - start, 2)}
        out.seek(0)
        err.seek(0)
        text, err_text = out.read(), err.read()
    info = {"seconds": round(time.time() - start, 2), "exit_code": rc}
    summary = parse_mm_summary(text)
    if summary is None:
        tail = [l for l in err_text.splitlines() if "ERROR" in l and not any(h in l for h in HARMLESS_LOG)][-3:]
        info["error"] = "no JSON summary from the engine (exit code %s)%s" % (rc, ": " + " | ".join(tail) if tail else "")
    return summary, info


def engine_validate(ptex, cfg=None, timeout=None):
    """Engine validation of one .ptex: {"available", "ok", "errors", "warnings", "seconds", ...}."""
    summary, info = run_engine(["--validate", str(Path(ptex).resolve())], cfg, timeout)
    if summary is None:
        return {"available": False, "error": info["error"]}
    files = summary.get("files") or []
    if not files:  # bad arguments
        return {"available": False, "error": "; ".join(summary.get("errors") or []) or "no result"}
    f = files[0]
    for item in f.get("errors", []) + f.get("warnings", []):
        item["source"] = "engine"
    return {"available": True, "ok": f.get("ok", False), "errors": f.get("errors", []),
            "warnings": f.get("warnings", []), "seconds": info["seconds"], "nodes": f.get("nodes"),
            "outputs_checked": f.get("outputs_checked")}


def node_preview_path(ptex, node, port=0, runs_dir=None):
    """Default output of node-preview: agent_runs/node_preview/<ptex stem>/<node>_p<port>.png
    (sub-graph paths a/b become a__b)."""
    return Path(runs_dir or RUNS_DIR) / "node_preview" / Path(ptex).stem / ("%s_p%d.png" % (node.replace("/", "__"), port))


def _engine_render(mode_args, out, cfg=None, timeout=None, keys=()):
    """Run an engine render mode that writes `out` (--render-output / --render-preview).
    Returns {"ok", "file", "seconds", "errors", "warnings", <keys copied from the summary>}."""
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()  # never report a stale image
    summary, info = run_engine(list(mode_args) + ["-o", str(out)], cfg, timeout)
    rv = {"ok": False, "file": None, "seconds": info.get("seconds"), "errors": [], "warnings": []}
    if summary is None:
        rv["errors"].append(info["error"])
        return rv
    rv["errors"] = summary.get("errors") or []
    rv["warnings"] = summary.get("warnings") or []
    for k in keys:
        if k in summary:
            rv[k] = summary[k]
    rv["ok"] = bool(summary.get("ok")) and out.is_file()
    if summary.get("ok") and not out.is_file():
        rv["errors"].append("engine reported success but %s was not written" % out)
    if rv["ok"]:
        rv["file"] = str(out)
    return rv


def node_preview(ptex, node, port=0, size=512, out=None, cfg=None, timeout=None):
    """Render one output of one node to a PNG with the engine's --render-output.
    Returns {"ok", "file", "node", "port", "size", "output_type", "outputs", "seconds", "errors", "warnings"}."""
    out = out or node_preview_path(ptex, node, port)
    args = ["--render-output", str(Path(ptex).resolve()), "--node", node, "--port", str(port), "--size", str(size)]
    rv = {"node": node, "port": port, "size": size}
    rv.update(_engine_render(args, out, cfg, timeout, ("type", "output_type", "output_label", "outputs")))
    return rv


def render_preview(ptex, out=None, mesh=None, env=None, size=None, cfg=None, timeout=None):
    """Lit 3D preview of a .ptex with the engine's --render-preview (defaults from mmx.toml:
    sphere+plane, Studio, 512 px per view). Returns {"ok", "file", "meshes", "env", "size", "width",
    "height", "image_size", "seconds", "errors", "warnings"}."""
    cfg = cfg or load_config()
    mesh = mesh or cfg["preview_mesh"]
    env = env or cfg["preview_env"]
    size = int(size or cfg["preview_size"])
    out = out or (RUNS_DIR / "preview" / (Path(ptex).stem + ".png"))
    args = ["--render-preview", str(Path(ptex).resolve()), "--mesh", mesh, "--env", str(env), "--size", str(size)]
    rv = {"meshes": mesh.split("+"), "env": env, "size": size}
    rv.update(_engine_render(args, out, cfg, timeout, ("meshes", "env", "width", "height", "image_size")))
    return rv


def cmd_preview(args):
    result = render_preview(args.ptex, args.out, args.mesh, args.env, args.size, load_config(args.config), args.timeout)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["ok"] else 1


def cmd_node_preview(args):
    result = node_preview(args.ptex, args.node, args.port, args.size, args.out, load_config(args.config), args.timeout)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------------------
# sheet (needs Pillow: agent_tools/.venv, see README)
# ---------------------------------------------------------------------------

# (file-name suffix, kind); longest suffixes first so "metal_smoothness" wins over "smoothness".
MAP_SUFFIXES = [
    ("metal_smoothness", "metal_smoothness"), ("orm", "orm"), ("base_color", "albedo"), ("basecolor", "albedo"),
    ("albedo", "albedo"), ("diffuse", "albedo"), ("color", "albedo"), ("normal", "normal"),
    ("height", "height"), ("depth", "height"), ("displacement", "height"),
    ("roughness", "roughness"), ("smoothness", "smoothness"), ("metallic", "metallic"), ("metal", "metallic"),
    ("occlusion", "ao"), ("ao", "ao"), ("emission", "emission"), ("opacity", "opacity"), ("sss", "sss"),
]
SHEET_ORDER = ["lit", "lit tiled 2x2", "albedo", "normal", "height", "roughness", "metallic", "ao",
               "emission", "opacity", "sss"]


def classify_maps(directory):
    """{kind: Path} for the PNGs in an export dir (sheet.png and unknowns under their own suffix)."""
    maps = {}
    for p in sorted(Path(directory).glob("*.png")):
        if p.name in ("sheet.png", PREVIEW_NAME):
            continue
        stem = p.stem.lower()
        for suf, kind in MAP_SUFFIXES:
            if stem == suf or stem.endswith("_" + suf):
                maps.setdefault(kind, p)
                break
        else:
            maps.setdefault(stem.rsplit("_", 1)[-1], p)
    return maps


def _channel(img, band):
    return img.convert("RGBA").getchannel(band)


def split_maps(maps):
    """Open images and split packed maps into single-meaning grayscale/RGB images: {label: Image}."""
    from PIL import Image, ImageOps
    out = {}
    for kind, p in maps.items():
        img = Image.open(p)
        img.load()
        if kind == "metal_smoothness":  # Unity: R = metallic, A = smoothness
            out["metallic"] = _channel(img, "R")
            out["roughness"] = ImageOps.invert(_channel(img, "A"))
        elif kind == "orm":  # glTF/Godot ORM: R = AO, G = roughness, B = metallic
            out["ao"], out["roughness"], out["metallic"] = (_channel(img, b) for b in "RGB")
        elif kind == "smoothness":
            out.setdefault("roughness", ImageOps.invert(img.convert("L")))
        elif kind in ("albedo", "normal", "emission"):
            out[kind] = img.convert("RGB")
        elif kind in ("height", "ao", "roughness", "metallic", "opacity"):
            out[kind] = img.convert("L")
        else:
            out[kind] = img.convert("RGB")
    return out


def lit_preview(albedo, normal, ao=None, size=512):
    """Crude Lambert render (one light from top-left) so relief reads at a glance. Pure Pillow."""
    from PIL import Image
    a = albedo.convert("RGB").resize((size, size)).tobytes()
    n = normal.convert("RGB").resize((size, size)).tobytes()
    o = ao.convert("L").resize((size, size)).tobytes() if ao is not None else None
    lx, ly, lz = -0.5, -0.6, 0.62  # image space (y down): up-left of the surface
    ln = (lx * lx + ly * ly + lz * lz) ** 0.5
    lx, ly, lz = lx / ln, ly / ln, lz / ln
    px = bytearray(len(a))
    for i in range(size * size):
        j = 3 * i
        nx, ny, nz = n[j] / 127.5 - 1, -(n[j + 1] / 127.5 - 1), n[j + 2] / 127.5 - 1  # Unity normals: +Y up; image y is down
        nl = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        lam = max(0.0, (nx * lx + ny * ly + nz * lz) / nl)
        k = (0.25 + 0.85 * lam) * ((0.5 + 0.5 * o[i] / 255) if o is not None else 1.0)
        px[j], px[j + 1], px[j + 2] = (min(255, int(a[j + c] * k)) for c in range(3))
    return Image.frombytes("RGB", (size, size), bytes(px))


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def find_preview(directory):
    """The 3D preview that goes with an export dir: <dir>/preview_3d.png or <dir>/../preview_3d.png."""
    for p in (Path(directory) / PREVIEW_NAME, Path(directory).parent / PREVIEW_NAME):
        if p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# reference photos: palette + side-by-side comparison
# ---------------------------------------------------------------------------

REFERENCE_STEM = "reference"   # agent_runs/<run>/reference.<ext>: the run's target photo (mmx run --ref)
PALETTE_SAMPLE = 192           # photos are downscaled to this many pixels on the long side before quantizing


def _luma(rgb):
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def _parse_crop(crop):
    """'L,T,R,B' as fractions 0..1 → tuple, or None."""
    if not crop:
        return None
    try:
        box = tuple(float(v) for v in crop.split(","))
    except ValueError:
        box = ()
    if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise SystemExit("mmx: --crop must be L,T,R,B fractions with 0 <= L < R <= 1 and 0 <= T < B <= 1")
    return box


def _open_rgb(path, crop=None):
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)  # phone photos store rotation in EXIF
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
            im = Image.alpha_composite(bg, im)
        im = im.convert("RGB")
    if crop:
        w, h = im.size
        im = im.crop((round(crop[0] * w), round(crop[1] * h), round(crop[2] * w), round(crop[3] * h)))
    return im


def extract_palette(image, n=6, crop=None):
    """Dominant colours of an image (path or PIL image): median cut + k-means on a downscaled copy.
    Returns {"colors": [{hex, rgb, share, luma}] by share, "luma": stats, "gradient": MM gradient}.
    The gradient lists the colours dark → light, each at the midpoint of its cumulative share, so a
    colorize node fed a uniformly distributed grayscale reproduces the photo's colour shares."""
    from PIL import Image
    n = max(2, min(12, int(n)))
    im = _open_rgb(image, crop) if not isinstance(image, Image.Image) else image.convert("RGB")
    im = im.copy()
    im.thumbnail((PALETTE_SAMPLE, PALETTE_SAMPLE))
    q = im.quantize(colors=n, method=Image.Quantize.MEDIANCUT, kmeans=8)
    pal = q.getpalette()
    total = im.width * im.height
    colors = []
    for count, idx in q.getcolors(n) or []:
        rgb = tuple(pal[3 * idx:3 * idx + 3])
        colors.append({"hex": "#%02x%02x%02x" % rgb, "rgb": list(rgb), "share": round(count / total, 4),
                       "luma": round(_luma(rgb), 3)})
    colors.sort(key=lambda c: -c["share"])
    hist = im.convert("L").histogram()
    mean = sum(i * c for i, c in enumerate(hist)) / total
    std = (sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total) ** 0.5

    def pct(p):
        acc = 0
        for i, c in enumerate(hist):
            acc += c
            if acc >= p * total:
                return round(i / 255, 3)
        return 1.0

    points, acc = [], 0.0
    for c in sorted(colors, key=lambda c: c["luma"]):
        r, g, b = (v / 255 for v in c["rgb"])
        points.append({"pos": round(acc + c["share"] / 2, 4), "r": round(r, 4), "g": round(g, 4), "b": round(b, 4), "a": 1})
        acc += c["share"]
    return {"colors": colors,
            "luma": {"mean": round(mean / 255, 3), "std": round(std / 255, 3), "p05": pct(0.05), "p95": pct(0.95)},
            "gradient": {"type": "Gradient", "interpolation": 1, "points": points}}


def palette_strip(palette, width, height=40, label=None, label_w=150):
    """Swatches dark → light, widths proportional to share, hex on each swatch that fits."""
    from PIL import Image, ImageDraw
    strip = Image.new("RGB", (width, height), (28, 28, 28))
    dr = ImageDraw.Draw(strip)
    x0 = 0
    if label:
        dr.text((6, 4), label, fill=(255, 255, 255), font=_font(13))
        dr.text((6, 21), "luma %.2f ± %.2f" % (palette["luma"]["mean"], palette["luma"]["std"]),
                fill=(190, 190, 190), font=_font(12))
        x0 = label_w
    cols = sorted(palette["colors"], key=lambda c: c["luma"])
    total = sum(c["share"] for c in cols) or 1
    x = x0
    for i, c in enumerate(cols):
        x1 = width if i == len(cols) - 1 else x + round((width - x0) * c["share"] / total)
        dr.rectangle((x, 0, max(x, x1 - 1), height - 1), fill=tuple(c["rgb"]))
        if x1 - x >= 56:
            ink = (0, 0, 0) if c["luma"] > 0.5 else (255, 255, 255)
            dr.text((x + 4, 4), c["hex"], fill=ink, font=_font(12))
            dr.text((x + 4, 21), "%d%%" % round(100 * c["share"]), fill=ink, font=_font(12))
        x = x1
    return strip


def _square(im):
    s = min(im.size)
    l, t = (im.width - s) // 2, (im.height - s) // 2
    return im.crop((l, t, l + s, t + s))


def compare_row(width, preview=None, reference=None, albedo=None, preview_label=None, n_colors=6, lab=22):
    """The top block of a sheet: [reference photo | 3D preview] at `width`, each with a label, then
    palette strips (reference, albedo) when a reference is given. Returns (image, info) or (None, {})."""
    from PIL import Image, ImageDraw
    if preview is None and reference is None:
        return None, {}
    parts = []  # (image, label)
    info = {}
    if reference is not None:
        ref_full = _open_rgb(reference)
        parts.append((_square(ref_full), "reference photo (the target; centre square)"))
    if preview is not None:
        with Image.open(preview) as im:
            parts.append((im.convert("RGB"), preview_label or "3D preview (MM renderer)"))
    h = max(p.height for p, _ in parts) if preview is None else parts[-1][0].height
    scaled = [(p.resize((round(p.width * h / p.height), h)), t) for p, t in parts]
    row_w = sum(p.width for p, _ in scaled)
    row_h = round(h * width / row_w)
    row = Image.new("RGB", (width, lab + row_h), (28, 28, 28))
    dr = ImageDraw.Draw(row)
    x = 0
    for p, t in scaled:
        w = round(p.width * width / row_w)
        row.paste(p.resize((w, row_h)), (x, lab))
        dr.text((x + 6, 4), t, fill=(255, 255, 255), font=_font(14))
        x += w
    blocks = [row]
    if reference is not None:
        ref_pal = extract_palette(ref_full, n_colors)
        info["reference"] = str(reference)
        info["reference_palette"] = [c["hex"] for c in ref_pal["colors"]]
        info["reference_luma"] = ref_pal["luma"]
        blocks.append(palette_strip(ref_pal, width, label="reference palette"))
        if albedo is not None:
            alb_pal = extract_palette(albedo, n_colors)
            info["albedo_palette"] = [c["hex"] for c in alb_pal["colors"]]
            info["albedo_luma"] = alb_pal["luma"]
            blocks.append(palette_strip(alb_pal, width, label="albedo palette"))
    out = Image.new("RGB", (width, sum(b.height for b in blocks)), (28, 28, 28))
    y = 0
    for b in blocks:
        out.paste(b, (0, y))
        y += b.height
    return out, info


def find_reference(directory):
    """agent_runs/<run>/reference.* for an export dir (<iter>/out) or iteration dir (<iter>)."""
    d = Path(directory).resolve()
    for base in (d.parent, d.parent.parent, d):
        hits = sorted(p for p in base.glob(REFERENCE_STEM + ".*") if p.suffix.lower() in IMAGE_SUFFIXES)
        if hits:
            return hits[0]
    return None


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")


def cmd_palette(args):
    res = extract_palette(args.photo, args.colors, _parse_crop(args.crop))
    res = {"photo": str(Path(args.photo).resolve()), **res}
    if not args.no_swatch:
        out = Path(args.swatch) if args.swatch else RUNS_DIR / "palette" / (Path(args.photo).stem + ".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        palette_strip(res, 768, 48, label=Path(args.photo).name[:20]).save(out)
        res["swatch"] = str(out)
    print(_dumps_rows(res, ("colors", "points")))
    return 0


def _dumps_rows(obj, row_keys, indent=1):
    """json.dumps(indent) but lists under `row_keys` print one compact item per line."""
    def enc(o, level):
        pad, inner = " " * (indent * level), " " * (indent * (level + 1))
        if isinstance(o, dict) and o:
            items = []
            for k, v in o.items():
                if k in row_keys and isinstance(v, list) and v:
                    rows = (",\n" + inner + " ").join(json.dumps(x, ensure_ascii=False) for x in v)
                    items.append("%s%s: [\n%s %s\n%s]" % (inner, json.dumps(k), inner, rows, inner))
                else:
                    items.append("%s%s: %s" % (inner, json.dumps(k), enc(v, level + 1)))
            return "{\n" + ",\n".join(items) + "\n" + pad + "}"
        return json.dumps(o, ensure_ascii=False)
    return enc(obj, 0)


def cmd_compare(args):
    from PIL import Image
    if not Path(args.ref).is_file():
        raise SystemExit("mmx compare: no such reference image: %s" % args.ref)
    block, info = compare_row(args.width, args.preview, args.ref, args.albedo)
    sheet = Image.new("RGB", (block.width, block.height), (28, 28, 28))
    sheet.paste(block, (0, 0))
    out = Path(args.out) if args.out else Path(args.preview).with_name(Path(args.preview).stem + "_vs_ref.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(json.dumps({"compare": str(out), **info}, indent=1))
    return 0


def make_sheet(directory, out=None, tile=384, cols=4, title=None, preview=None, preview_label=None,
               reference=None):
    """Write a labeled contact sheet of every map in `directory`, with the 3D preview (`preview`, or
    found by find_preview) as a full-width top row; with a `reference` photo (or one found by
    find_reference) the top row is [reference | preview] followed by reference/albedo palette strips.
    Returns {"sheet", "tiles", "sources", "preview", "reference", ...palette info}."""
    from PIL import Image, ImageDraw
    directory = Path(directory)
    preview = Path(preview) if preview else find_preview(directory)
    reference = Path(reference) if reference else find_reference(directory)
    maps = classify_maps(directory)
    if not maps:
        raise SystemExit("mmx sheet: no PNG maps in %s" % directory)
    imgs = split_maps(maps)
    tiles = {}
    if "albedo" in imgs and "normal" in imgs:
        lit = lit_preview(imgs["albedo"], imgs["normal"], imgs.get("ao"))
        tiles["lit"] = lit
        t2 = Image.new("RGB", (lit.width * 2, lit.height * 2))
        for x in (0, lit.width):
            for y in (0, lit.height):
                t2.paste(lit, (x, y))
        tiles["lit tiled 2x2"] = t2
    tiles.update(imgs)
    order = [k for k in SHEET_ORDER if k in tiles] + sorted(k for k in tiles if k not in SHEET_ORDER)

    head, lab = 30, 22
    rows = (len(order) + cols - 1) // cols
    top, ref_info = compare_row(cols * tile, preview, reference, imgs.get("albedo"), preview_label, lab=lab)
    top_h = top.height if top is not None else 0
    sheet = Image.new("RGB", (cols * tile, head + top_h + rows * (tile + lab)), (28, 28, 28))
    dr = ImageDraw.Draw(sheet)
    dr.text((6, 6), title or str(directory), fill=(255, 255, 255), font=_font(16))
    if top is not None:
        sheet.paste(top, (0, head))
    info = []
    for i, k in enumerate(order):
        im = tiles[k]
        x, y = (i % cols) * tile, head + top_h + (i // cols) * (tile + lab)
        sheet.paste(im.convert("RGB").resize((tile, tile)), (x, y + lab))
        text = k
        if im.mode == "L":  # numeric range helps spot flat/clipped maps
            lo, hi = im.getextrema()
            mean = sum(i * c for i, c in enumerate(im.histogram())) / (im.width * im.height)
            text += "  min %.2f  mean %.2f  max %.2f" % (lo / 255, mean / 255, hi / 255)
        dr.text((x + 6, y + 4), text, fill=(255, 255, 255), font=_font(14))
        info.append(text)
    out = Path(out) if out else directory / "sheet.png"
    sheet.save(out)
    return {"sheet": str(out), "tiles": info, "sources": {k: p.name for k, p in maps.items()},
            "preview": str(preview) if preview is not None else None,
            "reference": str(reference) if reference is not None else None, **ref_info}


def cmd_sheet(args):
    res = make_sheet(args.dir, args.out, preview=args.preview, reference=args.ref)
    print(json.dumps(res, indent=1))
    return 0


# ---------------------------------------------------------------------------
# run / wait
# ---------------------------------------------------------------------------


def next_iter_dir(run_name, runs_dir=None):
    """Create and return agent_runs/<run>/iter_NNN (next free number, from 001)."""
    base = Path(runs_dir or RUNS_DIR) / run_name
    base.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for p in base.iterdir() if (m := re.fullmatch(r"iter_(\d+)", p.name))]
    n = max(nums, default=0) + 1
    while True:
        d = base / ("iter_%03d" % n)
        try:
            d.mkdir()  # atomic claim
            return d
        except FileExistsError:
            n += 1


RUN_NAME_RE = re.compile(r"[\w.-]+(/[\w.-]+)*")


def set_run_reference(run_dir, photo):
    """Copy `photo` to <run_dir>/reference.<ext> (replacing an older one); later iterations find it."""
    import shutil
    photo = Path(photo)
    if not photo.is_file():
        raise SystemExit("mmx run: no such reference image: %s" % photo)
    if photo.suffix.lower() not in IMAGE_SUFFIXES:
        raise SystemExit("mmx run: --ref must be an image (%s)" % ", ".join(IMAGE_SUFFIXES))
    for old in Path(run_dir).glob(REFERENCE_STEM + ".*"):
        old.unlink()
    dest = Path(run_dir) / (REFERENCE_STEM + photo.suffix.lower())
    shutil.copy2(photo, dest)
    return dest


def run_iteration(ptex, run_name, target=None, cfg=None, timeout=None, runs_dir=None, note=None, size=None,
                  preview=None, reference=None):
    import shutil
    import time
    if not RUN_NAME_RE.fullmatch(run_name) or any(c in (".", "..") for c in run_name.split("/")):
        raise SystemExit("mmx run: --run-name may only use letters, digits, '_', '-', '.' and '/' "
                         "between parts (e.g. 1.3/desert)")
    ptex = Path(ptex).resolve()
    d = next_iter_dir(run_name, runs_dir)
    if reference:
        set_run_reference(d.parent, reference)
    _write_json(d / STATUS_NAME, {"state": "running", "started": time.time(), "ptex": str(ptex)})
    copy = d / ptex.name
    shutil.copy2(ptex, copy)
    if note:
        (d / "note.md").write_text(note + "\n")
    res = run_export(copy, d / "out", target, cfg, timeout, size=size)
    res["iter_dir"] = str(d)
    cfg = cfg or load_config()
    preview = cfg.get("preview_3d", True) if preview is None else preview
    label = None
    if res["ok"] and preview and cfg["mode"] == "source":
        p = render_preview(copy, d / PREVIEW_NAME, cfg=cfg, timeout=timeout)
        res["preview"] = {k: p.get(k) for k in ("ok", "file", "meshes", "env", "seconds", "errors")}
        if p["ok"]:
            label = "3D preview: %s, %s environment (the image to judge)" % (" + ".join(p.get("meshes") or []), p.get("env"))
        else:  # the maps are still useful: keep the iteration, flag the missing preview
            res.setdefault("warnings", []).append("3D preview failed: %s" % "; ".join(p["errors"]))
    if res["ok"]:
        try:
            sh = make_sheet(d / "out", d / "sheet.png", title="%s / %s  (%s)" % (run_name, d.name, ptex.name),
                            preview=(d / PREVIEW_NAME) if label else None, preview_label=label,
                            reference=find_reference(d))
            res["sheet"] = sh["sheet"]
            for k in ("reference", "reference_palette", "albedo_palette", "reference_luma", "albedo_luma"):
                if sh.get(k) is not None:
                    res[k] = sh[k]
        except Exception as e:  # keep the export result even if the sheet fails
            res["ok"] = False
            res["error"] = "sheet failed: %s" % e
    _write_json(d / RESULT_NAME, res)
    _write_json(d / STATUS_NAME, {"state": "done", "finished": time.time(), "ok": res["ok"]})
    return res


def cmd_run(args):
    res = run_iteration(args.ptex, args.run_name, args.target, load_config(args.config), args.timeout,
                        note=args.note, size=args.size, preview=False if args.no_preview else None,
                        reference=args.ref)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 2


def wait_for_result(path=None, run_name=None, timeout=300.0, fresh=60.0, runs_dir=None, poll=0.5):
    """Block until a result appears; for use from a shell that can't launch the app itself.
    path: an export out dir or iter dir. run_name: the newest iteration that is running, newer than
    the call, or finished within `fresh` seconds before the call."""
    import time
    start = time.time()
    while True:
        if path is not None:
            cand = [Path(path)]
        else:
            base = Path(runs_dir or RUNS_DIR) / run_name
            cand = sorted(base.glob("iter_[0-9]*"), key=lambda p: p.name, reverse=True)[:1] if base.is_dir() else []
        for d in cand:
            r = d / RESULT_NAME
            if r.exists() and (path is not None or r.stat().st_mtime >= start - fresh):
                st = d / STATUS_NAME
                if st.exists() and json.loads(st.read_text()).get("state") == "running":
                    continue  # export's result is in; run is still making the sheet
                return json.loads(r.read_text())
        if time.time() - start > timeout:
            return {"ok": False, "error": "mmx wait: no result after %ss" % timeout,
                    "hint": "did the command start in the Terminal panel? check its output"}
        time.sleep(poll)


def to_unity(ptex, project, name, target=None, size=None, verify=False, editor=None, cfg=None, timeout=None,
             verify_timeout=None, skip_validate=False):
    """Export `ptex` into <project>/Assets/Materials/Generated/<name>/ (see unity_handoff.py).
    Returns a JSON-able summary; staging + logs in agent_runs/to-unity/<name>/."""
    import unity_handoff as uh
    cfg = cfg or load_config()
    rv = {"ok": False, "stage": "project", "ptex": str(Path(ptex).resolve()), "name": name}
    try:
        uh.check_name(name)
        project = uh.check_project(project or cfg["unity"].get("project") or "")
        rv["project"] = str(project)
        rv["unity_version"] = uh.project_version(project)
        rv["stage"] = "pipeline"
        if target:
            rv["target"], rv["target_source"] = target, "--target"
        else:
            det = uh.detect_pipeline(project)
            rv["pipeline"] = {k: det[k] for k in ("pipeline", "source", "assets", "packages")}
            rv["target"], rv["target_source"] = det["target"], "detected"
    except uh.HandoffError as e:
        rv["error"] = str(e)
        return rv
    folder = (uh.GENERATED_DIR / name).as_posix()
    dest = project / folder
    work = RUNS_DIR / "to-unity" / name
    stage = work / "export"
    if stage.exists():
        shutil.rmtree(stage)
    rv.update(stage="export", folder=folder, dest=str(dest), work_dir=str(work))
    exp = run_export(ptex, stage, rv["target"], cfg, timeout, skip_validate=skip_validate, size=size,
                     output_name=name)
    rv["export"] = {k: exp.get(k) for k in ("ok", "stage", "error", "seconds", "warnings", "log_errors", "mm",
                                            "validation", "missing") if exp.get(k) not in (None, [], {})}
    if not exp["ok"]:
        rv["error"] = "export failed: %s" % exp.get("error")
        return rv
    rv["stage"] = "copy"
    try:
        rv.update(uh.sync_into_project(stage, dest, name))
    except (uh.HandoffError, OSError) as e:
        rv["error"] = "copy into the project failed: %s" % e
        return rv
    rv["material"] = "%s/%s.mat" % (folder, name)
    open_pids = uh.editor_processes(project)
    if open_pids:
        rv["editor_open"] = open_pids
    if verify:
        rv["stage"] = "verify"
        editor = editor or cfg["unity"].get("editor")
        v = uh.verify(editor or "", project, folder, work, verify_timeout or cfg["unity"]["verify_timeout"])
        rv["verify"] = v
        if not v["ok"]:
            rv["error"] = v.get("error", "verification failed")
            return rv
    rv.update(ok=True, stage="done")
    return rv


def cmd_to_unity(args):
    res = to_unity(args.ptex, args.project, args.name, args.target, args.size, args.verify, args.unity,
                   load_config(args.config), args.timeout, args.verify_timeout, args.no_validate)
    if RUNS_DIR.is_dir() and res.get("work_dir"):
        Path(res["work_dir"]).mkdir(parents=True, exist_ok=True)
        _write_json(Path(res["work_dir"]) / "to_unity_result.json", res)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


def cmd_wait(args):
    if bool(args.dir) == bool(args.run_name):
        raise SystemExit("mmx wait: give a directory or --run-name (not both)")
    res = wait_for_result(args.dir, args.run_name, args.timeout, args.fresh)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 2


def _ensure_pillow(cmd):
    """sheet/run/palette/compare need Pillow: re-exec under agent_tools/.venv if the current python lacks it."""
    import os
    if cmd not in ("sheet", "run", "palette", "compare"):  # preview/node-preview need no Pillow
        return
    try:
        import PIL  # noqa: F401
    except ImportError:
        if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve():
            os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])
        raise SystemExit("mmx %s needs Pillow: python3 -m venv agent_tools/.venv && "
                         "agent_tools/.venv/bin/pip install pillow" % cmd)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mmx", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("catalog", help="build agent_tools/catalog.json and agent_docs/NODES.md")
    p.add_argument("--nodes-dir", action="append", help="extra .mmg dir (e.g. the release app's nodes/); overrides repo defs")
    p.add_argument("--static", action="store_true", help="parse .mmg files in Python only (no engine)")
    p.add_argument("--config", help="config file (default agent_tools/mmx.toml or $MMX_CONFIG)")
    p.set_defaults(fn=cmd_catalog)
    p = sub.add_parser("validate", help="validate a .ptex file (Python checks, then the engine's); JSON result, exit 0/1")
    p.add_argument("ptex")
    p.add_argument("--fast", action="store_true", help="Python checks only (no Godot launch, no shader compile)")
    p.add_argument("--timeout", type=float, help="seconds before the engine check is killed (default from mmx.toml)")
    p.add_argument("--config", help="config file (default agent_tools/mmx.toml or $MMX_CONFIG)")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("node", help="print one node type's catalog entry")
    p.add_argument("type")
    p.set_defaults(fn=cmd_node)

    def export_opts(p):
        p.add_argument("--target", help="export target (default from mmx.toml: Unity/URP)")
        p.add_argument("--timeout", type=float, help="seconds before the app is killed (default from mmx.toml)")
        p.add_argument("--size", type=int, help="texture size in pixels, e.g. 512 for fast drafts "
                       "(source mode only; default: the graph's own size)")
        p.add_argument("--config", help="config file (default agent_tools/mmx.toml or $MMX_CONFIG)")

    p = sub.add_parser("export", help="validate + export a .ptex with the MM binary; JSON summary, exit 0/1/2")
    p.add_argument("ptex")
    p.add_argument("--out", required=True, help="output dir (created)")
    p.add_argument("--keep-meta", action="store_true", help="keep existing .meta files (Unity GUIDs)")
    p.add_argument("--no-validate", action="store_true", help="skip mmx validate")
    export_opts(p)
    p.set_defaults(fn=cmd_export)
    p = sub.add_parser("preview", help="lit 3D preview PNG of a .ptex (engine, source mode); JSON, exit 0/1")
    p.add_argument("ptex")
    p.add_argument("--mesh", help="sphere, plane, cube or several joined with + (default from mmx.toml: sphere+plane)")
    p.add_argument("--env", help="environment name or index (default from mmx.toml: Studio)")
    p.add_argument("--size", type=int, help="pixels per view (default from mmx.toml: 512)")
    p.add_argument("--out", help="output PNG (default agent_runs/preview/<ptex stem>.png)")
    p.add_argument("--timeout", type=float, help="seconds before Godot is killed (default from mmx.toml)")
    p.add_argument("--config", help="config file (default agent_tools/mmx.toml or $MMX_CONFIG)")
    p.set_defaults(fn=cmd_preview)
    p = sub.add_parser("node-preview", help="render one output of one node to a PNG (engine, source mode); JSON, exit 0/1")
    p.add_argument("ptex")
    p.add_argument("--node", required=True, help="node name; a/b for a node inside sub-graph a")
    p.add_argument("--port", type=int, default=0, help="output index (default 0; the result lists all outputs)")
    p.add_argument("--size", type=int, default=512, help="image size in pixels (16..8192, default 512)")
    p.add_argument("--out", help="output PNG (default agent_runs/node_preview/<ptex stem>/<node>_p<port>.png)")
    p.add_argument("--timeout", type=float, help="seconds before Godot is killed (default from mmx.toml)")
    p.add_argument("--config", help="config file (default agent_tools/mmx.toml or $MMX_CONFIG)")
    p.set_defaults(fn=cmd_node_preview)
    p = sub.add_parser("sheet", help="labeled contact-sheet PNG of an export dir")
    p.add_argument("dir")
    p.add_argument("--out", help="output PNG (default <dir>/sheet.png)")
    p.add_argument("--preview", help="3D preview PNG for the top row (default <dir>/preview_3d.png or <dir>/../preview_3d.png)")
    p.add_argument("--ref", help="reference photo shown left of the 3D preview, + palette strips "
                   "(default: reference.* of the run, see run --ref)")
    p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("run", help="one iteration: agent_runs/<run>/iter_NNN/ with ptex copy, out/, sheet.png")
    p.add_argument("ptex")
    p.add_argument("--run-name", required=True, help="agent_runs/<name>/; '/' nests, e.g. 1.3/desert")
    p.add_argument("--note", help="text saved as note.md in the iteration dir (what changed and why)")
    p.add_argument("--no-preview", action="store_true", help="skip the 3D preview (iter_NNN/preview_3d.png)")
    p.add_argument("--ref", help="reference photo (the target): copied to agent_runs/<run>/reference.<ext> and shown "
                   "beside the 3D preview on this and every later sheet of the run")
    export_opts(p)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("palette", help="dominant colours of a photo (hex + share), a ready MM gradient, swatch PNG")
    p.add_argument("photo")
    p.add_argument("-n", "--colors", type=int, default=6, help="number of colours, 2..12 (default 6)")
    p.add_argument("--crop", help="analyse only this part: L,T,R,B as fractions, e.g. 0.2,0.2,0.8,0.8")
    p.add_argument("--swatch", help="swatch PNG (default agent_runs/palette/<photo stem>.png)")
    p.add_argument("--no-swatch", action="store_true")
    p.set_defaults(fn=cmd_palette)
    p = sub.add_parser("compare", help="[reference photo | 3D preview] + palette strips in one PNG (e.g. for MCP previews)")
    p.add_argument("preview", help="3D preview PNG (mmx preview / MCP render_preview output)")
    p.add_argument("--ref", required=True, help="reference photo")
    p.add_argument("--albedo", help="albedo PNG: adds its palette strip under the reference's")
    p.add_argument("--width", type=int, default=1536)
    p.add_argument("--out", help="output PNG (default <preview stem>_vs_ref.png next to the preview)")
    p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("to-unity", help="export into <project>/Assets/Materials/Generated/<Name>/ with the project's "
                       "pipeline target; JSON, exit 0/1")
    p.add_argument("ptex")
    p.add_argument("--project", help="Unity project root (default [unity] project in mmx.toml)")
    p.add_argument("--name", required=True, help="material name: folder, .mat and texture prefix (letters, digits, _ -)")
    p.add_argument("--target", help="override the detected target (Unity/URP, Unity/HDRP, Unity/3D)")
    p.add_argument("--size", type=int, help="texture size in pixels (default: the graph's own size)")
    p.add_argument("--no-validate", action="store_true", help="skip mmx validate")
    p.add_argument("--verify", action="store_true", help="then run Unity -batchmode with MMAgentVerify "
                   "(the editor must be closed; installs Assets/Editor/MaterialMakerAgent/MMAgentVerify.cs)")
    p.add_argument("--unity", help="Unity executable (default [unity] editor in mmx.toml)")
    p.add_argument("--verify-timeout", type=float, help="seconds for the Unity run (default 900)")
    p.add_argument("--timeout", type=float, help="seconds before the MM export is killed (default from mmx.toml)")
    p.add_argument("--config", help="config file (default agent_tools/mmx.toml or $MMX_CONFIG)")
    p.set_defaults(fn=cmd_to_unity)
    p = sub.add_parser("wait", help="wait for an export/run started elsewhere (Terminal panel); print its result")
    p.add_argument("dir", nargs="?", help="export out dir or iteration dir")
    p.add_argument("--run-name", help="wait for this run's newest iteration")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--fresh", type=float, default=60.0,
                   help="with --run-name: accept a result finished up to this many seconds before the call")
    p.set_defaults(fn=cmd_wait)
    args = ap.parse_args(argv)
    if argv is None:
        _ensure_pillow(args.cmd)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
