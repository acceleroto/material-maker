#!/usr/bin/env python3
"""Tests for mmx.py.  Run: python3 -m unittest agent_tools/test_mmx.py -v"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmx  # noqa: E402

EXAMPLES = sorted((mmx.REPO / "material_maker" / "examples").glob("*.ptex"))
BRICKS = mmx.REPO / "material_maker" / "examples" / "bricks.ptex"
MMX = str(Path(__file__).resolve().parent / "mmx.py")


def run_validate(path):
    p = subprocess.run([sys.executable, MMX, "validate", str(path)], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def codes(result):
    return {e["code"] for e in result["errors"]}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = mmx.Catalog.load()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def broken_copy(self, name, mutate):
        data = json.loads(BRICKS.read_text())
        mutate(data)
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps(data, indent=1))
        return path

    @staticmethod
    def node(data, name):
        return next(n for n in data["nodes"] if n["name"] == name)


class TestExamples(Base):
    def test_all_examples_pass(self):
        self.assertGreater(len(EXAMPLES), 40)
        for f in EXAMPLES:
            with self.subTest(example=f.name):
                r = mmx.validate_file(f, self.catalog)
                self.assertTrue(r["ok"], json.dumps(r["errors"][:3], indent=1))

    def test_cli_ok_exit_code(self):
        rc, r = run_validate(BRICKS)
        self.assertEqual(rc, 0)
        self.assertEqual({k: r[k] for k in ("ok", "errors", "warnings")}, {"ok": True, "errors": [], "warnings": []})
        self.assertIn("static", r["checks"])


class TestBrokenCopies(Base):
    def test_misspelled_type(self):
        path = self.broken_copy("bad_type.ptex", lambda d: self.node(d, "Perlin").update(type="perlinn"))
        rc, r = run_validate(path)
        self.assertEqual(rc, 1)
        self.assertFalse(r["ok"])
        self.assertEqual(codes(r), {"unknown_type"})
        self.assertIn("perlin", r["errors"][0]["hint"])

    def test_bad_input_port(self):
        def mutate(d):
            c = next(c for c in d["connections"] if c["to"] == "blend_0")
            c["to_port"] = 7  # blend has inputs 0..2
        rc, r = run_validate(self.broken_copy("bad_port.ptex", mutate))
        self.assertEqual(rc, 1)
        self.assertEqual(codes(r), {"bad_input_port"})
        self.assertIn("2 a f", r["errors"][0]["hint"])

    def test_bad_parameters(self):
        def mutate(d):
            self.node(d, "colorize_0")["parameters"]["gradiant"] = {}
            self.node(d, "blend_0")["parameters"]["blend_type"] = "multiply"
        rc, r = run_validate(self.broken_copy("bad_params.ptex", mutate))
        self.assertEqual(rc, 1)
        self.assertEqual(codes(r), {"unknown_parameter", "bad_parameter_type"})
        unknown = next(e for e in r["errors"] if e["code"] == "unknown_parameter")
        self.assertIn("gradient", unknown["hint"])


class TestChecks(Base):
    def check(self, mutate):
        return mmx.validate_file(self.broken_copy("t.ptex", mutate), self.catalog)

    def test_invalid_json(self):
        path = Path(self.tmp.name) / "bad.json.ptex"
        path.write_text('{"nodes": [}')
        rc, r = run_validate(path)
        self.assertEqual((rc, codes(r)), (1, {"invalid_json"}))

    def test_missing_node_and_duplicate_input(self):
        def mutate(d):
            c = next(c for c in d["connections"] if c["to"] == "blend_0")
            d["connections"].append(dict(c))
            d["connections"].append({"from": "nope", "from_port": 0, "to": "blend_0", "to_port": 2})
        self.assertEqual(codes(self.check(mutate)), {"input_multiply_connected", "unknown_node"})

    def test_port_type_mismatch(self):
        def mutate(d):
            d["nodes"].append({"name": "circle", "type": "sdcircle", "parameters": {}})
            d["connections"] = [c for c in d["connections"] if not (c["to"] == "blend_0" and c["to_port"] == 2)]
            d["connections"].append({"from": "circle", "from_port": 0, "to": "blend_0", "to_port": 2})
        self.assertEqual(codes(self.check(mutate)), {"port_type_mismatch"})

    def test_generic_ports(self):
        def mutate(d, size, port):
            d["nodes"].append({"name": "b2", "type": "blend2", "generic_size": size, "parameters": {}})
            d["connections"].append({"from": "Perlin", "from_port": 0, "to": "b2", "to_port": port})
        self.assertTrue(self.check(lambda d: mutate(d, 2, 4))["ok"])  # b, l1, a1, l2, a2
        self.assertEqual(codes(self.check(lambda d: mutate(d, 2, 5))), {"bad_input_port"})

    def test_subgraph_param_labels_and_override(self):
        params = {p["name"]: p for p in self.catalog.entries["normal_map"]["parameters"]}
        self.assertEqual(params["param1"]["label"], "Strength")

        def mutate(d):
            graph = self.node(d, "graph")
            self.node(graph, "Bricks")["parameters"]["rows"] = 4
        r = self.check(mutate)
        self.assertTrue(r["ok"])
        self.assertIn("overridden_parameter", {w["code"] for w in r["warnings"]})

    def test_nodes_md_size(self):
        self.assertLess(len(mmx.NODES_MD_PATH.read_text().splitlines()), mmx.NODES_MD_MAX_LINES)


# A stand-in for the Material Maker binary: FAKE_MM_MODE = ok (write the requested files),
# partial (skip the .mat), hang (sleep), badargs/loadfail/exportfail (exit 1/2/3), nojson (no summary).
# Gets the same argv as the real app; with --json (source mode) it prints parse_args.gd's summary line.
FAKE_MM = """#!/usr/bin/env python3
import json, os, sys, time
mode = os.environ.get("FAKE_MM_MODE", "ok")
args = sys.argv[1:]
want_json = "--json" in args
print("Exporting...", flush=True)
if mode == "hang":
    time.sleep(60)
