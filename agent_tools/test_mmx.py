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
        self.assertEqual(r, {"ok": True, "errors": [], "warnings": []})


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


if __name__ == "__main__":
    unittest.main()
