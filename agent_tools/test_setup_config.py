"""Portable config: mmx.local.toml overrides, auto-detection, Unity editor lookup, AGENTS.md sync."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmx  # noqa: E402
import unity_handoff as uh  # noqa: E402
import sync_agents_md  # noqa: E402


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.base, self.local = self.t / "mmx.toml", self.t / "mmx.local.toml"
        self.base.write_text('mode = "source"\n[source]\ngodot = ""\nproject = ""\n[unity]\nproject = ""\n')
        self.patch = mock.patch.multiple(mmx, CONFIG_PATH=self.base, LOCAL_CONFIG_PATH=self.local)
        self.patch.start()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("MMX_CONFIG", None)

    def tearDown(self):
        self.env.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_defaults_filled(self):
        with mock.patch.object(mmx, "find_godot", return_value="/x/Godot"):
            cfg = mmx.load_config()
        self.assertEqual(cfg["source"]["project"], str(mmx.REPO))
        self.assertEqual(cfg["source"]["godot"], "/x/Godot")

    def test_local_overrides(self):
        self.local.write_text('[source]\ngodot = "/opt/godot"\n[unity]\nproject = "/p/Game"\n')
        cfg = mmx.load_config()
        self.assertEqual((cfg["source"]["godot"], cfg["unity"]["project"]), ("/opt/godot", "/p/Game"))
        self.assertEqual(cfg["mode"], "source")  # base file still applies

    def test_explicit_config_replaces_both(self):
        self.local.write_text('[source]\ngodot = "/opt/godot"\n')
        other = self.t / "other.toml"
        other.write_text('[source]\ngodot = "/other/godot"\n')
        self.assertEqual(mmx.load_config(other)["source"]["godot"], "/other/godot")

    def test_find_godot_env(self):
        exe = self.t / "godot"
        exe.write_text("")
        with mock.patch.dict(os.environ, {"MMX_GODOT": str(exe)}):
            self.assertEqual(mmx.find_godot(), str(exe))


class TestFindEditor(unittest.TestCase):
    def test_matches_project_version(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            root = d / "Hub"
            for v in ("6000.0.1f1", "6000.5.5f1"):
                (root / v / "Unity.app/Contents/MacOS").mkdir(parents=True)
                (root / v / "Unity.app/Contents/MacOS/Unity").write_text("")
            proj = d / "Game" / "ProjectSettings"
            proj.mkdir(parents=True)
            (proj / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.1f1\n")
            with mock.patch.object(sys, "platform", "darwin"), \
                    mock.patch.object(uh, "Path", side_effect=lambda p="", *a: Path(str(p).replace("/Applications/Unity/Hub/Editor", str(root)), *a)) as P:
                P.home = Path.home
                self.assertTrue(uh.find_editor(d / "Game").endswith("6000.0.1f1/Unity.app/Contents/MacOS/Unity"))
                (proj / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3.1f1\n")
                self.assertTrue(uh.find_editor(d / "Game").endswith("6000.5.5f1/Unity.app/Contents/MacOS/Unity"))


class TestAgentsSync(unittest.TestCase):
    def test_in_sync(self):
        self.assertEqual(sync_agents_md.build(), sync_agents_md.AGENTS.read_text(),
                         "AGENTS.md is out of sync with SKILL.md: run python3 agent_tools/sync_agents_md.py")


if __name__ == "__main__":
    unittest.main()