out = args[args.index("-o") + 1]
codes = {"badargs": 1, "loadfail": 2, "exportfail": 3}
if mode in codes:
    print("ERROR: boom", file=sys.stderr)
    if want_json:
        print(json.dumps({"errors": ["boom"], "exit_code": codes[mode], "files": [], "materials": [],
                          "mm_cli": 1, "ok": False, "warnings": []}))
    sys.exit(codes[mode])
json.dump(args, open(os.path.join(out, "argv.json"), "w"))
stem = os.path.splitext(os.path.basename(args[-1]))[0]
files = []
for suf in ("_albedo.png", "_albedo.png.meta", "_metal_smoothness.png", "_metal_smoothness.png.meta",
            "_normal.png", "_normal.png.meta", "_height.png", "_height.png.meta",
            "_occlusion.png", "_occlusion.png.meta", ".mat"):
    if not (mode == "partial" and suf == ".mat"):
        files.append(os.path.join(out, stem + suf))
        open(files[-1], "w").write("x")
print("Done")
if want_json and mode != "nojson":
    size = int(args[args.index("--size") + 1]) if "--size" in args else 2048
    target = args[args.index("--target") + 1]
    print(json.dumps({"errors": [], "exit_code": 0, "files": files, "mm_cli": 1, "ok": True, "warnings": [],
                      "materials": [{"files": files, "input": args[-1], "ok": True, "size": size, "target": target}]}))
