#!/usr/bin/env python3
"""Tests for mm_client.py and the engine's --serve mode.
Run: agent_tools/.venv/bin/python -m unittest agent_tools/test_mm_client.py -v  (MMX_SKIP_ENGINE=1 skips the real engine)"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mm_client  # noqa: E402
import mmx  # noqa: E402
from mm_client import MMClient, MMError  # noqa: E402

BRICKS = mmx.REPO / "material_maker" / "examples" / "bricks.ptex"

# Speaks the protocol, with engine-like noise on stdout
FAKE_SERVER = r'''
import json, sys, time
print("Godot Engine v4.7.2 - noise before the ready line", flush=True)
print(json.dumps({"mm_rpc": 1, "id": None, "ok": True, "result": {"ready": True, "version": 1}}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    rid, m, p = req.get("id"), req["method"], req.get("params", {})
    out = lambda d: print(json.dumps(dict({"mm_rpc": 1, "id": rid}, **d)), flush=True)
    if m == "echo":
        print("LOADER: some engine message", flush=True)
        print("{not json", flush=True)
        print(json.dumps({"other": "json without mm_rpc"}), flush=True)
        out({"ok": True, "result": p, "warnings": ["careful"]})
    elif m == "stale":
        print(json.dumps({"mm_rpc": 1, "id": -5, "ok": True, "result": {"stale": True}}), flush=True)
        out({"ok": True, "result": {"fresh": True}})
    elif m == "fail":
        out({"ok": False, "error": {"code": "unknown_node", "message": "no node X"}})
    elif m == "hang":
        time.sleep(60)
    elif m == "crash":
        print("about to crash", flush=True)
        sys.exit(3)
    elif m == "shutdown":
        out({"ok": True, "result": {"bye": True}})
        sys.exit(0)
'''

# Keeps a graph path + edit list, so that crash recovery can be checked; started engines are counted in a file
STATEFUL_SERVER = r'''
import json, os, sys, time
count = sys.argv[1]
n = int(open(count).read()) + 1 if os.path.exists(count) else 1
open(count, "w").write(str(n))
print(json.dumps({"mm_rpc": 1, "id": None, "ok": True, "result": {"ready": True, "engine": n}}), flush=True)
graph, edits = None, []
for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        print(json.dumps({"mm_rpc": 1, "id": None, "ok": False, "error": {"code": "parse_error", "message": "bad"}}), flush=True)
        continue
    rid, m, p = req.get("id"), req["method"], req.get("params", {})
    out = lambda d: print(json.dumps(dict({"mm_rpc": 1, "id": rid}, **d)), flush=True)
    if m == "load":
        if "missing" in p["path"]:
            out({"ok": False, "error": {"code": "load_failed", "message": "no such file"}})
            continue
        graph, edits = p["path"], []
        out({"ok": True, "result": {"path": graph}})
    elif m == "save":
        graph = p.get("path", graph)
        out({"ok": True, "result": {"path": graph}})
    elif m == "set_param":
        if p.get("value") == "crash":
            sys.exit(3)
        if p.get("value") == "hang":
            time.sleep(60)
        if p.get("value") == "crash_on_replay" and n > 1:
            sys.exit(3)
        edits.append(p["value"])
        out({"ok": True, "result": {}})
    elif m == "state":
        out({"ok": True, "result": {"graph": graph, "edits": edits, "engine": n}})
    elif m == "exit_after":
        out({"ok": True, "result": {}})
        sys.exit(0)
    elif m == "shutdown":
        out({"ok": True, "result": {"bye": True}})
        sys.exit(0)
'''


class TestClientWithFakeServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fake = Path(self.tmp.name) / "fake_server.py"
        fake.write_text(FAKE_SERVER)
        self.mm = MMClient(command=[sys.executable, str(fake)], log_path=Path(self.tmp.name) / "server.log", timeout=5,
                           auto_restart=False)

    def tearDown(self):
        self.mm.close(timeout=2)
        self.tmp.cleanup()

    def test_ready_and_echo_skips_noise(self):
        self.assertTrue(self.mm.info["ready"])
        self.assertEqual(self.mm.call("echo", a=1, b=[1, 2]), {"a": 1, "b": [1, 2]})
        self.assertEqual(self.mm.last_warnings, ["careful"])
        self.assertIn("LOADER: some engine message", self.mm.noise)

    def test_stale_response_dropped(self):
        self.assertEqual(self.mm.call("stale"), {"fresh": True})

    def test_error_raises(self):
        with self.assertRaises(MMError) as cm:
            self.mm.call("fail")
        self.assertEqual(cm.exception.code, "unknown_node")
        self.assertEqual(self.mm.call("echo", x=1), {"x": 1})  # still alive

    def test_timeout_kills(self):
        with self.assertRaises(MMError) as cm:
            self.mm.call("hang", timeout=0.5)
        self.assertEqual(cm.exception.code, "timeout")
        self.assertIsNotNone(self.mm.proc.poll())
        with self.assertRaises(MMError) as cm:
            self.mm.call("echo")
        self.assertEqual(cm.exception.code, "server_died")

    def test_crash(self):
        with self.assertRaises(MMError) as cm:
            self.mm.call("crash")
        self.assertEqual(cm.exception.code, "server_died")
        self.assertIn("about to crash", cm.exception.message)

    def test_close_shutdown(self):
        self.assertEqual(self.mm.close(), 0)

    def test_unsendable_requests(self):
        for bad in ({"v": float("nan")}, {"v": object()}):
            with self.assertRaises(MMError) as cm:
                self.mm.call("echo", **bad)
            self.assertEqual(cm.exception.code, "bad_params")
        with self.assertRaises(MMError) as cm:
            self.mm.call("echo", v="x" * (mm_client.MAX_REQUEST_BYTES + 1))
        self.assertIn("too large", cm.exception.message)
        self.assertEqual(self.mm.call("echo", v="é"), {"v": "é"})   # nothing was sent: still in sync

    def test_light_methods_get_shorter_timeouts(self):
        self.mm.timeout = 1000
        waits = []
        self.mm._wait = lambda req_id, timeout: waits.append(timeout) or {"ok": True, "id": req_id}
        self.mm.call("set_param", node="a")
        self.mm.call("render_preview")
        self.assertEqual(waits, [mm_client.LIGHT_TIMEOUT, 1000])


class TestRecovery(unittest.TestCase):
    """auto_restart: a crash/timeout restarts the engine, reloads the last loaded/saved graph, replays the edits."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        fake = d / "stateful_server.py"
        fake.write_text(STATEFUL_SERVER)
        self.mm = MMClient(command=[sys.executable, str(fake), str(d / "count")], log_path=d / "server.log", timeout=5)

    def tearDown(self):
        self.mm.close(timeout=2)
        self.tmp.cleanup()

    def test_crash_restores_graph_and_edits(self):
        self.mm.load("/g/a.ptex")
        self.mm.set_param("n", "x", 1)
        self.mm.set_param("n", "x", 2)
        with self.assertRaises(MMError) as cm:
            self.mm.set_param("n", "x", "crash")
        e = cm.exception
        self.assertEqual(e.code, "server_died")
        self.assertEqual(e.recovery["graph"], "/g/a.ptex")
        self.assertEqual(e.recovery["replayed"], 2)
        self.assertIn("reloaded a.ptex and replayed 2 of 2 edits", e.message)
        self.assertEqual(self.mm.call("state"), {"graph": "/g/a.ptex", "edits": [1, 2], "engine": 2})
        self.assertIn("engine restart 1", (Path(self.tmp.name) / "server.log").read_text())

    def test_save_resets_the_journal(self):
        self.mm.load("/g/a.ptex")
        self.mm.set_param("n", "x", 1)
        self.mm.save("/g/b.ptex")
        self.mm.set_param("n", "x", 2)
        with self.assertRaises(MMError):
            self.mm.set_param("n", "x", "crash")
        self.assertEqual(self.mm.call("state")["graph"], "/g/b.ptex")
        self.assertEqual(self.mm.call("state")["edits"], [2])

    def test_timeout_restores(self):
        self.mm.load("/g/a.ptex")
        self.mm.set_param("n", "x", 1)
        with self.assertRaises(MMError) as cm:
            self.mm.call("set_param", node="n", value="hang", timeout=0.5)
        self.assertEqual(cm.exception.code, "timeout")
        self.assertEqual(self.mm.call("state")["edits"], [1])

    def test_died_between_requests(self):
        self.mm.load("/g/a.ptex")
        self.mm.set_param("n", "x", 1)
        self.mm.call("exit_after")
        self.mm.proc.wait(5)
        state = self.mm.call("state")   # recovered first, then answered
        self.assertEqual((state["graph"], state["edits"], state["engine"]), ("/g/a.ptex", [1], 2))
        self.assertEqual(self.mm.last_recovery["replayed"], 1)

    def test_replay_crash_falls_back_to_graph_only(self):
        self.mm.load("/g/a.ptex")
        self.mm.set_param("n", "x", "crash_on_replay")   # fine in engine 1, crashes every later engine
        with self.assertRaises(MMError) as cm:
            self.mm.set_param("n", "x", "crash")
        self.assertEqual(cm.exception.recovery["graph"], "/g/a.ptex")
        self.assertEqual(cm.exception.recovery["replayed"], 0)
        self.assertIn("crashed the engine again", cm.exception.message)
        self.assertEqual(self.mm.call("state")["edits"], [])

    def test_graph_gone_after_crash(self):
        self.mm.load("/g/a.ptex")
        self.mm.graph_path = "/g/missing.ptex"   # as if the file was deleted meanwhile
        with self.assertRaises(MMError) as cm:
            self.mm.set_param("n", "x", "crash")
        self.assertIsNone(cm.exception.recovery["graph"])
        self.assertIn("could not be restored", cm.exception.message)
        self.assertIsNone(self.mm.call("state")["graph"])

    def test_restart_without_reload_and_no_graph(self):
        self.assertIn("no graph had been loaded", self.mm.restart()["summary"])
        self.mm.load("/g/a.ptex")
        self.mm.set_param("n", "x", 1)
        r = self.mm.restart(reload=False)
        self.assertEqual((r["graph"], r["edits_lost"]), (None, 1))
        self.assertIsNone(self.mm.call("state")["graph"])

    def test_malformed_line_answered(self):
        """A parse_error without id while a request is pending is that request's answer (no timeout)."""
        self.mm.proc.stdin.write("garbage\n")
        self.mm.proc.stdin.flush()
        t = time.time()
        msg = self.mm._wait(12345, 5)
        self.assertEqual(msg["error"]["code"], "parse_error")
        self.assertLess(time.time() - t, 2)

    def test_wrappers_build_params(self):
        sent = []
        self.mm.call = lambda method, timeout=None, **p: sent.append((method, p)) or {}
        self.mm.set_param("Perlin", "scale_x", 8)
        self.mm.set_param("Perlin", scale_x=8, scale_y=4)
        self.mm.connect("a", 0, "b", 1)
        self.mm.disconnect("b", 1)
        self.mm.get_graph()
        self.assertEqual(sent[0], ("set_param", {"node": "Perlin", "name": "scale_x", "value": 8}))
        self.assertEqual(sent[1], ("set_param", {"node": "Perlin", "params": {"scale_x": 8, "scale_y": 4}}))
        self.assertEqual(sent[2], ("connect", {"from": "a", "from_port": 0, "to": "b", "to_port": 1}))
        self.assertEqual(sent[3], ("disconnect", {"to": "b", "to_port": 1}))
        self.assertEqual(sent[4], ("get_graph", {}))


