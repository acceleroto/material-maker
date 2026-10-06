#!/usr/bin/env python3
"""mm_client: Python client for the Material Maker engine server (`Godot --path <repo> --serve`, cli_serve.gd).

One long-running engine process keeps a graph loaded; requests edit it through MMGenGraph methods and
render/validate/export it without relaunching Godot (stdlib only).

    from mm_client import MMClient
    with MMClient() as mm:                      # starts the server (paths from mmx.toml)
        mm.load("/abs/material.ptex")
        mm.set_param("Perlin", "scale_x", 8)
        mm.render_preview("/abs/out/preview.png")
        mm.export("/abs/out/maps")              # target from mmx.toml (Unity/URP)

Protocol (one JSON object per line; see agent_tools/README.md "Server mode"):
  request  {"id": 1, "method": "set_param", "params": {...}}
  response {"mm_rpc": 1, "id": 1, "ok": true, "result": {...}, "warnings": [...]}
           {"mm_rpc": 1, "id": 1, "ok": false, "error": {"code": "...", "message": "..."}}
The engine also prints its own messages on stdout: lines without "mm_rpc" are ignored.

Subcommands:
  batch <file.jsonl>   send each request line through one server, print the responses
  bench <ptex> ...     seconds per iteration, server vs relaunching the engine
"""

import argparse
import collections
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmx  # noqa: E402

PROTOCOL_VERSION = 1
START_TIMEOUT = 60.0      # seconds until the ready line
DEFAULT_TIMEOUT = 180.0   # seconds per request (exports of big graphs take a while)
CLOSE_TIMEOUT = 10.0


class MMError(Exception):
    """A request failed (code from the server, or "timeout" / "server_died" / "start_failed")."""

    def __init__(self, code, message, response=None):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message
        self.response = response