"""


class TestExportPlan(unittest.TestCase):
    def test_eval_condition(self):
        c = {"a_tex"}
        self.assertTrue(mmx.eval_condition("$(connected:a_tex)", c))
        self.assertFalse(mmx.eval_condition("$(connected:b_tex)", c))
        self.assertTrue(mmx.eval_condition("$(connected:b_tex) or $(connected:a_tex)", c))
        self.assertIsNone(mmx.eval_condition("$(param:x) == 1", c))
        self.assertIsNone(mmx.eval_condition("__import__('os')", c))

    def test_expected_files(self):
        cfg = mmx.load_config()
        r = mmx.expected_files(BRICKS, "/o", "Unity/URP", cfg)
        names = {Path(f).name for f in r["required"]}
        self.assertIn("bricks.mat", names)
        self.assertIn("bricks_metal_smoothness.png", names)
        self.assertNotIn("bricks_emission.png", names)  # emission input unconnected
        # improved_brick has no roughness/metallic input -> no metal_smoothness map (seen in Phase 0)
        r = mmx.expected_files(BRICKS.with_name("improved_brick.ptex"), "/o", "Unity/URP", cfg)
        self.assertNotIn("improved_brick_metal_smoothness.png", {Path(f).name for f in r["required"]})
        r = mmx.expected_files(BRICKS, "/o", "Unity/UPR", cfg)
        self.assertIn("Unity/URP", r["error"])


class TestExportRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        fake = t / "fake_mm"
        fake.write_text(FAKE_MM)
        fake.chmod(0o755)
        cfg = mmx.load_config()
        cfg["mode"] = "release"  # independent of mmx.toml
        cfg["release"]["binary"] = str(fake)
        cfg["timeout"] = 3
        self.cfg, self.t = cfg, t
        self.addCleanup(self.tmp.cleanup)

    def export(self, mode, ptex=BRICKS):
        import os
        os.environ["FAKE_MM_MODE"] = mode
        try:
            return mmx.run_export(ptex, self.t / "out", cfg=self.cfg)
        finally:
            del os.environ["FAKE_MM_MODE"]

    def test_ok_and_stale_outputs_removed(self):
        (self.t / "out").mkdir()
        (self.t / "out" / "bricks.mat").write_text("old")
        r = self.export("ok")
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(r["files"]), 11)
        self.assertEqual((self.t / "out" / "bricks.mat").read_text(), "x")
        self.assertTrue((self.t / "out" / "export.log").read_text().startswith("Exporting"))
        self.assertEqual(json.loads((self.t / "out" / mmx.RESULT_NAME).read_text())["ok"], True)

    def test_missing_file_detected(self):
        r = self.export("partial")
        self.assertFalse(r["ok"])
        self.assertEqual(r["missing"], ["bricks.mat"])

    def test_timeout(self):
        r = self.export("hang")
        self.assertEqual((r["ok"], r["error"]), (False, "timeout"))
        self.assertLess(r["seconds"], 10)

    def test_validation_refuses(self):
        data = json.loads(BRICKS.read_text())
        next(n for n in data["nodes"] if n["name"] == "Perlin")["type"] = "perlinn"
        bad = self.t / "bad.ptex"
        bad.write_text(json.dumps(data))
        r = self.export("ok", bad)
        self.assertEqual((r["ok"], r["stage"]), (False, "validate"))
        self.assertFalse((self.t / "out" / "export.log").exists())

    def test_iter_dirs_and_wait(self):
        runs = self.t / "runs"
        self.assertEqual(mmx.next_iter_dir("r", runs).name, "iter_001")
        self.assertEqual(mmx.next_iter_dir("r", runs).name, "iter_002")
        d = runs / "r" / "iter_002"
        mmx._write_json(d / mmx.RESULT_NAME, {"ok": True})
        self.assertEqual(mmx.wait_for_result(run_name="r", runs_dir=runs, timeout=1), {"ok": True})
        self.assertFalse(mmx.wait_for_result(self.t / "nowhere", timeout=0.2)["ok"])

    def test_nested_run_name(self):
        self.assertEqual(mmx.next_iter_dir("1.3/desert", self.t).parent, self.t / "1.3" / "desert")
        for bad in ("../x", "a/../b", "/abs", "a//b", "a/"):
            with self.assertRaises(SystemExit):
                mmx.run_iteration(self.t / "none.ptex", bad, runs_dir=self.t)


class TestExportSource(TestExportRun):
    """Source mode: Godot + repo, parse_args.gd's --json summary and exit codes."""
    def setUp(self):
        super().setUp()
        self.cfg["mode"] = "source"
        self.cfg["source"]["godot"] = self.cfg["release"]["binary"]
        self.cfg["release"]["binary"] = "/nonexistent"

    def test_command(self):
        cmd = mmx.export_command(self.cfg, "/a/b.ptex", "/o", "Unity/URP", 512)
        self.assertEqual(cmd[1:3], ["--path", self.cfg["source"]["project"]])
        for flag in ("--export-material", "--json", "--strict-target"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--size") + 1], "512")
        self.assertEqual(cmd[-3:], ["-o", "/o", "/a/b.ptex"])
        self.assertNotIn("--size", mmx.export_command(self.cfg, "/a/b.ptex", "/o", "Unity/URP"))
        self.cfg["mode"] = "release"
        with self.assertRaises(SystemExit):
            mmx.export_command(self.cfg, "/a/b.ptex", "/o", "Unity/URP", 512)

    def test_summary_and_size(self):
        import os
        os.environ["FAKE_MM_MODE"] = "ok"
        try:
            r = mmx.run_export(BRICKS, self.t / "out", cfg=self.cfg, size=256)
        finally:
            del os.environ["FAKE_MM_MODE"]
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["mm"]["targets"], ["Unity/URP"])
        self.assertEqual(r["mm"]["sizes"], [256])
        self.assertEqual(r["mm"]["files_written"], 11)

    def test_exit_codes(self):
        for mode, msg in (("badargs", "bad arguments"), ("loadfail", "load/parse failure"),
                          ("exportfail", "export failure")):
            r = self.export(mode)
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"], msg + ": boom")
            self.assertIn("ERROR: boom", r["log_errors"])

    def test_missing_summary(self):
        r = self.export("nojson")
        self.assertFalse(r["ok"])
        self.assertIn("no JSON summary", r["error"])

    def test_parse_mm_summary(self):
        self.assertIsNone(mmx.parse_mm_summary("noise\n{not json\n"))
        self.assertEqual(mmx.parse_mm_summary('x\n{"mm_cli": 1, "ok": true}\nWARNING: leak')["ok"], True)


