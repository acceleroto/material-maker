#!/usr/bin/env python3
"""mcp_server: stdio MCP server for Material Maker (stdlib only).

Wraps the engine server (`Godot --path <repo> --serve`, cli_serve.gd) through mm_client.MMClient: one tool per
server method, plus `batch` (several methods in one call) and `restart`. Render tools return the PNG as an MCP
image so the agent sees it directly.

    python3 agent_tools/mcp_server.py            # serve MCP over stdin/stdout (what Claude Code / Codex launch)
    python3 agent_tools/mcp_server.py --check    # start the engine once, print its info, exit 0/1
    python3 agent_tools/mcp_server.py --list-tools

The engine starts on the first tool call that needs it (~1.3 s) and stays up; a timeout or crash kills it and
the next call starts a fresh one (the loaded graph and unsaved edits are lost). Relative paths resolve against
the repo root; omitted output paths go to agent_runs/mcp/<graph stem>/. Engine stderr: agent_runs/mcp/engine.log.
MCP transport: JSON-RPC 2.0, one message per line; nothing but MCP messages is written to stdout.
"""

import argparse
import atexit
import base64
import json
import shlex
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmx  # noqa: E402
from mm_client import MMClient, MMError  # noqa: E402

SERVER_NAME = "material-maker"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]   # newest first
OUT_ROOT = mmx.RUNS_DIR / "mcp"

INSTRUCTIONS = """Material Maker engine: edit a procedural material graph (.ptex) in memory, see it rendered, export maps.
Loop: load (closest example in material_maker/examples/) -> render_preview (lit 3D sphere+plane: the primary image
to judge) -> 1-2 edits (set_param / add_node / connect) -> render_preview again; render_output shows one node's
output to debug; validate before export; save to keep the edited .ptex. Use batch for several edits + a render in
one call. Node types and parameters: list_nodes / describe_node, or agent_docs/NODES.md. Material inputs are
depth (not height). Paths may be relative to the repo root; output paths are optional."""

# Any JSON value (parameter values: numbers, enum names, colours, gradient objects...)
ANY = {"type": ["number", "integer", "string", "boolean", "object", "array", "null"]}
NODE = {"type": "string", "description": "Node name as in get_graph, e.g. \"Perlin\"; \"graph/Bricks\" for a node inside sub-graph \"graph\"."}
PORT = {"type": "integer", "minimum": 0, "default": 0}
SIZE = {"type": "integer", "minimum": 16, "maximum": 8192, "description": "Image size in pixels (default 512)."}


def _obj(props, required=(), **extra):
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    schema.update(extra)
    return schema


