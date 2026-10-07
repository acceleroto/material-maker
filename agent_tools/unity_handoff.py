"""Unity hand-off for `mmx to-unity` (stdlib only).

- detect_pipeline(project): which MM export target fits the project (Unity/URP, Unity/HDRP, Unity/3D).
- sync_into_project(stage, dest, name): copy a staged export into Assets/..., keeping the GUIDs of files
  that already exist there (re-exports don't break scene/prefab references), removing stale maps.
- verify(...): install agent_tools/unity/MMAgentVerify.cs and run Unity -batchmode -executeMethod on it.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFIER_SRC = HERE / "unity" / "MMAgentVerify.cs"
VERIFIER_DEST = Path("Assets") / "Editor" / "MaterialMakerAgent" / "MMAgentVerify.cs"
GENERATED_DIR = Path("Assets") / "Materials" / "Generated"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

PIPELINE_TARGETS = {"URP": "Unity/URP", "HDRP": "Unity/HDRP", "Built-in": "Unity/3D"}
# m_Script GUIDs of the pipeline asset classes (stable across package versions)
RP_SCRIPT_GUIDS = {
    "bf2edee5c58d82540a51f03df9d42094": "URP",   # UniversalRenderPipelineAsset
    "0cf1dab834d4ec34195b920ea7bbf9ec": "HDRP",  # HDRenderPipelineAsset
}
URP_PACKAGE = "com.unity.render-pipelines.universal"
HDRP_PACKAGE = "com.unity.render-pipelines.high-definition"

_GUID_LINE = re.compile(r"^guid:\s*([0-9a-f]{32})\s*$", re.M)
_RP_REF = re.compile(r"(?:m_CustomRenderPipeline|customRenderPipeline):\s*\{fileID:\s*(-?\d+)(?:,\s*guid:\s*([0-9a-f]{32}))?")


class HandoffError(Exception):
    pass


# ---------------------------------------------------------------------------
# project + pipeline
# ---------------------------------------------------------------------------


def check_project(project):
    p = Path(project).expanduser().resolve()
    if not (p / "Assets").is_dir() or not (p / "ProjectSettings").is_dir():
        raise HandoffError("not a Unity project (needs Assets/ and ProjectSettings/): %s" % p)
    return p


def check_name(name):
    if not NAME_RE.match(name or ""):
        raise HandoffError("bad material name %r: use 1-64 letters, digits, _ or -, starting with a letter or digit"
                           % name)
    return name


def project_version(project):
    f = Path(project) / "ProjectSettings" / "ProjectVersion.txt"
    m = re.search(r"m_EditorVersion:\s*(\S+)", f.read_text(errors="replace")) if f.exists() else None
    return m.group(1) if m else None


def _meta_guid(meta_path):
    try:
        with open(meta_path, errors="replace") as f:
            m = _GUID_LINE.search(f.read(400))
    except OSError:
        return None
    return m.group(1) if m else None


def find_asset_by_guid(project, guid):
    """Assets/... path (relative to the project) of the asset whose .meta has this guid, or None."""
    root = Path(project) / "Assets"
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".meta") and _meta_guid(os.path.join(dirpath, fn)) == guid:
                return str(Path(dirpath, fn[:-5]).relative_to(project))
    return None


def _classify_rp_asset(project, rel):
    text = (Path(project) / rel).read_text(errors="replace")
    m = re.search(r"m_Script:\s*\{fileID:\s*\d+,\s*guid:\s*([0-9a-f]{32})", text)
    if m and m.group(1) in RP_SCRIPT_GUIDS:
        return RP_SCRIPT_GUIDS[m.group(1)]
    if "m_RendererDataList" in text:
        return "URP"
    if "m_RenderPipelineSettings" in text:
        return "HDRP"
    return None


def detect_pipeline(project):
    """{"pipeline": "URP"|"HDRP"|"Built-in", "target", "source", "assets": [...], "packages": [...]}.
    Looks at the pipeline assets set in GraphicsSettings and every QualitySettings level, then the packages."""
    project = Path(project)
    packages = []
    manifest = project / "Packages" / "manifest.json"
    if manifest.exists():
        try:
            deps = json.loads(manifest.read_text()).get("dependencies", {})
            packages = [p for p in (URP_PACKAGE, HDRP_PACKAGE) if p in deps]
        except ValueError:
            pass
    refs = []
    for name in ("GraphicsSettings.asset", "QualitySettings.asset"):
        f = project / "ProjectSettings" / name
        if f.exists():
            for m in _RP_REF.finditer(f.read_text(errors="replace")):
                if m.group(1) != "0" and m.group(2):
                    refs.append(m.group(2))
    kinds, assets = set(), []
    for guid in dict.fromkeys(refs):
        rel = find_asset_by_guid(project, guid)
        kind = _classify_rp_asset(project, rel) if rel else None
        assets.append({"guid": guid, "path": rel, "pipeline": kind})
        if kind:
            kinds.add(kind)
    rv = {"assets": assets, "packages": packages}
    if len(kinds) == 1:
        pipe, source = kinds.pop(), "render pipeline asset"
    elif len(kinds) > 1:
        raise HandoffError("project mixes render pipelines %s; pass --target" % sorted(kinds))
    elif refs:  # assets set but not recognised (e.g. in a package): fall back to the packages
        if len(packages) == 1:
            pipe, source = ("URP" if packages[0] == URP_PACKAGE else "HDRP"), "package (pipeline asset not found)"
        else:
            raise HandoffError("cannot tell which render pipeline the project uses; pass --target")
    else:
        pipe, source = "Built-in", "no render pipeline asset set"
    rv.update(pipeline=pipe, target=PIPELINE_TARGETS[pipe], source=source)
    return rv


# ---------------------------------------------------------------------------
# copy into the project, keeping GUIDs
# ---------------------------------------------------------------------------


def material_meta(guid):
    return ("fileFormatVersion: 2\nguid: %s\nNativeFormatImporter:\n  externalObjects: {}\n"
            "  mainObjectFileID: 2100000\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n" % guid)


def _generated_file(name, fn):
    """True for files `mmx to-unity` owns in the material folder: <name>.mat(.meta), <name>_<map>.png(.meta)."""
    return re.match(r"^%s(\.mat|_[a-z_]+\.png)(\.meta)?$" % re.escape(name), fn) is not None


def sync_into_project(stage, dest, name):
    """Copy the staged export (stage/<name>.mat, <name>_*.png + .meta) into dest. Existing GUIDs win:
    a texture whose .meta is already in dest keeps that GUID (the new .mat is rewritten to match), and
    <name>.mat.meta is kept (or created) so the material's own GUID is stable. Maps the new export no longer
    produces are removed. Returns {"files", "kept_guids", "new_guids", "removed", "material_guid"}."""
    stage, dest = Path(stage), Path(dest)
    mat = stage / (name + ".mat")
    if not mat.exists():
        raise HandoffError("staged export has no %s" % mat.name)
    dest.mkdir(parents=True, exist_ok=True)
    mat_text = mat.read_text()
    new_files = sorted(f.name for f in stage.iterdir() if _generated_file(name, f.name))
    kept, fresh, out = [], [], []
    for fn in new_files:
        if not fn.endswith(".png.meta"):
            continue
        text = (stage / fn).read_text()
        new_guid = _meta_guid(stage / fn)
        old_guid = _meta_guid(dest / fn) if (dest / fn).exists() else None
        if old_guid and new_guid and old_guid != new_guid:
            text = text.replace(new_guid, old_guid)
            mat_text = mat_text.replace(new_guid, old_guid)
            kept.append(fn[:-5])
        else:
            fresh.append(fn[:-5])
        (dest / fn).write_text(text)
        out.append(fn)
    for fn in new_files:
        if fn.endswith(".png"):
            shutil.copyfile(stage / fn, dest / fn)
            out.append(fn)
    (dest / mat.name).write_text(mat_text)
    out.append(mat.name)
    mat_meta = dest / (mat.name + ".meta")
    mat_guid = _meta_guid(mat_meta) if mat_meta.exists() else None
    if not mat_guid:
        mat_guid = uuid.uuid4().hex
        mat_meta.write_text(material_meta(mat_guid))
    out.append(mat_meta.name)
    removed = []
    for f in sorted(dest.iterdir()):
        if _generated_file(name, f.name) and f.name not in out:
            f.unlink()
            removed.append(f.name)
    return {"files": sorted(out), "kept_guids": kept, "new_guids": fresh, "removed": removed,
            "material_guid": mat_guid}


# ---------------------------------------------------------------------------
# batchmode verification
# ---------------------------------------------------------------------------

LICENSE_PATTERNS = ("No valid Unity Editor license", "License is not active", "license is not valid",
                    "LICENSE SYSTEM", "Licensing::Module", "Failed to activate", "entitlement",
                    "Unity Editor license")


def editor_processes(project):
    """PIDs of Unity editors (not import workers) that have this project open."""
    try:
        ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in ps.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        # import workers belong to an editor (they also carry -projectPath); any other Unity process locks it
        if "Unity.app/Contents/MacOS/Unity" in cmd and str(project) in cmd and "AssetImportWorker" not in cmd:
            pids.append(int(pid))
    return pids


def install_verifier(project):
    """Copy MMAgentVerify.cs into the project (Assets/Editor/MaterialMakerAgent/). Returns (path, changed)."""
    dest = Path(project) / VERIFIER_DEST
    src = VERIFIER_SRC.read_text()
    if dest.exists() and dest.read_text() == src:
        return str(VERIFIER_DEST), False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src)
    return str(VERIFIER_DEST), True


def verify_command(editor, project, folder, report, log):
    return [editor, "-batchmode", "-quit", "-projectPath", str(project), "-logFile", str(log),
            "-executeMethod", "MMAgentVerify.Run", "-mmFolder", folder, "-mmReport", str(report)]


def license_hints(log_text):
    return sorted({l.strip()[:300] for l in log_text.splitlines()
                   if any(p.lower() in l.lower() for p in LICENSE_PATTERNS)})[:10]


def verify(editor, project, folder, work_dir, timeout=900):
    """Run the batchmode verification of `folder` (Assets/...). Returns {"ok", "report", "log", "seconds",
    "exit_code", "error"?, "license_lines"?}."""
    project = Path(project)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    report_path, log_path = work_dir / "unity_verify.json", work_dir / "unity_verify.log"
    report_path.unlink(missing_ok=True)
    rv = {"ok": False, "log": str(log_path), "report_file": str(report_path)}
    if not Path(editor).is_file():
        rv["error"] = "Unity editor not found: %s (set [unity] editor in mmx.toml or --unity)" % editor
        return rv
    open_pids = editor_processes(project)
    if open_pids:
        rv["error"] = ("the Unity editor has this project open (pid %s); batchmode cannot open it at the same time. "
                       "Close the editor, or skip --verify (the open editor imports the files on focus)"
                       % ", ".join(map(str, open_pids)))
        rv["stage"] = "editor_open"
        return rv
    rv["verifier"], rv["verifier_installed"] = install_verifier(project)
    cmd = verify_command(editor, project, folder, report_path, log_path)
    rv["command"] = cmd
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        rc = None
    rv["seconds"] = round(time.time() - start, 1)
    rv["exit_code"] = rc
    log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
    report = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())
        except ValueError:
            pass
    if report is not None:
        rv["report"] = report
        rv["ok"] = bool(report.get("ok")) and rc == 0
        if not rv["ok"]:
            rv["error"] = "verification found problems: " + "; ".join(
                report.get("errors", []) + [e for m in report.get("materials", []) for e in m.get("errors", [])])
        return rv
    lic = license_hints(log_text)
    if lic:
        rv["license_lines"] = lic
        rv["stage"] = "license"
        rv["error"] = "Unity did not run the verifier; the log mentions licensing (see license_lines / %s)" % log_path
    elif rc is None:
        rv["error"] = "Unity timed out after %ss (see %s)" % (timeout, log_path)
    else:
        errs = [l.strip() for l in log_text.splitlines() if re.search(r"error CS\d+|executeMethod|Aborting", l)][:10]
        rv["log_errors"] = errs
        rv["error"] = "Unity exited with code %s without a report (see %s)" % (rc, log_path)
    return rv
