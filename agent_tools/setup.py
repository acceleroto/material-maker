#!/usr/bin/env python3
"""One-time setup of the Material Maker agent tools on this machine, then a smoke test.

    python3 agent_tools/setup.py [--godot PATH] [--unity-project PATH] [--unity-editor PATH] [--skip-test]

Steps (each one is skipped when already done):
 1. checks Python >= 3.11 and finds Godot 4.7 (--godot, $MMX_GODOT, `godot` on PATH, /Applications/Godot*.app)
 2. creates agent_tools/.venv with Pillow (contact sheets, palettes)
 3. imports the Godot project once (`godot --headless --path <repo> --import`; import only, no rendering)
 4. writes agent_tools/mmx.local.toml (machine-specific paths; gitignored)
 5. smoke test: export bricks.ptex, render its 3D preview, start the MCP engine (needs a desktop session: Material
    Maker renders on the GPU, so this cannot run on a headless server)
Prints a JSON summary; exit 0 when everything passed.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "agent_tools"
VENV = TOOLS / ".venv"
LOCAL = TOOLS / "mmx.local.toml"
GODOT_MAJOR_MINOR = "4.7"
sys.path.insert(0, str(TOOLS))


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def step(rv, name, ok, **info):
    rv["steps"].append(dict(step=name, ok=ok, **info))
    mark = "ok  " if ok else "FAIL"
    detail = info.get("detail") or info.get("error") or ""
    print("[%s] %s%s" % (mark, name, (": " + detail) if detail else ""), file=sys.stderr, flush=True)
    return ok


def godot_version(godot):
    try:
        out = subprocess.run([godot, "--version"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"\d+\.\d+(\.\d+)?\S*", out)
    return m.group(0) if m else None


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v))


def write_local(settings):
    """Merge settings ({section: {key: value}}) into mmx.local.toml, keeping existing keys."""
    import tomllib
    data = {}
    if LOCAL.exists():
        with open(LOCAL, "rb") as f:
            data = tomllib.load(f)
    for section, values in settings.items():
        data.setdefault(section, {}).update({k: v for k, v in values.items() if v not in (None, "")})
    lines = ["# Machine-specific mmx settings (gitignored). Written by agent_tools/setup.py; edit freely.",
             "# Merged on top of agent_tools/mmx.toml."]
    for section, values in data.items():
        if isinstance(values, dict):
            lines += ["", "[%s]" % section] + ["%s = %s" % (k, toml_value(v)) for k, v in values.items()]
        else:
            lines.insert(2, "%s = %s" % (section, toml_value(values)))
    LOCAL.write_text("\n".join(lines) + "\n")


def run(cmd, timeout):
    t = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p, round(time.time() - t, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--godot", help="Godot 4.7 executable (default: auto-detect)")
    ap.add_argument("--unity-project", help="default Unity project for `mmx to-unity` (optional)")
    ap.add_argument("--unity-editor", help="Unity executable for --verify (default: Unity Hub editor matching the project)")
    ap.add_argument("--skip-test", action="store_true", help="skip the smoke test")
    ap.add_argument("--reimport", action="store_true", help="re-run the Godot import even if already done")
    args = ap.parse_args()
    rv = {"ok": False, "repo": str(REPO), "steps": []}

    # 1. Python + Godot
    if not step(rv, "python", sys.version_info >= (3, 11), detail="%d.%d" % sys.version_info[:2],
                error=None if sys.version_info >= (3, 11) else "Python 3.11+ needed (tomllib)"):
        print(json.dumps(rv, indent=1)); return 1
    import mmx
    godot = args.godot or (mmx.load_config()["source"]["godot"])
    version = godot_version(godot) if godot and Path(godot).is_file() else None
    if not step(rv, "godot", bool(version), godot=godot, version=version,
                detail="%s (%s)" % (godot, version) if version else None,
                error=None if version else "Godot %s not found: install it from https://godotengine.org/download "
                      "(standard build, not .NET) and pass --godot <executable>" % GODOT_MAJOR_MINOR):
        print(json.dumps(rv, indent=1)); return 1
    if not version.startswith(GODOT_MAJOR_MINOR):
        rv["warnings"] = ["Godot %s found; this fork is developed with %s.x (project.godot), other versions may "
                          "fail to load it" % (version, GODOT_MAJOR_MINOR)]
        print("[warn] " + rv["warnings"][0], file=sys.stderr)

    # 2. venv + Pillow
    py = venv_python()
    has_pillow = py.is_file() and subprocess.run([str(py), "-c", "import PIL"], capture_output=True).returncode == 0
    if not has_pillow:
        if not py.is_file():
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=False)
        p = subprocess.run([str(py), "-m", "pip", "install", "--quiet", "pillow"], capture_output=True, text=True)
        has_pillow = p.returncode == 0
        if not has_pillow:
            rv["pip_error"] = p.stderr[-800:]
    if not step(rv, "venv+pillow", has_pillow, detail=str(VENV) if has_pillow else None,
                error=None if has_pillow else "pip install pillow failed (see pip_error)"):
        print(json.dumps(rv, indent=1)); return 1

    # 3. Godot import (resource cache in .godot/; rendering needs it)
    imported = (REPO / ".godot" / "imported").is_dir() and any((REPO / ".godot" / "imported").iterdir())
    if args.reimport or not imported:
        print("importing the Godot project (first time: a few minutes)...", file=sys.stderr, flush=True)
        p, secs = run([godot, "--headless", "--path", str(REPO), "--import"], 1800)
        imported = (REPO / ".godot" / "imported").is_dir()
        step(rv, "godot import", imported, detail="%.0f s" % secs,
             error=None if imported else "import failed: " + (p.stderr or p.stdout)[-500:])
        if not imported:
            print(json.dumps(rv, indent=1)); return 1
    else:
        step(rv, "godot import", True, detail="already done")

    # 4. local config
    unity_project = args.unity_project and str(Path(args.unity_project).expanduser().resolve())
    unity_editor = args.unity_editor
    if unity_project and not unity_editor:
        import unity_handoff as uh
        unity_editor = uh.find_editor(unity_project) or None
    write_local({"source": {"godot": godot}, "unity": {"project": unity_project, "editor": unity_editor}})
    step(rv, "config", True, detail=str(LOCAL.relative_to(REPO)))

    # 5. smoke test
    if args.skip_test:
        rv["ok"] = True
    else:
        mmx_py = [sys.executable, str(TOOLS / "mmx.py")]
        bricks = str(REPO / "material_maker/examples/bricks.ptex")
        out = REPO / "agent_runs" / "setup_check"
        p, secs = run(mmx_py + ["export", bricks, "--size", "256", "--out", str(out / "export")], 300)
        ok_export = p.returncode == 0 and (out / "export" / "bricks_albedo.png").is_file()
        step(rv, "export test", ok_export, detail="%.0f s" % secs, error=None if ok_export else p.stdout[-600:] + p.stderr[-300:])
        p, secs = run(mmx_py + ["preview", bricks, "--size", "256", "--out", str(out / "preview.png")], 300)
        ok_preview = p.returncode == 0 and (out / "preview.png").is_file()
        step(rv, "3D preview test", ok_preview, detail="%.0f s -> %s" % (secs, out / "preview.png"),
             error=None if ok_preview else p.stdout[-600:] + p.stderr[-300:])
        p, secs = run([sys.executable, str(TOOLS / "mcp_server.py"), "--check"], 300)
        ok_mcp = p.returncode == 0
        step(rv, "MCP engine test", ok_mcp, detail="%.0f s" % secs, error=None if ok_mcp else (p.stdout + p.stderr)[-600:])
        rv["ok"] = ok_export and ok_preview and ok_mcp
        rv["preview"] = str(out / "preview.png")
    rv["next"] = ("Ready. Claude Code: start it in %s (the project's .mcp.json registers the material-maker MCP "
                  "tools; approve them if asked). Other agents: see agent_docs/GETTING_STARTED.md." % REPO
                  if rv["ok"] else "Fix the failed step above and run setup again.")
    print(json.dumps(rv, indent=1))
    return 0 if rv["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