# name -> (description, input schema, annotations)
TOOLS = {
    "load": (
        "Load a .ptex material graph into the engine (replaces the current graph and any unsaved edits). "
        "Start from the closest example in material_maker/examples/ rather than an empty graph. "
        "Returns the node count, the Material node and the image size.",
        _obj({"path": {"type": "string", "description": "Path to a .ptex file (absolute, or relative to the repo root)."}}, ["path"]),
        {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}),
    "save": (
        "Write the in-memory graph to a .ptex file (as the editor saves it). Default path: the loaded file. "
        "Don't overwrite files in material_maker/examples/: pass a path under agent_runs/.",
        _obj({"path": {"type": "string", "description": "Destination .ptex (absolute or repo-relative); default the loaded file."}}),
        {"readOnlyHint": False, "destructiveHint": True}),
    "list_nodes": (
        "Search the node library: add-node menu items (name, category, type) and all node types. Use query to filter "
        "(e.g. \"noise\", \"blend\", \"bricks\"); without filters the list is long.",
        _obj({"query": {"type": "string", "description": "Case-insensitive substring of the item name or type."},
              "category": {"type": "string", "description": "Menu category prefix, e.g. \"Noise\", \"Filter\", \"Simple\"."}}),
        {"readOnlyHint": True}),
    "describe_node": (
        "Describe a node type (inputs, outputs, parameters with types/ranges/defaults) or, with node, a node of the "
        "loaded graph (current parameter values, ports and connections). Give exactly one of type / node.",
        _obj({"type": {"type": "string", "description": "Node type, e.g. \"perlin\", \"blend2\", \"colorize\"."}, "node": NODE}),
        {"readOnlyHint": True}),
    "add_node": (
        "Add a node of a type to the graph (or inside a sub-graph via parent). The name is deduplicated "
        "(perlin -> perlin_2): use the returned name. Returns its ports and parameter values.",
        _obj({"type": {"type": "string", "description": "Node type, e.g. \"perlin\" (see list_nodes)."},
              "name": {"type": "string", "description": "Preferred node name (default: the type)."},
              "parent": {"type": "string", "description": "Sub-graph node to add into (default: top level)."},
              "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                           "description": "[x, y] in the graph editor (cosmetic)."},
              "parameters": {"type": "object", "additionalProperties": ANY, "description": "Initial parameter values {name: value}."}},
             ["type"]),
        {"readOnlyHint": False, "destructiveHint": False}),
    "remove_node": (
        "Delete a node and its connections (the Material node cannot be deleted).",
        _obj({"node": NODE}, ["node"]),
        {"readOnlyHint": False, "destructiveHint": True}),
    "connect": (
        "Connect an output port to an input port (ports are 0-based; port types are checked; an input takes one "
        "connection, so an existing one is replaced and returned as `replaced`). Loops are rejected.",
        _obj({"from": NODE, "from_port": PORT, "to": NODE, "to_port": PORT}, ["from", "to"]),
        {"readOnlyHint": False, "destructiveHint": False}),
    "disconnect": (
        "Remove the connection into an input port (optionally only if it comes from from/from_port). "
        "An unconnected input reads as 0.",
        _obj({"to": NODE, "to_port": PORT, "from": NODE, "from_port": PORT}, ["to"]),
        {"readOnlyHint": False, "destructiveHint": True}),
    "set_param": (
        "Set node parameters, either name+value or params={name: value, ...}. Values are checked against the "
        "definition: float = number or a $-expression (\"$time*0.1\"); enum = index or value name; boolean; "
        "color = {r,g,b,a}, [r,g,b(,a)] or \"#rrggbb\"; gradient/curve/... = the object as in get_graph full=true. "
        "Returns old and new values; out-of-slider floats are set with a warning.",
        _obj({"node": NODE, "name": {"type": "string"}, "value": ANY,
              "params": {"type": "object", "additionalProperties": ANY, "description": "Several {name: value} at once."}},
             ["node"]),
        {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}),
    "get_graph": (
        "The loaded graph: compact nodes [{name, type, parameters}] and connections; node = a sub-graph's contents; "
        "full=true returns the complete .ptex dict (large).",
        _obj({"node": {"type": "string", "description": "Sub-graph node to list (default: top level)."},
              "full": {"type": "boolean", "default": False}}),
        {"readOnlyHint": True}),
    "validate": (
        "Check the graph like `mmx validate`: unknown types, bad connections, then a shader compile of every node "
        "output. Run before export; a broken $-expression only shows up here.",
        _obj({}),
        {"readOnlyHint": True}),
    "render_output": (
        "Render one node output to a PNG and return the image (debug a node: what does this noise/mask look like?). "
        "Note: a normal_map node's raw output is MM's internal format (blue ~0.1, red flipped vs the Unity export).",
        _obj({"node": NODE, "port": PORT, "size": SIZE,
              "output": {"type": "string", "description": "PNG path (default agent_runs/mcp/<graph>/node_<node>_p<port>_NNN.png)."},
              "return_image": {"type": "boolean", "default": True}},
             ["node"]),
        {"readOnlyHint": False, "destructiveHint": False}),
    "render_preview": (
        "Render the material lit in 3D (Material node; default a sphere and a plane side by side, Studio environment) "
        "and return the image. This is the primary image to judge a material by; keep mesh/env/size fixed across "
        "iterations so images stay comparable.",
        _obj({"mesh": {"type": "string", "description": "sphere, plane, cube, or a+b for several views (default sphere+plane)."},
              "env": {"type": "string", "description": "Environment name or index (default Studio)."},
              "size": {"type": "integer", "minimum": 64, "maximum": 2048, "description": "Pixels per view (default 512)."},
              "output": {"type": "string", "description": "PNG path (default agent_runs/mcp/<graph>/preview_NNN.png)."},
              "return_image": {"type": "boolean", "default": True}}),
        {"readOnlyHint": False, "destructiveHint": False}),
    "export": (
        "Export the material's texture maps (+ .mat for Unity) for an engine target. Stale <prefix>.* / <prefix>_* "
        "files in output_dir are deleted first. Returns the written files.",
        _obj({"output_dir": {"type": "string", "description": "Directory (default agent_runs/mcp/<graph>/export)."},
              "target": {"type": "string", "description": "Export target, exact name (default from mmx.toml: Unity/URP)."},
              "size": {"type": "integer", "minimum": 0, "description": "Texture size in pixels; 0 = the graph's own size (default)."},
              "prefix": {"type": "string", "description": "File name stem (default: the graph's file name)."},
              "overwrite": {"type": "boolean", "default": True}}),
        {"readOnlyHint": False, "destructiveHint": False}),
    "batch": (
        "Run several operations in order in one call; stops at the first failure (later steps may depend on it). "
        "Each op is {\"method\": <tool name except batch/restart>, \"params\": {...}} with the same params as that "
        "tool. Images from render steps are returned (set return_image false in a step to skip one). "
        "Example: set_param, set_param, render_preview.",
        _obj({"ops": {"type": "array", "minItems": 1, "items": _obj(
            {"method": {"type": "string"}, "params": {"type": "object"}}, ["method"])}}, ["ops"]),
        {"readOnlyHint": False, "destructiveHint": True}),
    "restart": (
        "Kill and restart the engine (after a hang or an internal error). The loaded graph and unsaved edits are lost.",
        _obj({}),
        {"readOnlyHint": False, "destructiveHint": True}),
}