class TestStartFailures(unittest.TestCase):
    def test_no_binary(self):
        with self.assertRaises(MMError) as cm:
            MMClient(command=["/nonexistent/godot"])
        self.assertEqual(cm.exception.code, "start_failed")

    def test_exits_before_ready(self):
        with self.assertRaises(MMError) as cm:
            MMClient(command=[sys.executable, "-c", "print('boom')"], start_timeout=5)
        self.assertEqual(cm.exception.code, "server_died")

    def test_release_mode_refused(self):
        cfg = mmx.load_config()
        cfg["mode"] = "release"
        with self.assertRaises(MMError):
            MMClient(cfg=cfg)

    def test_missing_godot_or_project(self):
        cfg = mmx.load_config()
        cfg["mode"] = "source"
        cfg["source"] = dict(cfg["source"], godot="/nonexistent/Godot")
        with self.assertRaises(MMError) as cm:
            MMClient(cfg=cfg)
        self.assertIn("Godot not found", cm.exception.message)
        cfg["source"] = dict(cfg["source"], godot=sys.executable, project="/nonexistent")
        with self.assertRaises(MMError) as cm:
            MMClient(cfg=cfg)
        self.assertIn("no project.godot", cm.exception.message)


def godot_available():
    cfg = mmx.load_config()
    return (cfg["mode"] == "source" and Path(cfg["source"]["godot"]).exists()
            and not os.environ.get("MMX_SKIP_ENGINE"))


