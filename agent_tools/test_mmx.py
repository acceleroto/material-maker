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


if __name__ == "__main__":
    unittest.main()