class ToolError(Exception):
    pass


class MaterialMakerTools:
    """Tool implementations on top of one lazily started MMClient."""

    def __init__(self, cfg=None, engine_command=None, timeout=None, log_path=None, out_root=None):
        self.cfg = cfg or mmx.load_config()
        self.out_root = Path(out_root) if out_root else OUT_ROOT
        self.engine_command = engine_command
        self.timeout = timeout or float(self.cfg.get("timeout", 180))
        self.log_path = Path(log_path) if log_path else self.out_root / "engine.log"
        self.mm = None
        self.graph_path = None
        self.counters = {}

    # -- engine lifecycle --------------------------------------------------

    def engine(self):
        if self.mm is not None and self.mm.proc.poll() is not None:
            self._drop()
        if self.mm is None:
            self.mm = MMClient(self.cfg, log_path=self.log_path, timeout=self.timeout, command=self.engine_command)
        return self.mm

    def _drop(self):
        if self.mm is not None:
            try:
                self.mm.kill()
                self.mm.close()   # closes the log; the process is already gone
            except Exception:
                pass
        self.mm = None
        self.graph_path = None

    def close(self):
        if self.mm is not None:
            try:
                self.mm.close(timeout=5)
            except Exception:
                self.mm.kill()
            self.mm = None

    def call(self, method, **params):
        mm = self.engine()
        try:
            result = mm.call(method, **params)
        except MMError as e:
            if e.code in ("timeout", "server_died"):
                self._drop()
                raise ToolError("%s: %s. The engine is gone; the next call starts a new one (load the graph again, "
                                "unsaved edits are lost). Engine log: %s" % (e.code, e.message, _rel(self.log_path)))
            hint = HINTS.get(e.code, "")
            if hint and hint in e.message:
                hint = ""
            raise ToolError("%s: %s%s" % (e.code, e.message, (" (" + hint + ")") if hint else ""))
        return result, list(mm.last_warnings)

    # -- paths -------------------------------------------------------------

    def _out_dir(self):
        stem = self.graph_path.stem if self.graph_path else "untitled"
        return self.out_root / stem

    def _next_png(self, base):
        d = self._out_dir()
        key = (str(d), base)
        n = self.counters.get(key)
        if n is None:   # continue after files left by an earlier session
            n = max((int(p.stem.rsplit("_", 1)[1]) for p in d.glob(base + "_[0-9][0-9][0-9].png")
                     if p.stem.rsplit("_", 1)[1].isdigit()), default=0)
        n += 1
        self.counters[key] = n
        return d / ("%s_%03d.png" % (base, n))

    # -- tools -------------------------------------------------------------

    def run(self, name, args):
        """Returns (result dict, warnings, image paths to return)."""
        args = dict(args or {})
        if name == "batch":
            raise ToolError("bad_params: batch cannot be nested")
        fn = getattr(self, "t_" + name, None)
        if fn is None or name not in TOOLS:
            raise ToolError("unknown_tool: %s (tools: %s)" % (name, ", ".join(TOOLS)))
        _check_args(name, args)
        return fn(**args)

    def t_load(self, path):
        p = _abs(path)
        if not p.is_file():
            raise ToolError("load_failed: no such file %s" % p)
        result, w = self.call("load", path=str(p))
        self.graph_path = p
        return result, w, []

    def t_save(self, path=None):
        result, w = self.call("save", **({"path": str(_abs(path))} if path else {}))
        if path:
            self.graph_path = _abs(path)
        return result, w, []

    def t_list_nodes(self, query=None, category=None):
        result, w = self.call("list_nodes", **_opt(query=query, category=category))
        return result, w, []

    def t_describe_node(self, type=None, node=None):
        if (type is None) == (node is None):
            raise ToolError("bad_params: give exactly one of type / node")
        result, w = self.call("describe_node", **_opt(type=type, node=node))
        return result, w, []

    def t_add_node(self, type, name=None, parent=None, position=None, parameters=None):
        result, w = self.call("add_node", type=type, **_opt(name=name, parent=parent, position=position, parameters=parameters))
        return result, w, []

    def t_remove_node(self, node):
        result, w = self.call("remove_node", node=node)
        return result, w, []

    def t_connect(self, to, from_port=0, to_port=0, **kw):
        result, w = self.call("connect", **{"from": kw["from"], "from_port": from_port, "to": to, "to_port": to_port})
        return result, w, []

    def t_disconnect(self, to, to_port=0, from_port=None, **kw):
        result, w = self.call("disconnect", to=to, to_port=to_port, **_opt(**{"from": kw.get("from"), "from_port": from_port}))
        return result, w, []

    def t_set_param(self, node, name=None, value=None, params=None):
        if params is not None and name is not None:
            raise ToolError("bad_params: give name+value or params, not both")
        if params is None and name is None:
            raise ToolError("bad_params: give name+value or params")
        if params is not None:
            result, w = self.call("set_param", node=node, params=params)
        else:
            result, w = self.call("set_param", node=node, name=name, value=value)
        return result, w, []

    def t_get_graph(self, node=None, full=False):
        result, w = self.call("get_graph", **_opt(node=node, full=full or None))
        return result, w, []

    def t_validate(self):
        result, w = self.call("validate")
        return result, w, []

    def t_render_output(self, node, port=0, size=None, output=None, return_image=True):
        out = _abs(output) if output else self._next_png("node_%s_p%d" % (_safe(node), port))
        out.parent.mkdir(parents=True, exist_ok=True)
        result, w = self.call("render_output", node=node, output=str(out), port=port, **_opt(size=size))
        return result, w, [out] if return_image else []

    def t_render_preview(self, mesh=None, env=None, size=None, output=None, return_image=True):
        out = _abs(output) if output else self._next_png("preview")
        out.parent.mkdir(parents=True, exist_ok=True)
        result, w = self.call("render_preview", output=str(out), mesh=mesh or self.cfg["preview_mesh"],
                              env=str(env or self.cfg["preview_env"]), size=int(size or self.cfg["preview_size"]))
        return result, w, [out] if return_image else []

    def t_export(self, output_dir=None, target=None, size=None, prefix=None, overwrite=True):
        out = _abs(output_dir) if output_dir else self._out_dir() / "export"
        out.mkdir(parents=True, exist_ok=True)
        if prefix is None and self.graph_path is not None:
            prefix = self.graph_path.stem
        result, w = self.call("export", output_dir=str(out), target=target or self.cfg["target"], overwrite=overwrite,
                              **_opt(size=size, prefix=prefix))
        return result, w, []

    def t_restart(self):
        self._drop()
        mm = self.engine()
        return {"restarted": True, "start_seconds": mm.start_seconds, "engine": mm.info}, [], []

    def batch(self, ops):
        """Returns (steps, warnings, images, error or None)."""
        steps, warnings, images = [], [], []
        for i, op in enumerate(ops):
            method = op.get("method") if isinstance(op, dict) else None
            if method in ("batch", None) or method not in TOOLS:
                return steps, warnings, images, "op %d: unknown method %r" % (i, method)
            try:
                result, w, imgs = self.run(method, op.get("params") or {})
            except ToolError as e:
                return steps, warnings, images, "op %d (%s) failed: %s" % (i, method, e)
            step = {"index": i, "method": method, "ok": True, "result": result}
            if w:
                step["warnings"] = w
                warnings.extend("op %d: %s" % (i, x) for x in w)
            steps.append(step)
            images.extend(imgs)
        return steps, warnings, images, None


