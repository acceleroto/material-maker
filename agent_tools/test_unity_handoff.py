#!/usr/bin/env python3
"""Tests for unity_handoff.py and `mmx to-unity` (no Unity needed; a fake editor stands in).
Run: python3 -m unittest agent_tools/test_unity_handoff.py -v"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmx  # noqa: E402
import unity_handoff as uh  # noqa: E402

URP_ASSET = """%YAML 1.1
--- !u!114 &11400000
MonoBehaviour:
  m_Script: {fileID: 11500000, guid: bf2edee5c58d82540a51f03df9d42094, type: 3}
  m_Name: PC_RPAsset
  m_RendererDataList:
"""
HDRP_ASSET = """--- !u!114 &11400000
MonoBehaviour:
  m_Script: {fileID: 11500000, guid: 0cf1dab834d4ec34195b920ea7bbf9ec, type: 3}
  m_RenderPipelineSettings:
"""


def make_project(root, rp_asset=None, packages=(), quality_only=False):
    root = Path(root)
    (root / "Assets" / "Settings").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "Packages").mkdir()
    (root / "Packages" / "manifest.json").write_text(json.dumps({"dependencies": {p: "1.0.0" for p in packages}}))
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.5.5f1\n")
    guid = "4b83569d67af61e458304325a23e5dfd"
    ref = "{fileID: 11400000, guid: %s, type: 2}" % guid if rp_asset else "{fileID: 0}"
    gfx_ref = "{fileID: 0}" if quality_only else ref
    (root / "ProjectSettings" / "GraphicsSettings.asset").write_text("  m_CustomRenderPipeline: %s\n" % gfx_ref)
    (root / "ProjectSettings" / "QualitySettings.asset").write_text(
        "  - name: PC\n    customRenderPipeline: %s\n" % ref)
    if rp_asset:
        (root / "Assets" / "Settings" / "RP.asset").write_text(rp_asset)
        (root / "Assets" / "Settings" / "RP.asset.meta").write_text("fileFormatVersion: 2\nguid: %s\n" % guid)
    return root


def stage_export(d, name, guids, maps=("albedo", "normal")):
    """Fake MM Unity export: <name>.mat referencing <name>_<map>.png via the given guids."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    mat = ["Material:", "  m_Name: %s" % name, "  m_SavedProperties:", "    m_TexEnvs:"]
    for m, g in zip(maps, guids):
        (d / ("%s_%s.png" % (name, m))).write_bytes(b"png-" + m.encode())
        (d / ("%s_%s.png.meta" % (name, m))).write_text(
            "fileFormatVersion: 2\nguid: %s\nTextureImporter:\n\tsRGBTexture: %d\n" % (g, m != "normal"))
        mat += ["    - _%sMap:" % m, "        m_Texture: {fileID: 2800000, guid: %s, type: 3}" % g]
    (d / (name + ".mat")).write_text("\n".join(mat) + "\n")
    (d / "export.log").write_text("")
    return d


class TestDetect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_urp(self):
        r = uh.detect_pipeline(make_project(self.t / "p", URP_ASSET, [uh.URP_PACKAGE]))
        self.assertEqual((r["pipeline"], r["target"]), ("URP", "Unity/URP"))
        self.assertEqual(r["assets"][0]["path"], "Assets/Settings/RP.asset")

    def test_hdrp(self):
        r = uh.detect_pipeline(make_project(self.t / "p", HDRP_ASSET, [uh.HDRP_PACKAGE]))
        self.assertEqual(r["target"], "Unity/HDRP")

    def test_quality_level_only(self):
        r = uh.detect_pipeline(make_project(self.t / "p", URP_ASSET, [uh.URP_PACKAGE], quality_only=True))
        self.assertEqual(r["target"], "Unity/URP")

    def test_builtin(self):
        # URP package installed but no pipeline asset assigned: Built-in renders
        r = uh.detect_pipeline(make_project(self.t / "p", None, [uh.URP_PACKAGE]))
        self.assertEqual((r["pipeline"], r["target"]), ("Built-in", "Unity/3D"))

    def test_unknown_asset_falls_back_to_package(self):
        p = make_project(self.t / "p", URP_ASSET, [uh.HDRP_PACKAGE])
        (p / "Assets" / "Settings" / "RP.asset.meta").unlink()  # asset lives somewhere we can't see
        r = uh.detect_pipeline(p)
        self.assertEqual(r["target"], "Unity/HDRP")
        self.assertIn("package", r["source"])

    def test_not_a_project(self):
        with self.assertRaises(uh.HandoffError):
            uh.check_project(self.t)

    def test_names(self):
        for ok in ("Bricks", "mossy_roof-2", "A"):
            self.assertEqual(uh.check_name(ok), ok)
        for bad in ("", "a b", "../x", "_x", "x/y", "é", "a" * 65):
            with self.assertRaises(uh.HandoffError, msg=bad):
                uh.check_name(bad)


