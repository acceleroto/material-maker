#!/usr/bin/env python3
"""Tests for mcp_server.py (MCP over stdio on top of the engine server).
Run: agent_tools/.venv/bin/python -m unittest agent_tools/test_mcp_server.py -v  (MMX_SKIP_ENGINE=1 skips the real engine)"""

import base64
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_server  # noqa: E402
import mmx  # noqa: E402
from mcp_server import MaterialMakerTools, MCPServer  # noqa: E402

BRICKS = mmx.REPO / "material_maker" / "examples" / "bricks.ptex"
SERVER = Path(mcp_server.__file__)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")

# Minimal engine server: enough of the --serve protocol for the MCP layer
FAKE_ENGINE = r'''
import base64, json, sys, time
PNG = base64.b64decode("%s")
print("Godot Engine noise", flush=True)
print(json.dumps({"mm_rpc": 1, "id": None, "ok": True, "result": {"ready": True, "version": 1}}), flush=True)
loaded = None
for line in sys.stdin:
    req = json.loads(line)
    rid, m, p = req.get("id"), req["method"], req.get("params", {})
    out = lambda d: print(json.dumps(dict({"mm_rpc": 1, "id": rid}, **d)), flush=True)
    if m == "load":
        loaded = p["path"]
        out({"ok": True, "result": {"path": loaded, "nodes": 3}})
    elif loaded is None and m != "shutdown":
        out({"ok": False, "error": {"code": "no_graph", "message": "no graph loaded"}})
    elif m in ("render_preview", "render_output"):
        open(p["output"], "wb").write(PNG)
        out({"ok": True, "result": {"file": p["output"], "params": p}})
    elif m == "set_param":
        if p["node"] == "Nope":
            out({"ok": False, "error": {"code": "unknown_node", "message": "no node Nope"}})
        elif p["node"] == "Hang":
            time.sleep(30)
        elif p["node"] == "Crash":
            sys.exit(3)
        else:
            out({"ok": True, "result": {"node": p["node"], "params": p}, "warnings": ["out of range"]})
    elif m == "shutdown":
        out({"ok": True, "result": {"bye": True}})
        sys.exit(0)
    else:
        out({"ok": True, "result": {"method": m, "params": p}})
''' % base64.b64encode(PNG).decode()


class FakeEngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        fake = self.dir / "fake_engine.py"
        fake.write_text(FAKE_ENGINE)
        self.engine_cmd = [sys.executable, str(fake)]
        self.tools = MaterialMakerTools(engine_command=self.engine_cmd, timeout=3, out_root=self.dir / "out")
        self.out = io.StringIO()
        self.server = MCPServer(self.tools, out=self.out)

    def tearDown(self):
        self.tools.close()
        self.tmp.cleanup()

    def rpc(self, method, params=None, id=1):
        return self.server.handle({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})

    def tool(self, _tool, **args):
        r = self.rpc("tools/call", {"name": _tool, "arguments": args})["result"]
        text = r["content"][0]["text"]
        payload = json.loads(text) if text.startswith("{") else text
        return r, payload