class MMClient:
    """One engine server process. Methods mirror the server's (load, set_param, render_preview...);
    each returns the result dict or raises MMError. Warnings of the last request: .last_warnings."""

    def __init__(self, cfg=None, log_path=None, timeout=DEFAULT_TIMEOUT, command=None, start_timeout=START_TIMEOUT):
        self.cfg = cfg or mmx.load_config()
        self.timeout = timeout
        self.last_warnings = []
        self.noise = collections.deque(maxlen=50)   # recent non-protocol stdout lines
        self._responses = queue.Queue()
        self._next_id = 1
        self._lock = threading.Lock()
        if command is None:
            if self.cfg["mode"] != "source":
                raise MMError("start_failed", "the server needs mode = \"source\" in mmx.toml")
            command = [self.cfg["source"]["godot"], "--path", self.cfg["source"]["project"], "--serve"]
        self.command = list(command)
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = open(self.log_path, "w")
        else:
            self._log = subprocess.DEVNULL
        start = time.time()
        try:
            self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                         text=True, encoding="utf-8", errors="replace", bufsize=1, start_new_session=True)
        except OSError as e:
            raise MMError("start_failed", "cannot start the engine: %s" % e)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        ready = self._wait(None, start_timeout)
        self.info = ready.get("result", {})
        self.start_seconds = round(time.time() - start, 2)

    # -- process plumbing --------------------------------------------------

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            msg = None
            if line.startswith("{") and '"mm_rpc"' in line:
                try:
                    msg = json.loads(line)
                except ValueError:
                    msg = None
            if isinstance(msg, dict) and "mm_rpc" in msg:
                self._responses.put(msg)
            elif line:
                self.noise.append(line)
        self._responses.put(None)  # EOF: the process is gone

    def _died(self, what):
        rc = self.proc.poll()
        tail = " | ".join(list(self.noise)[-3:])
        return MMError("server_died", "the engine exited (code %s) %s%s" % (rc, what, (": " + tail) if tail else ""))

    def _wait(self, req_id, timeout):
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                self.kill()
                raise MMError("timeout", "no response after %ss (server killed)" % timeout)
            try:
                msg = self._responses.get(timeout=remaining)
            except queue.Empty:
                continue
            if msg is None:
                raise self._died("before responding")
            if msg.get("id") == req_id:
                return msg
            # A response to an earlier request that timed out on our side: drop it

    def call(self, method, timeout=None, **params):
        """Send one request and wait for its response. Returns the result dict, raises MMError."""
        with self._lock:
            if self.proc.poll() is not None:
                raise self._died("earlier")
            req_id = self._next_id
            self._next_id += 1
            line = json.dumps({"id": req_id, "method": method, "params": params}, ensure_ascii=False)
            try:
                self.proc.stdin.write(line + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise self._died("while sending")
            msg = self._wait(req_id, timeout or self.timeout)
        self.last_warnings = msg.get("warnings", [])
        if not msg.get("ok"):
            err = msg.get("error") or {}
            raise MMError(err.get("code", "error"), err.get("message", "unknown error"), msg)
        return msg.get("result", {})

    def kill(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                self.proc.kill()
            self.proc.wait()

    def close(self, timeout=CLOSE_TIMEOUT):
        """Ask the server to quit; kill it if it does not. Returns the exit code."""
        if self.proc.poll() is None:
            try:
                self.call("shutdown", timeout=timeout)
            except MMError:
                pass
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.kill()
        if self._log is not subprocess.DEVNULL:
            self._log.close()
            self._log = subprocess.DEVNULL
        return self.proc.returncode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- methods -----------------------------------------------------------

    def load(self, path):
        return self.call("load", path=str(Path(path).resolve()))

    def save(self, path=None):
        return self.call("save", **({"path": str(Path(path).resolve())} if path else {}))

    def list_nodes(self, query=None, category=None):
        return self.call("list_nodes", **_opt(query=query, category=category))

    def describe_node(self, type=None, node=None):
        return self.call("describe_node", **_opt(type=type, node=node))

    def add_node(self, type, name=None, parent=None, position=None, parameters=None):
        return self.call("add_node", type=type, **_opt(name=name, parent=parent, position=position, parameters=parameters))

    def remove_node(self, node):
        return self.call("remove_node", node=node)

    def connect(self, from_node, from_port, to_node, to_port):
        return self.call("connect", **{"from": from_node, "from_port": from_port, "to": to_node, "to_port": to_port})

    def disconnect(self, to_node, to_port, from_node=None, from_port=None):
        return self.call("disconnect", to=to_node, to_port=to_port, **_opt(**{"from": from_node, "from_port": from_port}))

    def set_param(self, node, name=None, value=None, **params):
        """set_param("Perlin", "scale_x", 8) or set_param("Perlin", scale_x=8, scale_y=8)."""
        if name is not None:
            return self.call("set_param", node=node, name=name, value=value)
        return self.call("set_param", node=node, params=params)

    def get_graph(self, node=None, full=False):
        return self.call("get_graph", **_opt(node=node, full=full or None))

    def validate(self):
        return self.call("validate")

    def render_output(self, node, output, port=0, size=None):
        return self.call("render_output", node=node, output=str(Path(output).resolve()), port=port, **_opt(size=size))

    def render_preview(self, output, mesh=None, env=None, size=None):
        return self.call("render_preview", output=str(Path(output).resolve()),
                         mesh=mesh or self.cfg["preview_mesh"], env=str(env or self.cfg["preview_env"]),
                         size=int(size or self.cfg["preview_size"]))

    def export(self, output_dir, target=None, size=None, prefix=None, overwrite=True):
        return self.call("export", output_dir=str(Path(output_dir).resolve()), target=target or self.cfg["target"],
                         overwrite=overwrite, **_opt(size=size, prefix=prefix))


def _opt(**kw):
    return {k: v for k, v in kw.items() if v is not None}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_batch(args):
    """Each line of the file is a request ({"method": ..., "params": {...}}); prints one response per line."""
    lines = [l for l in Path(args.file).read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    failed = 0
    with MMClient(log_path=args.log) as mm:
        for line in lines:
            req = json.loads(line)
            try:
                result = mm.call(req["method"], **req.get("params", {}))
                out = {"method": req["method"], "ok": True, "result": result}
                if mm.last_warnings:
                    out["warnings"] = mm.last_warnings
            except MMError as e:
                failed += 1
                out = {"method": req["method"], "ok": False, "error": {"code": e.code, "message": e.message}}
                if e.code in ("timeout", "server_died"):
                    print(json.dumps(out, ensure_ascii=False))
                    return 1
            print(json.dumps(out, ensure_ascii=False))
    return 1 if failed else 0


def _parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def _set_ptex_param(data, node, name, value):
    """Edit a parameter in .ptex JSON (for the relaunch path of the benchmark)."""
    for n in data.get("nodes", []):
        if n.get("name") == node:
            n.setdefault("parameters", {})[name] = value
            return
    raise SystemExit("bench: no node %s at the top level of the graph" % node)


def cmd_bench(args):
    """Same edit -> render loop through one server and by relaunching the engine for every step."""
    cfg = mmx.load_config(args.config)
    ptex = Path(args.ptex).resolve()
    values = [_parse_value(v) for v in args.values.split(",")]
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {"ptex": str(ptex), "node": args.node, "param": args.param, "values": values,
              "steps": ["set_param", "render_preview"] + (["render_output"] if args.render_node else [])
              + (["export"] if args.export else [])}

    # Server: one launch, then edits in place
    t0 = time.time()
    server_iters = []
    with MMClient(cfg, log_path=out / "server.log") as mm:
        startup = mm.start_seconds
        t = time.time()
        mm.load(ptex)
        load_s = time.time() - t
        for i, v in enumerate(values):
            t = time.time()
            mm.set_param(args.node, args.param, v)
            mm.render_preview(out / ("server_%02d_preview.png" % i))
            if args.render_node:
                mm.render_output(args.render_node, out / ("server_%02d_node.png" % i))
            if args.export:
                mm.export(out / ("server_%02d_export" % i), prefix=ptex.stem)
            server_iters.append(round(time.time() - t, 3))
    report["server"] = {"startup_s": startup, "load_s": round(load_s, 3), "iterations_s": server_iters,
                        "mean_s": round(sum(server_iters) / len(server_iters), 3), "total_s": round(time.time() - t0, 2)}

    # Relaunch: write the edited .ptex, one engine process per step (what mmx does)
    data = json.loads(ptex.read_text())
    t0 = time.time()
    relaunch_iters = []
    for i, v in enumerate(values):
        t = time.time()
        _set_ptex_param(data, args.node, args.param, v)
        edited = out / ("%s_relaunch_%02d.ptex" % (ptex.stem, i))
        edited.write_text(json.dumps(data, indent=1))
        r = mmx.render_preview(edited, out / ("relaunch_%02d_preview.png" % i), cfg=cfg)
        if not r["ok"]:
            raise SystemExit("bench: relaunch preview failed: %s" % r.get("errors"))
        if args.render_node:
            r = mmx.node_preview(edited, args.render_node, out=out / ("relaunch_%02d_node.png" % i), cfg=cfg)
            if not r["ok"]:
                raise SystemExit("bench: relaunch node preview failed: %s" % r.get("errors"))
        if args.export:
            r = mmx.run_export(edited, out / ("relaunch_%02d_export" % i), cfg=cfg, skip_validate=True)
            if not r["ok"]:
                raise SystemExit("bench: relaunch export failed: %s" % r.get("errors"))
        relaunch_iters.append(round(time.time() - t, 3))
    report["relaunch"] = {"iterations_s": relaunch_iters, "mean_s": round(sum(relaunch_iters) / len(relaunch_iters), 3),
                          "total_s": round(time.time() - t0, 2)}

    # Same pixels both ways?
    import hashlib

    def md5(p):
        return hashlib.md5(Path(p).read_bytes()).hexdigest()

    report["identical_previews"] = all(md5(out / ("server_%02d_preview.png" % i)) == md5(out / ("relaunch_%02d_preview.png" % i))
                                       for i in range(len(values)))
    if args.render_node:
        report["identical_node_renders"] = all(md5(out / ("server_%02d_node.png" % i)) == md5(out / ("relaunch_%02d_node.png" % i))
                                               for i in range(len(values)))
    report["speedup"] = round(report["relaunch"]["mean_s"] / report["server"]["mean_s"], 2)
    (out / "bench.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mm_client", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("batch", help="run a JSON-lines request file through one server")
    b.add_argument("file")
    b.add_argument("--log", help="engine stderr log file")
    b.set_defaults(func=cmd_batch)
    p = sub.add_parser("bench", help="seconds per iteration, server vs relaunch")
    p.add_argument("ptex")
    p.add_argument("--node", required=True, help="top-level node whose parameter is swept")
    p.add_argument("--param", required=True)
    p.add_argument("--values", required=True, help="comma-separated JSON values, e.g. 2,4,8")
    p.add_argument("--render-node", help="also render this node's output each iteration")
    p.add_argument("--export", action="store_true", help="also export each iteration")
    p.add_argument("--out", default=str(mmx.RUNS_DIR / "bench"))
    p.add_argument("--config")
    p.set_defaults(func=cmd_bench)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
