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

Crash recovery (auto_restart=True, the default): when the engine dies or a request times out, the client
starts a new engine, loads the last loaded/saved graph and replays the edits made since (add_node, remove_node,
connect, disconnect, set_param); the failed request itself is not repeated and still raises MMError (its
.recovery says what was restored). An engine that died between requests is recovered before the next one.

Subcommands:
  batch <file.jsonl>   send each request line through one server, print the responses
  bench <ptex> ...     seconds per iteration, server vs relaunching the engine
"""

import argparse
import collections
import copy
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
LIGHT_TIMEOUT = 60.0      # cap for methods that neither render nor compile (a hang shows up sooner)
CLOSE_TIMEOUT = 10.0
LIGHT_METHODS = {"save", "list_nodes", "describe_node", "add_node", "remove_node", "connect", "disconnect",
                 "set_param", "get_graph", "shutdown"}
# Edits replayed after a crash (on top of the last loaded/saved graph)
EDIT_METHODS = {"add_node", "remove_node", "connect", "disconnect", "set_param"}
FATAL_CODES = {"timeout", "server_died"}
# cli_serve.gd reads stdin lines into a 4 MiB buffer: longer requests would arrive in pieces
MAX_REQUEST_BYTES = (1 << 22) - 1


class MMError(Exception):
    """A request failed (code from the server, or "timeout" / "server_died" / "start_failed" / "bad_params").
    After a timeout/crash with auto_restart, .recovery is the recovery report (see MMClient.restart)."""

    def __init__(self, code, message, response=None, recovery=None):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message
        self.response = response
        self.recovery = recovery


class MMClient:
    """One engine server process. Methods mirror the server's (load, set_param, render_preview...);
    each returns the result dict or raises MMError. Warnings of the last request: .last_warnings."""

    def __init__(self, cfg=None, log_path=None, timeout=DEFAULT_TIMEOUT, command=None, start_timeout=START_TIMEOUT,
                 auto_restart=True):
        self.cfg = cfg or mmx.load_config()
        self.timeout = timeout
        self.start_timeout = start_timeout
        self.auto_restart = auto_restart
        self.last_warnings = []
        self.last_recovery = None    # report of the last crash recovery (also on MMError.recovery)
        self.restarts = 0
        self.graph_path = None       # last successfully loaded/saved graph (what a restart reloads)
        self.edits = []              # [(method, params)] since then (what a restart replays)
        self.noise = collections.deque(maxlen=50)   # recent non-protocol stdout lines
        self._next_id = 1
        self._lock = threading.RLock()
        if command is None:
            if self.cfg["mode"] != "source":
                raise MMError("start_failed", "the server needs mode = \"source\" in mmx.toml")
            godot, project = Path(self.cfg["source"]["godot"]), Path(self.cfg["source"]["project"])
            if not godot.is_file():
                raise MMError("start_failed", "Godot not found at %s (mmx.toml [source] godot)" % godot)
            if not (project / "project.godot").is_file():
                raise MMError("start_failed", "no project.godot in %s (mmx.toml [source] project)" % project)
            command = [str(godot), "--path", str(project), "--serve"]
        self.command = list(command)
        self.log_path = Path(log_path) if log_path else None
        self._log = subprocess.DEVNULL
        self.proc = None
        self._start()

    # -- process plumbing --------------------------------------------------

    def _start(self):
        """Start an engine process and wait for its ready line (log appended after a restart)."""
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self._log is subprocess.DEVNULL:
                self._log = open(self.log_path, "a" if self.restarts else "w")
            if self.restarts:
                self._log.write("\n--- mm_client: engine restart %d ---\n" % self.restarts)
                self._log.flush()
        self._responses = queue.Queue()
        start = time.time()
        try:
            self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                         text=True, encoding="utf-8", errors="replace", bufsize=1, start_new_session=True)
        except OSError as e:
            raise MMError("start_failed", "cannot start the engine: %s" % e)
        threading.Thread(target=self._read, args=(self.proc, self._responses), daemon=True).start()
        try:
            ready = self._wait(None, self.start_timeout)
        except MMError:
            self.kill()
            raise
        if not ready.get("ok"):
            self.kill()
            raise MMError("start_failed", "the engine did not start: %s" % ready.get("error"))
        self.info = ready.get("result", {})
        self.start_seconds = round(time.time() - start, 2)

    def _read(self, proc, responses):
        for line in proc.stdout:
            line = line.strip()
            msg = None
            if line.startswith("{") and '"mm_rpc"' in line:
                try:
                    msg = json.loads(line)
                except ValueError:
                    msg = None
            if isinstance(msg, dict) and "mm_rpc" in msg:
                responses.put(msg)
            elif line:
                self.noise.append(line)
        proc.stdout.close()
        responses.put(None)  # EOF: the process is gone

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
            if req_id is not None and msg.get("id") is None and not msg.get("ok"):
                # The server could not read our request (parse_error / bad_request): requests are sequential,
                # so this is the answer to ours
                return msg
            # A response to an earlier request that timed out on our side: drop it

    def call(self, method, timeout=None, **params):
        """Send one request and wait for its response. Returns the result dict, raises MMError.
        With auto_restart, a timeout/crash restarts the engine and restores the graph before raising."""
        with self._lock:
            self.last_recovery = None
            if self.proc.poll() is not None:
                if not self.auto_restart:
                    raise self._died("earlier")
                self.restart()   # died between requests (killed, crashed after answering): recover, then go on
            try:
                msg = self._send(method, params, timeout)
            except MMError as e:
                if e.code not in FATAL_CODES or not self.auto_restart:
                    raise
                self.kill()
                e.recovery = self.restart()
                e.message += "; " + e.recovery["summary"]
                e.args = ("%s: %s" % (e.code, e.message),)
                raise e
        self.last_warnings = msg.get("warnings", [])
        if not msg.get("ok"):
            err = msg.get("error") or {}
            raise MMError(err.get("code", "error"), err.get("message", "unknown error"), msg)
        result = msg.get("result", {})
        self._track(method, params, result)
        return result

    def _send(self, method, params, timeout=None):
        if self.proc.poll() is not None:
            raise self._died("earlier")
        req_id = self._next_id
        self._next_id += 1
        try:
            line = json.dumps({"id": req_id, "method": method, "params": params}, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as e:
            raise MMError("bad_params", "%s: parameters are not JSON (%s)" % (method, e))
        if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise MMError("bad_params", "%s: request too large (%d bytes, max %d)" % (method, len(line.encode("utf-8")),
                                                                                   MAX_REQUEST_BYTES))
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise self._died("while sending")
        if timeout is None:
            timeout = min(self.timeout, LIGHT_TIMEOUT) if method in LIGHT_METHODS else self.timeout
        return self._wait(req_id, timeout)

    def _track(self, method, params, result):
        """Remember what a restart has to restore."""
        if method == "load":
            self.graph_path = result.get("path") or params.get("path")
            self.edits = []
        elif method == "save":
            self.graph_path = result.get("path") or params.get("path") or self.graph_path
            self.edits = []
        elif method in EDIT_METHODS:
            self.edits.append((method, copy.deepcopy(params)))

    def restart(self, reload=True):
        """Kill the engine, start a new one and (reload=True) load the last loaded/saved graph and replay the
        edits made since. If replaying crashes the engine again, retries with the graph only. Returns a report:
        {restarted, graph, replayed, edits_lost, errors, summary}; raises MMError("start_failed") if no engine starts."""
        with self._lock:
            self.kill()
            self.restarts += 1
            self._start()
            report = {"restarted": True, "graph": None, "replayed": 0, "edits_lost": 0, "errors": []}
            path, edits = self.graph_path, list(self.edits)
            self.graph_path, self.edits = None, []
            if reload and path:
                for attempt_edits in (edits, []):
                    try:
                        self._restore(path, attempt_edits, report)
                        break
                    except MMError as e:
                        if e.code not in FATAL_CODES:
                            raise
                        report["errors"].append("restoring crashed the engine again (%s)" % e.message)
                        self.kill()
                        self.restarts += 1
                        self._start()
                        self.graph_path, self.edits = None, []
                        report.update(graph=None, replayed=0)
            elif edits:
                report["edits_lost"] = len(edits)
            report["summary"] = _recovery_summary(report, path, len(edits) if reload else 0)
            self.last_recovery = report
            return report

    def _restore(self, path, edits, report):
        msg = self._send("load", {"path": path})
        if not msg.get("ok"):
            report["errors"].append("cannot reload %s: %s" % (path, (msg.get("error") or {}).get("message")))
            report["edits_lost"] = len(edits)
            return
        self._track("load", {"path": path}, msg.get("result", {}))
        report["graph"] = path
        for i, (method, params) in enumerate(edits):
            msg = self._send(method, params)
            if not msg.get("ok"):
                report["errors"].append("replaying %s failed: %s" % (method, (msg.get("error") or {}).get("message")))
                report["edits_lost"] = len(edits) - i
                return
            self._track(method, params, msg.get("result", {}))
            report["replayed"] += 1
        report["edits_lost"] = 0

    def kill(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                self.proc.kill()
            self.proc.wait()
        if self.proc is not None and self.proc.stdin and not self.proc.stdin.closed:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def close(self, timeout=CLOSE_TIMEOUT):
        """Ask the server to quit; kill it if it does not. Returns the exit code."""
        if self.proc.poll() is None:
            try:
                self._send("shutdown", {}, timeout)   # not call(): no recovery while closing
            except MMError:
                pass
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
        self.kill()   # if still running; closes our end of stdin either way
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


def _recovery_summary(report, path, n_edits):
    if report["graph"]:
        text = "engine restarted, reloaded %s" % Path(report["graph"]).name
        if n_edits:
            text += " and replayed %d of %d edits made since it was loaded/saved" % (report["replayed"], n_edits)
    elif path:
        text = "engine restarted, but the graph could not be restored (load it again)"
    else:
        text = "engine restarted (no graph had been loaded)"
    if report["errors"]:
        text += " [%s]" % "; ".join(report["errors"])
    return text


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