class TestProtocol(FakeEngineCase):
    def test_initialize_negotiates_version(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["capabilities"])
        self.assertEqual(r["serverInfo"]["name"], "material-maker")
        r = self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(r["protocolVersion"], mcp_server.PROTOCOL_VERSIONS[0])

    def test_tools_list_schemas(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        names = [t["name"] for t in tools]
        for method in ("load", "save", "list_nodes", "describe_node", "add_node", "remove_node", "connect", "disconnect",
                       "set_param", "get_graph", "validate", "render_output", "render_preview", "export", "batch", "restart"):
            self.assertIn(method, names)
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertGreater(len(t["description"]), 30)
            for req in t["inputSchema"].get("required", []):
                self.assertIn(req, t["inputSchema"]["properties"])

    def test_notification_and_errors(self):
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.rpc("ping")["result"], {})
        self.assertEqual(self.rpc("nope/method")["error"]["code"], -32601)
        self.assertEqual(self.rpc("tools/call", {"name": "nope"})["error"]["code"], -32602)
        self.server.serve(io.StringIO("{bad json\n\n"))
        self.assertEqual(json.loads(self.out.getvalue())["error"]["code"], -32700)

    def test_malformed_messages(self):
        handle = self.server.handle
        self.assertEqual(handle({"jsonrpc": "2.0", "id": 1, "method": 5})["error"]["code"], -32600)
        self.assertEqual(handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": [1]})["error"]["code"], -32602)
        self.assertEqual(self.rpc("tools/call", {"name": "load", "arguments": "x"})["error"]["code"], -32602)
        self.assertEqual(self.rpc("tools/call", {"name": ["load"]})["error"]["code"], -32602)
        self.assertEqual(handle("just a string")["error"]["code"], -32600)
        self.assertIsNone(handle({"jsonrpc": "2.0", "id": 3, "result": {}}))   # a response, not a request
        self.server.serve(io.StringIO("[]\n"))
        self.assertEqual(json.loads(self.out.getvalue())["error"]["code"], -32600)
        self.assertEqual(self.rpc("ping")["result"], {})   # still serving

    def test_engine_starts_lazily(self):
        self.rpc("tools/list")
        self.assertIsNone(self.tools.mm)
        self.tool("get_graph")
        self.assertIsNotNone(self.tools.mm)


class TestTools(FakeEngineCase):
    def test_engine_error_is_tool_error(self):
        r, text = self.tool("get_graph")
        self.assertTrue(r["isError"])
        self.assertIn("no_graph", text)
        self.assertIn("call load first", text)

    def test_arg_checks(self):
        r, text = self.tool("load", bogus=1)
        self.assertTrue(r["isError"])
        self.assertIn("bogus", text)
        r, text = self.tool("connect", to="x")
        self.assertIn("needs from", text)
        r, text = self.tool("load", path="no/such/file.ptex")
        self.assertIn("load_failed", text)
        self.assertIsNone(self.tools.mm)   # rejected before starting the engine

    def test_arg_types_and_ranges(self):
        for tool, args, expect in [
                ("load", {"path": 5}, "load.path must be string"),
                ("render_preview", {"size": 100000}, "render_preview.size must be <= 2048"),
                ("render_preview", {"size": "big"}, "must be integer"),
                ("render_output", {"node": "a", "size": 8}, "must be >= 16"),
                ("render_output", {"node": "a", "port": True}, "must be integer"),
                ("export", {"size": 16384}, "must be <= 8192"),
                ("add_node", {"type": "perlin", "position": [1]}, "must have 2..2 items"),
                ("add_node", {"type": "perlin", "position": ["a", 2]}, "add_node.position[0] must be number"),
                ("get_graph", {"full": "yes"}, "must be boolean"),
                ("batch", {"ops": []}, "must have 1..any items"),
                ("batch", {"ops": [{"method": "load", "x": 1}]}, "batch.ops[0] does not take x"),
                ("batch", {"ops": [{"method": "load", "params": []}]}, "batch.ops[0].params must be object"),
                ("batch", {"ops": [{"params": {}}]}, "batch.ops[0] needs method")]:
            r, text = self.tool(tool, **args)
            self.assertTrue(r["isError"], (tool, args))
            self.assertIn(expect, text, (tool, args))
        self.assertIsNone(self.tools.mm)   # all rejected before starting the engine
        r, p = self.tool("render_output", node="a", size=64.0, output=str(self.dir / "x.png"), return_image=False)
        self.assertIn("no_graph", p)   # 64.0 is an integer: passed on

    def test_large_images_not_inlined(self):
        self.tool("load", path=str(BRICKS))
        old = mcp_server.MAX_INLINE_IMAGE_BYTES
        mcp_server.MAX_INLINE_IMAGE_BYTES = 10
        try:
            r, p = self.tool("render_preview")
        finally:
            mcp_server.MAX_INLINE_IMAGE_BYTES = old
        self.assertFalse(r["isError"])
        self.assertEqual([c["type"] for c in r["content"]], ["text"])
        self.assertIn("render smaller", p["images_not_inlined"][0])

    def test_relative_path_and_render_returns_image(self):
        r, p = self.tool("load", path="material_maker/examples/bricks.ptex")
        self.assertFalse(r["isError"])
        self.assertEqual(p["path"], str(BRICKS))
        r, p = self.tool("render_preview")
        self.assertEqual([c["type"] for c in r["content"]], ["text", "image"])
        self.assertEqual(r["content"][1]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(r["content"][1]["data"]), PNG)
        out = self.dir / "out" / "bricks" / "preview_001.png"
        self.assertEqual(p["file"], str(out))
        self.assertEqual(p["params"]["mesh"], "sphere+plane")   # defaults from mmx.toml
        r, p = self.tool("render_preview", return_image=False)
        self.assertEqual(len(r["content"]), 1)
        self.assertTrue(p["file"].endswith("preview_002.png"))
        r, p = self.tool("render_output", node="graph/Bricks", port=1)
        self.assertTrue(p["file"].endswith("node_graph_Bricks_p1_001.png"))
        self.assertEqual(r["content"][1]["type"], "image")

    def test_set_param_forms_and_warnings(self):
        self.tool("load", path=str(BRICKS))
        r, p = self.tool("set_param", node="Perlin", name="scale_x", value=8)
        self.assertEqual(p["params"], {"node": "Perlin", "name": "scale_x", "value": 8})
        self.assertEqual(p["warnings"], ["out of range"])
        r, p = self.tool("set_param", node="Perlin", params={"scale_x": 8})
        self.assertEqual(p["params"], {"node": "Perlin", "params": {"scale_x": 8}})
        r, text = self.tool("set_param", node="Perlin")
        self.assertTrue(r["isError"])

    def test_connect_passes_from(self):
        self.tool("load", path=str(BRICKS))
        r, p = self.tool("connect", **{"from": "a", "to": "b", "to_port": 2})
        self.assertEqual(p["params"], {"from": "a", "from_port": 0, "to": "b", "to_port": 2})
        r, p = self.tool("disconnect", to="b")
        self.assertEqual(p["params"], {"to": "b", "to_port": 0})

    def test_export_defaults(self):
        self.tool("load", path=str(BRICKS))
        r, p = self.tool("export")
        self.assertEqual(p["params"]["output_dir"], str(self.dir / "out" / "bricks" / "export"))
        self.assertEqual(p["params"]["prefix"], "bricks")
        self.assertEqual(p["params"]["target"], mmx.load_config()["target"])

    def test_batch_stops_at_first_failure(self):
        r, p = self.tool("batch", ops=[{"method": "load", "params": {"path": str(BRICKS)}},
                                       {"method": "set_param", "params": {"node": "Perlin", "name": "a", "value": 1}},
                                       {"method": "render_preview"},
                                       {"method": "set_param", "params": {"node": "Nope", "name": "a", "value": 1}},
                                       {"method": "render_preview"}])
        self.assertTrue(r["isError"])
        self.assertEqual(len(p["steps"]), 3)
        self.assertIn("op 3 (set_param) failed: unknown_node", p["error"])
        self.assertEqual(p["warnings"], ["op 1: out of range"])
        self.assertEqual([c["type"] for c in r["content"]], ["text", "image"])
        r, p = self.tool("batch", ops=[{"method": "batch", "params": {}}])
        self.assertIn("unknown method", p["error"])

    def test_crash_and_timeout_recover_graph(self):
        self.tool("load", path=str(BRICKS))
        self.tool("set_param", node="Perlin", name="a", value=1)
        r, text = self.tool("set_param", node="Crash", name="a", value=1)
        self.assertTrue(r["isError"])
        self.assertIn("server_died", text)
        self.assertIn("reloaded bricks.ptex and replayed 1 of 1 edits", text)
        self.assertIn("was not repeated", text)
        r, p = self.tool("get_graph")   # new engine with the graph restored
        self.assertFalse(r["isError"], p)
        self.assertEqual(self.tools.graph_path, BRICKS)
        r, text = self.tool("set_param", node="Hang", name="a", value=1)
        self.assertIn("timeout", text)
        self.assertIn("reloaded bricks.ptex", text)
        r, p = self.tool("render_preview")
        self.assertFalse(r["isError"], p)
        self.assertTrue(p["file"].endswith("bricks/preview_001.png"))

    def test_engine_killed_between_calls(self):
        self.tool("load", path=str(BRICKS))
        self.tools.mm.proc.kill()
        self.tools.mm.proc.wait()
        r, p = self.tool("get_graph")
        self.assertFalse(r["isError"], p)
        self.assertIn("the engine had exited; engine restarted, reloaded bricks.ptex", p["warnings"][0])

    def test_restart_tool(self):
        r, p = self.tool("restart")
        self.assertTrue(p["restarted"])
        self.tool("load", path=str(BRICKS))
        r, p = self.tool("restart")
        self.assertEqual(p["graph"], str(BRICKS))
        r, p = self.tool("restart", reload=False)
        self.assertIsNone(p["graph"])
        r, text = self.tool("get_graph")
        self.assertIn("no_graph", text)


class TestStdio(unittest.TestCase):
    def test_subprocess_session(self):
        with tempfile.TemporaryDirectory() as t:
            fake = Path(t) / "fake_engine.py"
            fake.write_text(FAKE_ENGINE)
            lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                     {"jsonrpc": "2.0", "method": "notifications/initialized"},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "load", "arguments": {"path": str(BRICKS)}}},
                     {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "render_preview", "arguments": {"output": str(Path(t) / "p.png")}}}]
            p = subprocess.run([sys.executable, str(SERVER), "--engine-command", shlex.join([sys.executable, str(fake)]),
                                "--log", str(Path(t) / "engine.log")],
                               input="".join(json.dumps(l) + "\n" for l in lines), capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            out = [json.loads(l) for l in p.stdout.splitlines()]   # stdout carries only MCP messages
            self.assertEqual([o["id"] for o in out], [1, 2, 3])
            self.assertEqual(out[0]["result"]["protocolVersion"], "2024-11-05")
            self.assertFalse(out[2]["result"]["isError"], out[2])
            self.assertEqual(out[2]["result"]["content"][1]["type"], "image")

    def test_list_tools_cli(self):
        p = subprocess.run([sys.executable, str(SERVER), "--list-tools"], capture_output=True, text=True, timeout=30)
        self.assertEqual(len(json.loads(p.stdout)), len(mcp_server.TOOLS))


def godot_available():
    cfg = mmx.load_config()
    return (cfg["mode"] == "source" and Path(cfg["source"]["godot"]).exists()
            and not os.environ.get("MMX_SKIP_ENGINE"))


@unittest.skipUnless(godot_available(), "needs Godot + mode = source (set MMX_SKIP_ENGINE=1 to skip)")
class TestRealEngine(unittest.TestCase):
    def test_edit_render_export(self):
        with tempfile.TemporaryDirectory() as t:
            tools = MaterialMakerTools(out_root=Path(t) / "out", log_path=Path(t) / "engine.log")
            server = MCPServer(tools, out=io.StringIO())

            def tool(_tool, **args):
                return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": _tool, "arguments": args}})["result"]
            try:
                self.assertFalse(tool("load", path=str(BRICKS))["isError"])
                r = tool("batch", ops=[{"method": "set_param", "params": {"node": "Perlin", "params": {"scale_x": 8}}},
                                       {"method": "render_preview", "params": {"size": 128}},
                                       {"method": "render_output", "params": {"node": "Perlin", "size": 64}}])
                self.assertFalse(r["isError"], r["content"][0]["text"])
                images = [c for c in r["content"] if c["type"] == "image"]
                self.assertEqual(len(images), 2)
                self.assertEqual(base64.b64decode(images[0]["data"])[:4], b"\x89PNG")
                r = tool("validate")
                self.assertTrue(json.loads(r["content"][0]["text"])["ok"])
                r = tool("export", size=64)
                files = json.loads(r["content"][0]["text"])["files"]
                self.assertTrue(any(f.endswith("bricks_albedo.png") for f in files))
                self.assertTrue(all(Path(f).is_file() for f in files))
            finally:
                tools.close()

    def test_engine_crash_recovery(self):
        with tempfile.TemporaryDirectory() as t:
            tools = MaterialMakerTools(out_root=Path(t) / "out", log_path=Path(t) / "engine.log")
            server = MCPServer(tools, out=io.StringIO())

            def tool(_tool, **args):
                r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": _tool, "arguments": args}})["result"]
                return r, json.loads(r["content"][0]["text"])
            try:
                tool("load", path=str(BRICKS))
                r, p = tool("add_node", type="perlin", name="extra", position=[100, 200])
                self.assertFalse(r["isError"], p)
                os.kill(tools.mm.proc.pid, 9)
                tools.mm.proc.wait(10)
                r, p = tool("render_preview", size=64)
                self.assertFalse(r["isError"], p)
                self.assertIn("reloaded bricks.ptex and replayed 1 of 1 edits", p["warnings"][0])
                self.assertEqual(r["content"][1]["type"], "image")
                r, p = tool("describe_node", node="extra")
                self.assertFalse(r["isError"], p)
            finally:
                tools.close()


if __name__ == "__main__":
    unittest.main()