class TestEditorProcesses(unittest.TestCase):
    def test_match(self):
        u = "/Applications/Unity/Hub/Editor/6000.5.5f1/Unity.app/Contents/MacOS/Unity"
        proj = "/tmp/My Proj"
        ps = "\n".join([
            "10 %s -createproject /tmp/My Proj -cloneFromTemplate /x.tgz" % u,
            "11 %s -projectPath /tmp/My Proj -logFile x" % u,
            "12 %s -adb2 -batchMode -name AssetImportWorker1 -projectPath /tmp/My Proj" % u,
            "13 /bin/zsh -c python3 x.py --unity %s --project /tmp/My Proj" % u,
            "14 %s -projectPath /tmp/My Proj2 -logFile y" % u,
            "15 /Applications/Unity Hub.app/Contents/MacOS/Unity Hub",
        ])
        self.assertEqual(uh.editor_processes(proj, ps), [10, 11])


class TestSync(unittest.TestCase):
    G1 = ["11111111111111111111111111111111", "22222222222222222222222222222222"]
    G2 = ["33333333333333333333333333333333", "44444444444444444444444444444444"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.dest = self.t / "proj" / "Assets" / "Materials" / "Generated" / "Rock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_export(self):
        r = uh.sync_into_project(stage_export(self.t / "s1", "Rock", self.G1), self.dest, "Rock")
        self.assertEqual(r["kept_guids"], [])
        self.assertEqual(len(r["new_guids"]), 2)
        self.assertNotIn("export.log", r["files"])
        self.assertFalse((self.dest / "export.log").exists())
        meta = (self.dest / "Rock.mat.meta").read_text()
        self.assertIn("guid: " + r["material_guid"], meta)
        self.assertIn("mainObjectFileID: 2100000", meta)

    def test_reexport_keeps_guids(self):
        r1 = uh.sync_into_project(stage_export(self.t / "s1", "Rock", self.G1), self.dest, "Rock")
        r2 = uh.sync_into_project(stage_export(self.t / "s2", "Rock", self.G2), self.dest, "Rock")
        self.assertEqual(r2["kept_guids"], ["Rock_albedo.png", "Rock_normal.png"])
        self.assertEqual(r1["material_guid"], r2["material_guid"])
        mat = (self.dest / "Rock.mat").read_text()
        for g in self.G1:
            self.assertIn(g, mat)
        for g in self.G2:
            self.assertNotIn(g, mat)
            self.assertNotIn(g, "".join(f.read_text() for f in self.dest.glob("*.meta")))
        self.assertEqual((self.dest / "Rock_albedo.png").read_bytes(), b"png-albedo")

    def test_stale_maps_removed_others_kept(self):
        uh.sync_into_project(stage_export(self.t / "s1", "Rock", self.G1), self.dest, "Rock")
        (self.dest / "notes.txt").write_text("user file")
        (self.dest / "Rocky_albedo.png").write_text("other material")
        r = uh.sync_into_project(stage_export(self.t / "s2", "Rock", self.G2[:1], maps=("albedo",)), self.dest, "Rock")
        self.assertEqual(r["removed"], ["Rock_normal.png", "Rock_normal.png.meta"])
        self.assertTrue((self.dest / "notes.txt").exists())
        self.assertTrue((self.dest / "Rocky_albedo.png").exists())

    def test_texture_metas(self):
        maps = ("albedo", "normal", "metal_smoothness", "occlusion")
        g = ["%032d" % i for i in range(4)]
        stage = stage_export(self.t / "s1", "Rock", g, maps=maps)
        # a real PNG header for the albedo: 3000x1000 → max size 4096
        (stage / "Rock_albedo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (3000).to_bytes(4, "big")
                                                + (1000).to_bytes(4, "big") + b"rest")
        r = uh.sync_into_project(stage, self.dest, "Rock")
        tx = r["textures"]
        self.assertEqual({k: (v["texture_type"], v["srgb"]) for k, v in tx.items()},
                         {"Rock_albedo.png": (0, 1), "Rock_normal.png": (1, 0),
                          "Rock_metal_smoothness.png": (0, 0), "Rock_occlusion.png": (0, 0)})
        self.assertEqual(tx["Rock_albedo.png"]["max_size"], 4096)
        self.assertEqual(tx["Rock_normal.png"]["max_size"], 2048)  # no PNG header → 2048
        for i, m in enumerate(maps):
            text = (self.dest / ("Rock_%s.png.meta" % m)).read_text()
            self.assertNotIn("\t", text)
            self.assertIn("guid: %s\n" % g[i], text)
            self.assertIn("    sRGBTexture: %d\n" % (m == "albedo"), text)
        self.assertIn("  textureType: 1\n", (self.dest / "Rock_normal.png.meta").read_text())
        self.assertIn("  maxTextureSize: 4096\n", (self.dest / "Rock_albedo.png.meta").read_text())

    def test_texture_settings_roles(self):
        self.assertEqual(uh.texture_settings("X_emission.png")["srgb"], 1)
        self.assertEqual(uh.texture_settings("X_maskmap.png")["srgb"], 0)
        self.assertEqual(uh.texture_settings("X_height.png", (512, 512))["max_size"], 512)
        self.assertEqual(uh.texture_settings("X_height.png", (20, 20))["max_size"], 32)

    def test_missing_mat(self):
        s = stage_export(self.t / "s1", "Rock", self.G1)
        (s / "Rock.mat").unlink()
        with self.assertRaises(uh.HandoffError):
            uh.sync_into_project(s, self.dest, "Rock")


FAKE_UNITY = r"""#!/usr/bin/env python3
import json, sys
a = sys.argv
def arg(n): return a[a.index(n) + 1]
mode = open(arg("-projectPath") + "/fake_mode").read().strip()
open(arg("-logFile"), "w").write("Unity fake\n" + ("No valid Unity Editor license found\n" if mode == "license" else ""))
if mode == "license":
    sys.exit(1)
ok = mode == "ok"
rep = {"mm_unity_verify": 1, "ok": ok, "folder": arg("-mmFolder"), "errors": [] if ok else ["no material"],
       "materials": []}
json.dump(rep, open(arg("-mmReport"), "w"))
sys.exit(0 if ok else 1)
"""


class TestVerifyFake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.project = make_project(self.t / "proj", URP_ASSET, [uh.URP_PACKAGE])
        (self.t / "fake_unity.py").write_text(FAKE_UNITY)
        self.unity = self.t / "Unity"  # sh wrapper: a shebang can't hold a python path with spaces
        self.unity.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, self.t / "fake_unity.py"))
        self.unity.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_mode(self, mode):
        (self.project / "fake_mode").write_text(mode)
        return uh.verify(str(self.unity), self.project, "Assets/Materials/Generated/X", self.t / "work", timeout=30)

    def test_ok_installs_verifier(self):
        r = self.run_mode("ok")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["report"]["folder"], "Assets/Materials/Generated/X")
        self.assertTrue((self.project / uh.VERIFIER_DEST).exists())
        self.assertTrue(r["verifier_installed"])
        self.assertFalse(self.run_mode("ok")["verifier_installed"])  # unchanged → not rewritten

    def test_problems(self):
        r = self.run_mode("bad")
        self.assertFalse(r["ok"])
        self.assertIn("no material", r["error"])

    def test_license(self):
        r = self.run_mode("license")
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "license")
        self.assertTrue(r["license_lines"])

    def test_missing_editor(self):
        r = uh.verify(str(self.t / "nope"), self.project, "Assets/X", self.t / "work")
        self.assertIn("not found", r["error"])