try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


@unittest.skipUnless(HAVE_PIL, "needs Pillow (run with agent_tools/.venv/bin/python)")
class TestSheet(unittest.TestCase):
    def test_lit_light_from_top_left(self):
        from PIL import Image
        albedo = Image.new("RGB", (8, 8), (200, 200, 200))
        def lit(rgb):  # Unity/OpenGL normal: G > 128 faces up (towards the image top)
            return mmx.lit_preview(albedo, Image.new("RGB", (8, 8), rgb), size=8).getpixel((4, 4))[0]
        self.assertGreater(lit((128, 200, 230)), lit((128, 56, 230)))  # up-facing brighter than down
        self.assertGreater(lit((56, 128, 230)), lit((200, 128, 230)))  # left-facing brighter than right

    def test_sheet(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            Image.new("RGB", (64, 64), (200, 50, 50)).save(Path(t) / "m_albedo.png")
            Image.new("RGB", (64, 64), (128, 128, 255)).save(Path(t) / "m_normal.png")
            Image.new("RGBA", (64, 64), (255, 0, 0, 64)).save(Path(t) / "m_metal_smoothness.png")
            r = mmx.make_sheet(t)
            self.assertTrue(Path(r["sheet"]).exists())
            labels = [s.split()[0] for s in r["tiles"]]
            self.assertEqual(labels, ["lit", "lit", "albedo", "normal", "roughness", "metallic"])
            self.assertIn("min 0.75", r["tiles"][4])  # roughness = 1 - smoothness(64/255)
            self.assertEqual(mmx.make_sheet(t)["sources"].keys(), r["sources"].keys())  # ignores sheet.png
            self.assertIsNone(r["preview"])

    def test_sheet_preview_top_row(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "out"
            out.mkdir()
            Image.new("RGB", (64, 64), (200, 50, 50)).save(out / "m_albedo.png")
            plain = Image.open(mmx.make_sheet(out, Path(t) / "plain.png", tile=64)["sheet"])
            Image.new("RGB", (200, 100), (0, 255, 0)).save(Path(t) / mmx.PREVIEW_NAME)  # iter dir = out/..
            r = mmx.make_sheet(out, Path(t) / "with.png", tile=64)
            self.assertEqual(r["preview"], str(Path(t) / mmx.PREVIEW_NAME))
            self.assertNotIn("preview", " ".join(r["sources"].values()))
            sheet = Image.open(r["sheet"])
            self.assertEqual(sheet.width, plain.width)
            self.assertEqual(sheet.height, plain.height + 128 + 22)  # 2:1 preview at sheet width 256, + label
            self.assertEqual(sheet.getpixel((128, 30 + 22 + 64)), (0, 255, 0))  # top row is the preview
            # a preview inside the export dir is not mistaken for a map
            Image.new("RGB", (200, 100), (0, 0, 255)).save(out / mmx.PREVIEW_NAME)
            r = mmx.make_sheet(out, Path(t) / "inside.png", tile=64)
            self.assertEqual(r["preview"], str(out / mmx.PREVIEW_NAME))
            self.assertEqual(list(r["sources"]), ["albedo"])


# A stand-in for Godot running cli_inspect.gd: prints the canned summary in $FAKE_ENGINE_SUMMARY
# (or nothing with FAKE_ENGINE_MODE=nojson, or hangs with FAKE_ENGINE_MODE=hang).
FAKE_ENGINE = """#!/usr/bin/env python3
import json, os, sys, time
mode = os.environ.get("FAKE_ENGINE_MODE", "ok")
if mode == "hang":
    time.sleep(60)
print("Godot Engine v4 - noise")
if mode != "nojson":
    s = json.loads(os.environ["FAKE_ENGINE_SUMMARY"])
    s["argv"] = sys.argv[1:]
    print(json.dumps(s))
sys.exit(int(os.environ.get("FAKE_ENGINE_EXIT", "0")))
"""


def engine_summary(errors=(), warnings=(), ok=None):
    ok = not errors if ok is None else ok
    return {"mm_cli": 1, "mode": "validate", "ok": ok, "exit_code": 0 if ok else 4, "errors": [], "warnings": [],
            "files": [{"input": "x.ptex", "ok": ok, "nodes": 3, "outputs_checked": 5,
                       "errors": list(errors), "warnings": list(warnings)}]}


class TestEngineValidate(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        fake = Path(self.tmp.name) / "fake_godot"
        fake.write_text(FAKE_ENGINE)
        fake.chmod(0o755)
        self.cfg = mmx.load_config()
        self.cfg["mode"] = "source"
        self.cfg["source"]["godot"] = str(fake)
        self.cfg["timeout"] = 3
        self.env = {}
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in self.env])

    def setenv(self, **kw):
        import os
        for k, v in kw.items():
            os.environ[k] = v if isinstance(v, str) else json.dumps(v)
            self.env[k] = True

    def test_engine_errors_are_merged(self):
        err = {"code": "shader_compile_error", "graph_path": "/", "node": "custom", "message": "custom: bad"}
        self.setenv(FAKE_ENGINE_SUMMARY=engine_summary([err]), FAKE_ENGINE_EXIT="4")
        r = mmx.validate_full(BRICKS, self.cfg)
        self.assertFalse(r["ok"])
        self.assertEqual(r["checks"], ["static", "engine"])
        self.assertEqual([e["code"] for e in r["errors"]], ["shader_compile_error"])
        self.assertEqual(r["errors"][0]["source"], "engine")
        self.assertEqual(r["engine"]["outputs_checked"], 5)

    def test_engine_argv(self):
        self.setenv(FAKE_ENGINE_SUMMARY=engine_summary())
        summary, info = mmx.run_engine(["--validate", "/abs/x.ptex"], self.cfg)
        self.assertEqual(summary["argv"], ["--path", self.cfg["source"]["project"], "--validate", "/abs/x.ptex", "--json"])
        self.assertEqual(info["exit_code"], 0)

    def test_clean(self):
        self.setenv(FAKE_ENGINE_SUMMARY=engine_summary())
        r = mmx.validate_full(BRICKS, self.cfg)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checks"], ["static", "engine"])

    def test_fast_and_config_skip_engine(self):
        self.setenv(FAKE_ENGINE_MODE="hang")
        self.assertEqual(mmx.validate_full(BRICKS, self.cfg, fast=True)["checks"], ["static"])
        self.cfg["validate_engine"] = False
        self.assertEqual(mmx.validate_full(BRICKS, self.cfg)["checks"], ["static"])

    def test_static_errors_skip_engine(self):
        self.setenv(FAKE_ENGINE_MODE="hang")
        with tempfile.NamedTemporaryFile("w", suffix=".ptex", delete=False) as f:
            f.write("{not json")
        r = mmx.validate_full(f.name, self.cfg)
        Path(f.name).unlink()
        self.assertFalse(r["ok"])
        self.assertEqual(r["checks"], ["static"])
        self.assertIn("engine_check_skipped", [w["code"] for w in r["warnings"]])

    def test_engine_unavailable_is_a_warning(self):
        for mode in ("nojson", "hang"):
            with self.subTest(mode=mode):
                self.setenv(FAKE_ENGINE_MODE=mode, FAKE_ENGINE_SUMMARY=engine_summary())
                r = mmx.validate_full(BRICKS, self.cfg)
                self.assertTrue(r["ok"])
                self.assertEqual(r["checks"], ["static"])
                self.assertEqual([w["code"] for w in r["warnings"]][-1:], ["engine_unavailable"])
        self.cfg["mode"] = "release"
        r = mmx.validate_full(BRICKS, self.cfg)
        self.assertIn("source", r["warnings"][-1]["message"])


class TestNodePreview(unittest.TestCase):
    setUp = TestEngineValidate.setUp  # fake engine (only its fixtures, not its tests)
    setenv = TestEngineValidate.setenv

    def summary(self, ok=True, errors=()):
        return {"mm_cli": 1, "mode": "render-output", "ok": ok, "exit_code": 0 if ok else 1, "errors": list(errors),
                "warnings": [], "type": "perlin", "output_type": "f", "outputs": [{"index": 0, "type": "f", "label": ""}]}

    def test_default_path(self):
        p = mmx.node_preview_path("/x/bricks.ptex", "graph/Bricks", 2, runs_dir="/r")
        self.assertEqual(p, Path("/r/node_preview/bricks/graph__Bricks_p2.png"))

    def test_argv_and_missing_file(self):
        out = Path(self.tmp.name) / "sub" / "n.png"
        self.setenv(FAKE_ENGINE_SUMMARY=self.summary())
        r = mmx.node_preview(BRICKS, "Perlin", 1, 256, out, self.cfg)
        # the fake engine writes no file: success must not be reported
        self.assertFalse(r["ok"])
        self.assertIn("was not written", r["errors"][0])
        self.assertEqual(r["output_type"], "f")
        self.assertTrue(out.parent.is_dir())

    def test_ok_when_file_written(self):
        out = Path(self.tmp.name) / "n.png"
        self.setenv(FAKE_ENGINE_SUMMARY=self.summary())
        orig = mmx.run_engine

        def fake_run(args, cfg=None, timeout=None):
            self.assertEqual(args, ["--render-output", str(BRICKS.resolve()), "--node", "Perlin", "--port", "0",
                                    "--size", "64", "-o", str(out.resolve())])
            out.write_bytes(b"png")
            return orig(args, cfg, timeout)
        mmx.run_engine = fake_run
        self.addCleanup(setattr, mmx, "run_engine", orig)
        r = mmx.node_preview(BRICKS, "Perlin", 0, 64, out, self.cfg)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["file"], str(out.resolve()))

    def test_engine_error(self):
        out = Path(self.tmp.name) / "n.png"
        out.write_bytes(b"stale")
        self.setenv(FAKE_ENGINE_SUMMARY=self.summary(False, ["no node nope in bricks.ptex"]), FAKE_ENGINE_EXIT="1")
        r = mmx.node_preview(BRICKS, "nope", 0, 64, out, self.cfg)
        self.assertFalse(r["ok"])
        self.assertFalse(out.exists())  # stale image removed
        self.assertEqual(r["errors"], ["no node nope in bricks.ptex"])

    def test_no_summary(self):
        self.setenv(FAKE_ENGINE_MODE="nojson", FAKE_ENGINE_SUMMARY="{}")
        r = mmx.node_preview(BRICKS, "Perlin", 0, 64, Path(self.tmp.name) / "n.png", self.cfg)
        self.assertFalse(r["ok"])
        self.assertIn("no JSON summary", r["errors"][0])