HINTS = {
    "no_graph": "call load first",
    "unknown_node": "see get_graph for node names",
    "unknown_type": "see list_nodes",
    "unknown_parameter": "see describe_node for parameter names",
    "bad_port": "see describe_node for the node's ports",
    "internal": "a script error aborted the method; see the engine log, restart if later calls misbehave",
}


def _check_args(name, args):
    """Reject unknown keys and missing required ones before they reach the engine."""
    schema = TOOLS[name][1]
    unknown = sorted(set(args) - set(schema["properties"]))
    if unknown:
        raise ToolError("bad_params: %s does not take %s (takes: %s)" % (name, ", ".join(unknown),
                        ", ".join(schema["properties"]) or "nothing"))
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise ToolError("bad_params: %s needs %s" % (name, ", ".join(missing)))


def _abs(path):
    p = Path(path).expanduser()
    return (p if p.is_absolute() else mmx.REPO / p).resolve()


def _rel(p):
    p = Path(p)
    return str(p.relative_to(mmx.REPO)) if p.is_relative_to(mmx.REPO) else str(p)


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _opt(**kw):
    return {k: v for k, v in kw.items() if v is not None}


def _image_content(path):
    data = Path(path).read_bytes()
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": "image/png"}


# ---------------------------------------------------------------------------
# MCP protocol (JSON-RPC 2.0 over stdio, newline-delimited)
# ---------------------------------------------------------------------------