class TestToUnity(unittest.TestCase):
    """mmx.to_unity with run_export faked (no Godot)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.project = make_project(self.t / "proj", URP_ASSET, [uh.URP_PACKAGE])
        self.calls = []
        self.orig = mmx.run_export, mmx.RUNS_DIR
        mmx.RUNS_DIR = self.t / "runs"

        def fake_export(ptex, out_dir, target=None, cfg=None, timeout=None, keep_meta=False, skip_validate=False,
                        size=None, output_name=None):
            self.calls.append({"target": target, "output_name": output_name, "size": size})
            stage_export(out_dir, output_name, TestSync.G1)
            return {"ok": True, "stage": "done", "seconds": 0.1}
        mmx.run_export = fake_export

    def tearDown(self):
        mmx.run_export, mmx.RUNS_DIR = self.orig
        self.tmp.cleanup()

    def test_detected_target_and_folder(self):
        r = mmx.to_unity("x.ptex", self.project, "Rock", size=512, cfg=mmx.load_config())
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.calls, [{"target": "Unity/URP", "output_name": "Rock", "size": 512}])
        self.assertEqual(r["material"], "Assets/Materials/Generated/Rock/Rock.mat")
        self.assertTrue((self.project / "Assets/Materials/Generated/Rock/Rock_normal.png").exists())

    def test_target_override_and_bad_name(self):
        r = mmx.to_unity("x.ptex", self.project, "Rock", target="Unity/3D", cfg=mmx.load_config())
        self.assertEqual((r["target"], r["target_source"]), ("Unity/3D", "--target"))
        r = mmx.to_unity("x.ptex", self.project, "bad name", cfg=mmx.load_config())
        self.assertFalse(r["ok"])
        self.assertEqual(self.calls[-1]["target"], "Unity/3D")  # no export for the bad name

    def test_export_command_output_name(self):
        cfg = mmx.load_config()
        cfg["mode"] = "source"
        cmd = mmx.export_command(cfg, "/a/b.ptex", "/o", "Unity/URP", None, "Rock")
        self.assertEqual(cmd[cmd.index("--output-file") + 1], "Rock")
        cfg["mode"] = "release"
        with self.assertRaises(SystemExit):
            mmx.export_command(cfg, "/a/b.ptex", "/o", "Unity/URP", None, "Rock")
        exp = mmx.expected_files(mmx.REPO / "material_maker/examples/bricks.ptex", "/o", "Unity/URP",
                                 mmx.load_config(), "Rock")
        self.assertIn("/o/Rock.mat", exp["required"])


if __name__ == "__main__":
    unittest.main()