class TestRenderPreview(unittest.TestCase):
    setUp = TestEngineValidate.setUp
    setenv = TestEngineValidate.setenv

    def test_argv_and_defaults(self):
        out = Path(self.tmp.name) / "p.png"
        seen = []
        orig = mmx.run_engine

        def fake_run(args, cfg=None, timeout=None):
            seen.append(args)
            out.write_bytes(b"png")
            return {"mm_cli": 1, "ok": True, "errors": [], "warnings": [], "env": "Studio", "width": 1024,
                    "height": 512, "meshes": ["sphere", "plane"]}, {"seconds": 1.0, "exit_code": 0}
        mmx.run_engine = fake_run
        self.addCleanup(setattr, mmx, "run_engine", orig)
        r = mmx.render_preview(BRICKS, out, cfg=self.cfg)
        self.assertTrue(r["ok"], r)
        self.assertEqual(seen[0], ["--render-preview", str(BRICKS.resolve()), "--mesh", "sphere+plane", "--env", "Studio",
                                   "--size", "512", "-o", str(out.resolve())])
        self.assertEqual((r["width"], r["height"], r["env"]), (1024, 512, "Studio"))
        mmx.render_preview(BRICKS, out, mesh="cube", env="1", size=64, cfg=self.cfg)
        self.assertEqual(seen[1][3:8], ["cube", "--env", "1", "--size", "64"])

    def test_engine_error(self):
        self.setenv(FAKE_ENGINE_SUMMARY={"mm_cli": 1, "ok": False, "errors": ["unknown --env x"], "warnings": []},
                    FAKE_ENGINE_EXIT="1")
        r = mmx.render_preview(BRICKS, Path(self.tmp.name) / "p.png", env="x", cfg=self.cfg)
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"], ["unknown --env x"])