class MCPServer:
    def __init__(self, tools, out=None):
        self.tools = tools
        self.out = out or sys.stdout

    def send(self, msg):
        self.out.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.out.flush()

    def serve(self, inp=None):
        for line in inp or sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                continue
            for m in (msg if isinstance(msg, list) else [msg]):
                reply = self.handle(m)
                if reply is not None:
                    self.send(reply)

    def handle(self, msg):
        if not isinstance(msg, dict) or "method" not in msg:
            if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                return None   # a response to a server->client request (we send none)
            return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                    "error": {"code": -32600, "message": "invalid request"}}
        method, params, mid = msg["method"], msg.get("params") or {}, msg.get("id")
        is_notification = "id" not in msg
        try:
            result = self.dispatch(method, params)
        except _RPCError as e:
            return None if is_notification else {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": e.message}}
        except Exception as e:  # never let one request kill the server
            traceback.print_exc(file=sys.stderr)
            return None if is_notification else {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "internal error: %s" % e}}
        return None if is_notification else {"jsonrpc": "2.0", "id": mid, "result": result}

    def dispatch(self, method, params):
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method.startswith("notifications/"):
            return None
        if method == "tools/list":
            return {"tools": tool_list()}
        if method == "tools/call":
            return self.call_tool(params.get("name"), params.get("arguments") or {})
        raise _RPCError(-32601, "method not found: %s" % method)

    def call_tool(self, name, args):
        if name not in TOOLS:
            raise _RPCError(-32602, "unknown tool: %s" % name)
        t = time.time()
        try:
            if name == "batch":
                _check_args("batch", args)
                steps, warnings, images, error = self.tools.batch(args["ops"])
                payload = {"ok": error is None, "steps": steps}
                if error:
                    payload["error"] = error
                if warnings:
                    payload["warnings"] = warnings
                is_error = error is not None
            else:
                result, warnings, images = self.tools.run(name, args)
                payload = dict(result)
                if warnings:
                    payload["warnings"] = warnings
                is_error = False
        except ToolError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except MMError as e:   # engine failed to start
            return {"content": [{"type": "text", "text": "%s: %s" % (e.code, e.message)}], "isError": True}
        for p in images:
            payload.setdefault("images", []).append(_rel(p))
        payload["tool_seconds"] = round(time.time() - t, 2)
        content = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
        for p in images:
            if Path(p).is_file():
                content.append(_image_content(p))
        return {"content": content, "isError": is_error}


class _RPCError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def tool_list():
    return [{"name": n, "description": d, "inputSchema": s, "annotations": a} for n, (d, s, a) in TOOLS.items()]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mcp_server", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="start the engine, print its ready info, exit")
    ap.add_argument("--list-tools", action="store_true", help="print the tool definitions as JSON")
    ap.add_argument("--config", help="mmx.toml to use (default agent_tools/mmx.toml or $MMX_CONFIG)")
    ap.add_argument("--engine-command", help="command line that starts the engine server (tests)")
    ap.add_argument("--timeout", type=float, help="seconds per engine request (default mmx.toml timeout)")
    ap.add_argument("--log", help="engine stderr log (default agent_runs/mcp/engine.log)")
    args = ap.parse_args(argv)
    if args.list_tools:
        print(json.dumps(tool_list(), indent=1))
        return 0
    cfg = mmx.load_config(args.config)
    cmd = shlex.split(args.engine_command) if args.engine_command else None
    tools = MaterialMakerTools(cfg, engine_command=cmd, timeout=args.timeout, log_path=args.log)
    if args.check:
        try:
            mm = tools.engine()
        except MMError as e:
            print(json.dumps({"ok": False, "error": {"code": e.code, "message": e.message}}))
            return 1
        print(json.dumps({"ok": True, "start_seconds": mm.start_seconds, "engine": mm.info,
                          "tools": list(TOOLS), "log": _rel(tools.log_path)}))
        tools.close()
        return 0
    atexit.register(tools.close)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr   # stray prints must never corrupt the MCP stream
    try:
        MCPServer(tools, out=real_stdout).serve()
    except KeyboardInterrupt:
        pass
    finally:
        tools.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