def md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(godot_available(), "needs Godot + mode = source (set MMX_SKIP_ENGINE=1 to skip)")
class TestRealServer(unittest.TestCase):
    """One engine server for the whole class (~1 min)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name).resolve()
        cls.mm = MMClient(log_path=cls.dir / "server.log", timeout=120)

    @classmethod
    def tearDownClass(cls):
        cls.mm.close()
        cls.tmp.cleanup()

    def setUp(self):
        if self.mm.proc.poll() is not None:  # a failed test killed it: don't fail every later test too
            type(self).mm = MMClient(log_path=self.dir / "server_restarted.log", timeout=120)
        self.mm.load(BRICKS)

    def assertError(self, code, method, **params):
        with self.assertRaises(MMError) as cm:
            self.mm.call(method, **params)
        self.assertEqual(cm.exception.code, code, cm.exception.message)
        return cm.exception

    def test_ready(self):
        self.assertTrue(self.mm.info["ready"])
        self.assertTrue(self.mm.info["rendering_device"])
        self.assertIn("render_preview", self.mm.info["methods"])

    def test_load_and_get_graph(self):
        r = self.mm.load(BRICKS)
        self.assertTrue(r["material"])
        self.assertEqual(r["nodes"], 17)
        g = self.mm.get_graph()
        names = {n["name"] for n in g["nodes"]}
        self.assertIn("Perlin", names)
        self.assertIn({"from": "Perlin", "from_port": 0, "to": "Warp", "to_port": 1}, g["connections"])
        self.assertEqual(self.mm.get_graph(full=True)["graph"]["type"], "graph")
        sub = self.mm.get_graph(node="graph")
        self.assertIn("Bricks", {n["name"] for n in sub["nodes"]})
        self.assertError("load_failed", "load", path=str(self.dir / "missing.ptex"))
        self.assertError("bad_params", "load", path="relative.ptex")

    def test_list_and_describe(self):
        r = self.mm.list_nodes(query="voronoi")
        self.assertTrue(any(t["type"] == "voronoi" for t in r["types"]))
        d = self.mm.describe_node(type="perlin")
        self.assertEqual(d["type"], "perlin")
        d = self.mm.describe_node(node="Perlin")
        self.assertEqual(d["type"], "perlin")
        self.assertEqual({p["name"]: p["default"] for p in d["parameters"]}["scale_x"], 4)
        self.assertEqual(d["connections"]["outputs"][0]["to"], "Warp")
        self.assertError("unknown_type", "describe_node", type="no_such_type")
        self.assertError("unknown_node", "describe_node", node="Nope")

    def test_edit_cycle(self):
        a = self.mm.add_node("perlin", parameters={"scale_x": 3})
        self.assertEqual(a["name"], "perlin")
        self.assertEqual(a["parameters"]["scale_x"], 3)
        c = self.mm.connect(a["name"], 0, "Warp", 1)
        self.assertEqual(c["replaced"]["from"], "Perlin")
        r = self.mm.set_param("Perlin", scale_x=12, scale_y=12)
        self.assertEqual([(x["name"], x["old"], x["new"]) for x in r["changed"]], [("scale_x", 4, 12), ("scale_y", 4, 12)])
        self.mm.set_param("blend_1", "blend_type", "multiply")
        self.assertEqual(self.mm.describe_node(node="blend_1")["parameters"][0]["default"], 2)
        self.mm.set_param("Warp", "amount", 5)
        self.assertTrue(any("slider range" in w for w in self.mm.last_warnings))
        self.assertEqual(self.mm.disconnect("Warp", 1)["removed"]["from"], a["name"])
        self.assertEqual(self.mm.remove_node(a["name"])["removed"], a["name"])
        self.assertNotIn(a["name"], {n["name"] for n in self.mm.get_graph()["nodes"]})

    def test_edit_errors_keep_server_alive(self):
        self.assertError("connection_rejected", "connect", **{"from": "blend_0", "from_port": 0, "to": "Warp", "to_port": 0})
        self.assertError("bad_port", "connect", **{"from": "Perlin", "from_port": 3, "to": "Warp", "to_port": 0})
        self.assertError("unknown_parameter", "set_param", node="Perlin", name="nope", value=1)
        self.assertError("bad_value", "set_param", node="Perlin", name="iterations", value="x")
        self.assertError("cannot_delete", "remove_node", node="Material")
        self.assertError("unknown_type", "add_node", type="no_such_type")
        self.assertError("no_connection", "disconnect", to="Perlin", to_port=0)
        self.assertError("unknown_method", "frobnicate")
        self.assertError("bad_params", "set_param", node="Perlin")
        self.assertEqual(self.mm.validate()["ok"], True)

    def test_missing_files_and_dropped_nodes_warn(self):
        e = self.assertError("load_failed", "load", path=str(BRICKS.parent))
        self.assertIn("a directory", e.message)
        self.assertError("load_failed", "load", path=str(self.dir / "nope.ptex"))
        r = self.mm.add_node("image", name="img", position=[10, 20], parameters={"image": str(self.dir / "nope.png")})
        self.assertEqual(r["name"], "img")
        self.assertTrue(any("nope.png not found" in w for w in self.mm.last_warnings), self.mm.last_warnings)
        self.mm.set_param("img", "image", str(BRICKS))   # exists (not an image, but a file)
        self.assertEqual(self.mm.last_warnings, [])
        self.mm.set_param("img", "image", "/no/such/dir/tex.png")
        self.assertTrue(self.mm.last_warnings)
        v = self.mm.validate()
        self.assertTrue(v["ok"])
        self.assertEqual([w["code"] for w in v["warnings"]], ["missing_file"])
        # A file with a node of an unknown type and a missing image: loads, with warnings
        data = json.loads(BRICKS.read_text())
        data["nodes"].append({"name": "alien", "type": "no_such_type", "parameters": {}})
        data["nodes"].append({"name": "img", "type": "image", "parameters": {"image": "/no/such/tex.png"}})
        data["connections"].append({"from": "alien", "from_port": 0, "to": "Material", "to_port": 1})
        odd = self.dir / "odd.ptex"
        odd.write_text(json.dumps(data))
        self.mm.load(odd)
        w = " | ".join(self.mm.last_warnings)
        self.assertIn("alien has unknown type no_such_type", w)
        self.assertIn("tex.png not found", w)

    def test_size_limits(self):
        self.assertError("bad_params", "render_preview", output=str(self.dir / "x.png"), size=8192)
        self.assertError("bad_params", "render_output", node="Perlin", output=str(self.dir / "x.png"), size=16384)
        self.assertError("bad_params", "export", output_dir=str(self.dir / "big"), size=16384)
        self.assertError("bad_params", "render_output", node="Perlin", output=str(self.dir / "x.png"), size=8)
        self.assertError("bad_params", "add_node", type="perlin", position=[1])
        self.assertFalse((self.dir / "big").exists())

    def test_raw_protocol_errors(self):
        """Malformed lines answered with parse_error/bad_request, then normal service."""
        self.mm.proc.stdin.write("this is not json\n" + json.dumps({"id": 9001, "params": {}}) + "\n")
        self.mm.proc.stdin.flush()
        first = self.mm._wait(None, 30)
        self.assertEqual(first["error"]["code"], "parse_error")
        second = self.mm._wait(9001, 30)
        self.assertEqual(second["error"]["code"], "bad_request")
        self.assertTrue(self.mm.get_graph()["nodes"])

    def test_reload_before_renders_finish(self):
        """Regression: freeing a graph while mm_deps renders its buffers hung every later render."""
        self.mm.load(mmx.REPO / "material_maker" / "examples" / "stylized_wall.ptex")
        self.mm.load(BRICKS)
        self.mm.add_node("buffer", name="buf")
        self.mm.remove_node("buf")
        r = self.mm.call("render_output", node="blend_0", output=str(self.dir / "reload.png"), size=64, timeout=30)
        self.assertTrue(Path(r["file"]).exists())

    def test_preview_follows_edits_after_export(self):
        """Regression: an export replaced the Material's preview textures, so later edits never reached render_preview."""
        shots = []
        for i, v in enumerate([16, 2]):
            self.mm.export(self.dir / ("exp_follow%d" % i), size=64, prefix="b")
            self.mm.set_param("Perlin", "scale_x", v)
            png = self.dir / ("follow%d.png" % i)
            self.mm.render_preview(png, size=64)
            saved = self.dir / ("follow%d.ptex" % i)
            self.mm.save(saved)
            cli = mmx.render_preview(saved, self.dir / ("follow%d_cli.png" % i), size=64)
            self.assertEqual(md5(png), md5(cli["file"]), "iteration %d" % i)
            shots.append(md5(png))
        self.assertNotEqual(shots[0], shots[1])

    def test_validate_reports_shader_errors(self):
        self.mm.set_param("Perlin", "scale_x", "$nonsense_variable")
        r = self.mm.validate()
        self.assertFalse(r["ok"])
        self.assertTrue(any(e["code"] == "shader_compile_error" for e in r["errors"]))

    def test_renders_match_cli_after_edits(self):
        before = self.dir / "before.png"
        self.mm.render_output("blend_0", before, size=256)
        self.mm.set_param("Perlin", scale_x=12, scale_y=12)
        self.mm.set_param("colorize_0", "gradient", {"type": "Gradient", "interpolation": 1, "points": [
            {"pos": 0, "r": 0, "g": 0, "b": 0.5, "a": 1}, {"pos": 1, "r": 0.2, "g": 0.4, "b": 1, "a": 1}]})
        node_png, preview_png = self.dir / "node.png", self.dir / "preview.png"
        r = self.mm.render_output("blend_0", node_png, size=256)
        self.assertEqual(r["type"], "blend")
        self.mm.render_preview(preview_png, size=256)
        self.assertNotEqual(md5(before), md5(node_png))
        saved = self.dir / "edited.ptex"
        self.mm.save(saved)
        cli_node = mmx.node_preview(saved, "blend_0", size=256, out=self.dir / "cli_node.png")
        cli_preview = mmx.render_preview(saved, self.dir / "cli_preview.png", size=256)
        self.assertTrue(cli_node["ok"] and cli_preview["ok"])
        self.assertEqual(md5(node_png), md5(cli_node["file"]))
        self.assertEqual(md5(preview_png), md5(cli_preview["file"]))
        self.assertError("unknown_node", "render_output", node="Nope", output=str(self.dir / "x.png"))
        self.assertError("bad_params", "render_preview", output=str(self.dir / "x.png"), mesh="teapot")

    def test_export_and_save_round_trip(self):
        out = self.dir / "export"
        r = self.mm.export(out, size=256, prefix="bricks")
        names = sorted(Path(f).name for f in r["files"])
        self.assertIn("bricks.mat", names)
        self.assertIn("bricks_albedo.png", names)
        self.assertEqual(r["target"], "Unity/URP")
        again = self.mm.export(out, size=256, prefix="bricks")
        self.assertEqual(sorted(Path(f).name for f in again["files"]), names)  # .mat rewritten, not skipped
        self.assertIn(str(out / "bricks.mat"), again["deleted"])
        self.assertError("bad_params", "export", output_dir=str(out), target="Nope/Nope")
        self.mm.set_param("Perlin", "scale_x", 7)
        saved = self.dir / "round_trip.ptex"
        self.mm.save(saved)
        self.mm.load(saved)
        params = {n["name"]: n["parameters"] for n in self.mm.get_graph()["nodes"]}
        self.assertEqual(params["Perlin"]["scale_x"], 7)
        self.assertEqual(mmx.validate_full(saved, fast=True)["ok"], True)