class TestRunWithPreview(unittest.TestCase):
    """run_iteration with export and preview stubbed: the preview lands on top of the sheet, a failed
    preview only warns."""
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = mmx.load_config()
        self.cfg["mode"] = "source"
        self.calls = []

        def fake_export(ptex, out_dir, *a, **kw):
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (32, 32), (200, 50, 50)).save(Path(out_dir) / "x_albedo.png")
            return {"ok": True, "files": []}

        def fake_preview(ptex, out, **kw):
            self.calls.append(Path(out))
            if self.preview_ok:
                Image.new("RGB", (64, 32), (0, 255, 0)).save(out)
                return {"ok": True, "file": str(out), "meshes": ["sphere", "plane"], "env": "Studio", "errors": []}
            return {"ok": False, "file": None, "errors": ["boom"]}
        for name, f in (("run_export", fake_export), ("render_preview", fake_preview)):
            self.addCleanup(setattr, mmx, name, getattr(mmx, name))
            setattr(mmx, name, f)

    def run_it(self, **kw):
        return mmx.run_iteration(BRICKS, "r", cfg=self.cfg, runs_dir=self.tmp.name, **kw)

    def test_preview_on_top(self):
        self.preview_ok = True
        r = self.run_it()
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.calls, [Path(r["iter_dir"]) / mmx.PREVIEW_NAME])
        self.assertTrue(r["preview"]["ok"])
        from PIL import Image
        self.assertEqual(Image.open(r["sheet"]).getpixel((100, 30 + 22 + 50)), (0, 255, 0))

    def test_preview_failure_warns(self):
        self.preview_ok = False
        r = self.run_it()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["warnings"], ["3D preview failed: boom"])
        self.assertTrue(Path(r["sheet"]).exists())

    def test_disabled(self):
        self.preview_ok = True
        self.run_it(preview=False)
        self.cfg["preview_3d"] = False
        self.run_it()
        self.cfg["preview_3d"], self.cfg["mode"] = True, "release"
        self.run_it()
        self.assertEqual(self.calls, [])


class TestEngineCatalogMerge(unittest.TestCase):
    def test_merge(self):
        static = mmx.Catalog({
            "bricks3": {"type": "bricks3", "kind": "shader", "label": "Bricks", "shortdesc": "", "longdesc": "",
                        "parameters": [{"name": "rows", "type": "float"}], "inputs": [], "outputs": [],
                        "source": "addons/material_maker/nodes/bricks3.mmg", "category": "Uncategorized"}})
        listing = {"items": [
            {"tree_item": "Pattern/Bricks", "category": "Pattern", "type": "bricks3", "inline_graph": False,
             "keywords": ["wall"]},
            {"tree_item": "Pattern/Bricks/Tiles", "category": "Pattern", "type": "bricks3", "inline_graph": False,
             "keywords": ["tile"]},
            {"tree_item": "Workflow/Materials/Wood", "category": "Workflow", "type": "graph", "inline_graph": True}]}
        described = {"nodes": [
            {"type": "bricks3", "generator": "MMGenShader", "label": "Bricks", "shortdesc": "Bricks!",
             "parameters": [{"name": "rows", "type": "float", "default": 6, "min": 1, "max": 64, "label": "Rows"},
                            {"name": "pattern", "type": "enum", "default": 0,
                             "values": [{"name": "Running Bond", "value": "rb"}]}],
             "inputs": [{"name": "mortar_map", "type": "f", "label": "6:"}],
             "outputs": [{"type": "f", "f": "$(name_uv).x"}, {"type": "fill"}]},
            {"type": "newtype", "generator": "MMGenGraph", "label": "New", "parameters": [], "inputs": [], "outputs": []}]}
        entries, diffs = mmx.merge_engine_catalog(static, listing, described)
        b = entries["bricks3"]
        self.assertEqual(b["shortdesc"], "Bricks!")
        self.assertEqual([p["name"] for p in b["parameters"]], ["rows", "pattern"])
        self.assertEqual(b["parameters"][1]["values"], ["Running Bond"])
        self.assertEqual(b["outputs"], [{"index": 0, "type": "f"}, {"index": 1, "type": "fill"}])
        self.assertEqual(b["library"], ["Pattern/Bricks", "Pattern/Bricks/Tiles"])
        self.assertEqual((b["category"], b["section"]), ("Pattern", "Pattern"))
        self.assertEqual(b["keywords"], ["tile", "wall"])
        self.assertTrue(b["in_library"])
        self.assertEqual(b["source"], "addons/material_maker/nodes/bricks3.mmg")
        self.assertEqual(entries["newtype"]["kind"], "graph")
        self.assertFalse(entries["newtype"]["in_library"])
        self.assertEqual(diffs, [{"type": "bricks3", "fields": ["parameters", "inputs", "outputs"]}])

    def test_generated_catalog_is_engine_based(self):
        data = json.loads(mmx.CATALOG_PATH.read_text())
        self.assertIn("engine", data["generated_by"])
        self.assertEqual(data["types"]["gaussian_blur"]["parameters"][1]["default"], 4.8)  # graph value, not def
        self.assertEqual(data["types"]["reroute"]["inputs"][0]["type"], "any")


def godot_available():
    import os
    cfg = mmx.load_config()
    return (cfg["mode"] == "source" and Path(cfg["source"]["godot"]).exists()
            and not os.environ.get("MMX_SKIP_ENGINE"))