@unittest.skipUnless(godot_available(), "needs Godot + mode = source (set MMX_SKIP_ENGINE=1 to skip)")
class TestServerLifecycle(unittest.TestCase):
    def test_killed_engine_recovers_graph_and_edits(self):
        """SIGKILL the engine after edits: the next request restarts it, reloads the graph and replays the edits,
        and renders the same pixels as before the crash."""
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            with MMClient(log_path=d / "server.log", timeout=120) as mm:
                mm.load(BRICKS)
                mm.set_param("Perlin", scale_x=11, scale_y=11)
                mm.add_node("perlin", name="extra")
                mm.connect("extra", 0, "Material", 1)
                mm.render_preview(d / "before.png", size=128)
                pid = mm.proc.pid
                os.kill(pid, 9)
                mm.proc.wait(10)
                mm.render_preview(d / "after.png", size=128)
                self.assertNotEqual(mm.proc.pid, pid)
                self.assertEqual(mm.last_recovery["replayed"], 3)
                self.assertEqual(md5(d / "before.png"), md5(d / "after.png"))
                params = {n["name"]: n["parameters"] for n in mm.get_graph()["nodes"]}
                self.assertEqual(params["Perlin"]["scale_x"], 11)
                self.assertIn("extra", params)


    def test_no_graph_then_eof_quits(self):
        cfg = mmx.load_config()
        cmd = [cfg["source"]["godot"], "--path", cfg["source"]["project"], "--serve"]
        req = json.dumps({"id": 1, "method": "get_graph"}) + "\n"
        p = subprocess.run(cmd, input=req, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0)
        lines = [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{") and '"mm_rpc"' in l]
        self.assertTrue(lines[0]["result"]["ready"])
        self.assertEqual(lines[1]["error"]["code"], "no_graph")

    def test_batch_cli(self):
        with tempfile.TemporaryDirectory() as t:
            script = Path(t) / "req.jsonl"
            script.write_text("# comment\n" + json.dumps({"method": "load", "params": {"path": str(BRICKS)}}) + "\n"
                              + json.dumps({"method": "set_param", "params": {"node": "Nope", "name": "a", "value": 1}}) + "\n")
            p = subprocess.run([sys.executable, mm_client.__file__, "batch", str(script)], capture_output=True, text=True, timeout=120)
            out = [json.loads(l) for l in p.stdout.splitlines()]
            self.assertEqual(p.returncode, 1)
            self.assertTrue(out[0]["ok"])
            self.assertEqual(out[1]["error"]["code"], "unknown_node")


if __name__ == "__main__":
    unittest.main()