@unittest.skipUnless(godot_available(), "needs Godot + mode = source (set MMX_SKIP_ENGINE=1 to skip)")
class TestRealEngine(Base):
    """Runs the real engine (~1 min). Fixtures are broken copies of bricks.ptex."""

    def engine(self, *args, timeout=600):
        summary, info = mmx.run_engine(list(args), timeout=timeout)
        self.assertIsNotNone(summary, info)
        return summary, info

    def test_examples(self):
        summary, info = self.engine("--validate", *[str(f) for f in EXAMPLES])
        self.assertEqual(len(summary["files"]), len(EXAMPLES))
        for f in summary["files"]:
            with self.subTest(example=Path(f["input"]).name):
                if Path(f["input"]).name == "doc_tools.ptex":
                    # MM's documentation helper graph really has GLSL errors ('input' is a reserved word)
                    self.assertEqual({e["code"] for e in f["errors"]}, {"shader_compile_error"})
                else:
                    self.assertTrue(f["ok"], json.dumps(f["errors"][:2]))
                    self.assertGreater(f["outputs_checked"], 0)

    def test_broken(self):
        def custom_bad(d):
            m = next(n for n in json.loads((BRICKS.parent / "mandelbrot.ptex").read_text())["nodes"] if "shader_model" in n)
            m["name"] = "custom_bad"
            out = m["shader_model"]["outputs"][0]
            out[next(k for k in out if k in ("f", "rgb", "rgba"))] = "undefined_thing_xyz($(uv))"
            d["nodes"].append(m)
            d["connections"].append({"from": "custom_bad", "from_port": 0, "to": "colorize_0", "to_port": 0})
            d["connections"] = [c for c in d["connections"] if not (c["to"] == "colorize_0" and c["from"] == "Perlin")]

        files = {
            "unknown_type": self.broken_copy("e_type.ptex", lambda d: self.node(d, "Perlin").update(type="perlinn")),
            "bad_output_port": self.broken_copy("e_port.ptex", lambda d: d["connections"].append(
                {"from": "Perlin", "from_port": 7, "to": "blend_2", "to_port": 0})),
            "port_type_mismatch": self.broken_copy("e_mismatch.ptex", lambda d: (
                d["nodes"].append({"name": "bx", "type": "bricks3", "parameters": {}}),
                d["connections"].append({"from": "bx", "from_port": 1, "to": "blend_2", "to_port": 0}))),
            "shader_compile_error": self.broken_copy("e_glsl.ptex", custom_bad),
        }
        summary, info = self.engine("--validate", *[str(f) for f in files.values()])
        self.assertEqual(info["exit_code"], 4)
        self.assertFalse(summary["ok"])
        for (code, path), f in zip(files.items(), summary["files"]):
            with self.subTest(code=code):
                self.assertFalse(f["ok"])
                self.assertIn(code, {e["code"] for e in f["errors"]}, json.dumps(f["errors"]))
        glsl = next(e for e in summary["files"][3]["errors"] if e["code"] == "shader_compile_error")
        self.assertEqual(glsl["node"], "custom_bad")
        self.assertIn("undefined_thing_xyz", glsl["message"])

    def test_describe_and_list(self):
        summary, _ = self.engine("--describe-node", "bricks3", "nosuch")
        self.assertEqual(summary["exit_code"], 2)
        self.assertEqual([n["type"] for n in summary["nodes"]], ["bricks3"])
        summary, _ = self.engine("--list-nodes")
        self.assertTrue(summary["ok"])
        self.assertIn("Pattern/Bricks", {i["tree_item"] for i in summary["items"]})

    def test_render_output(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            r = mmx.node_preview(BRICKS, "graph/Bricks", 0, 128, Path(t) / "b.png")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["type"], "bricks")
            self.assertEqual(Image.open(r["file"]).size, (128, 128))
            r = mmx.node_preview(BRICKS, "Perlin", 3, 128, Path(t) / "p.png")
            self.assertFalse(r["ok"])
            self.assertIn("no port 3", r["errors"][0])

    def test_render_preview(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            r = mmx.render_preview(BRICKS, Path(t) / "p.png", mesh="sphere", size=128)
            self.assertTrue(r["ok"], r)
            im = Image.open(r["file"]).convert("RGB")
            self.assertEqual(im.size, (128, 128))
            self.assertNotEqual(im.getpixel((64, 64)), im.getpixel((2, 2)))  # something in front of the background
            r = mmx.render_preview(BRICKS, Path(t) / "q.png", env="nope", size=64)
            self.assertFalse(r["ok"])
            self.assertIn("unknown --env nope", r["errors"][0])

    def test_mmx_validate_cli(self):
        rc, r = run_validate(BRICKS)
        self.assertEqual(rc, 0)
        self.assertEqual(r["checks"], ["static", "engine"])


if __name__ == "__main__":
    unittest.main()
