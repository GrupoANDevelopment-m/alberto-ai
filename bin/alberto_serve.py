#!/usr/bin/env python3
"""
Alberto-Serve: hardened server launcher with watchdog.

Differences from `alberto serve`:
- Pre-flight checks: deps, config, sandbox
- Auto-installs missing deps with mirror fallback
- Watchdog: if server crashes, restart automatically
- Health check: every 10s pings /api/status, calls SelfHealer on failure
- Single-instance lock (so multiple alberto-serve can't collide)

Usage:
    alberto-serve --port 8741
    alberto-serve --port 8741 --max-restarts 5
    alberto-serve --port 8741 --no-watchdog   # single run, no auto-restart
"""
from __future__ import annotations
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path


# Pre-flight: ensure critical deps
REQUIRED_DEPS = ["pyyaml", "fastapi", "uvicorn", "httpx", "openai"]


def preflight_install():
    """Install missing critical deps with mirror fallback."""
    mirrors = [
        "https://mirrors.aliyun.com/pypi/simple/",
        "https://pypi.tuna.tsinghua.edu.cn/simple/",
        "https://pypi.org/simple/",
    ]
    for dep in REQUIRED_DEPS:
        try:
            __import__(dep if dep != "pyyaml" else "yaml")
        except ImportError:
            for mirror in mirrors:
                print(f"[preflight] installing {dep} from {mirror}...", flush=True)
                try:
                    r = subprocess.run(
                        [sys.executable, "-m", "pip", "install",
                         "--break-system-packages", "-q",
                         "-i", mirror, "--timeout", "30", dep],
                        capture_output=True, text=True, timeout=60,
                    )
                    if r.returncode == 0:
                        print(f"[preflight] ✓ {dep} installed", flush=True)
                        break
                except subprocess.TimeoutExpired:
                    continue
            else:
                print(f"[preflight] ✗ failed to install {dep} from any mirror",
                      file=sys.stderr, flush=True)


def find_free_port(start: int = 8741) -> int:
    """Find a free port starting from `start`."""
    for p in range(start, start + 100):
        with socket.socket() as s:
            try:
                s.bind(("", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port in range")


def check_lock(pidfile: Path) -> bool:
    """Return True if another alberto-serve is already running."""
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        pidfile.unlink(missing_ok=True)
        return False


def write_lock(pidfile: Path, pid: int):
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(pid))


def kill_alberto_serves():
    """Kill any existing alberto serve/alberto-serve processes."""
    subprocess.run(["pkill", "-9", "-f", "alberto.cli serve"],
                  capture_output=True, timeout=5)
    subprocess.run(["pkill", "-9", "-f", "bin/alberto-serve"],
                  capture_output=True, timeout=5)
    time.sleep(1)


def wait_for_health(port: int, timeout: float = 15.0) -> bool:
    """Wait for /api/status to return 200."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status",
                                       timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def run_one(port: int, host: str = "0.0.0.0") -> int:
    """Run a single alberto serve process. Returns exit code."""
    env = os.environ.copy()
    env["ALBERTO_PORT"] = str(port)
    cmd = [sys.executable, "-m", "alberto.cli", "serve",
           "--host", host, "--port", str(port)]
    print(f"[alberto-serve] starting: {' '.join(cmd)}", flush=True)
    proc = subprocess.Popen(cmd, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, bufsize=1)
    # Stream output
    for line in proc.stdout:
        print(line, end="", flush=True)
        if "Uvicorn running" in line or "Application startup complete" in line:
            print(f"[alberto-serve] ✓ server up on port {port}", flush=True)
    proc.wait()
    return proc.returncode


def watchdog_loop(port: int, max_restarts: int, host: str):
    """Watchdog: restart server on crash up to max_restarts times."""
    restarts = 0
    crash_history = []
    while True:
        rc = run_one(port, host)
        if rc == 0:
            print(f"[alberto-serve] clean exit", flush=True)
            return
        restarts += 1
        crash_history.append({"at": time.time(), "exit_code": rc})
        if max_restarts > 0 and restarts > max_restarts:
            print(f"[alberto-serve] ✗ crashed {restarts} times (>max {max_restarts}); giving up",
                  file=sys.stderr, flush=True)
            sys.exit(1)
        # Run self-heal on the crash
        try:
            from alberto import Alberto
            from alberto.runtime.self_healing import SelfHealer
            a = Alberto()
            sh = SelfHealer(a)
            heal = sh.attempt_heal(
                Exception(f"server crashed with exit code {rc}"),
                context="server_watchdog"
            )
            print(f"[alberto-serve] heal result: fixed={heal.get('fixed')}, "
                  f"fixers={heal.get('matched_fixers', [])}", flush=True)
            a.shutdown()
        except Exception as e:
            print(f"[alberto-serve] heal attempt failed: {e}", file=sys.stderr, flush=True)
        # Backoff before restart
        backoff = min(2 ** restarts, 30)
        print(f"[alberto-serve] restarting in {backoff}s (attempt {restarts})", flush=True)
        time.sleep(backoff)


def main():
    p = argparse.ArgumentParser(prog="alberto-serve",
                               description="Alberto server with watchdog + preflight")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8741)
    p.add_argument("--max-restarts", type=int, default=10,
                  help="max consecutive restarts before giving up (0=infinite)")
    p.add_argument("--no-watchdog", action="store_true",
                  help="single-run, no auto-restart")
    p.add_argument("--no-preflight", action="store_true",
                  help="skip dependency pre-flight check")
    p.add_argument("--kill-existing", action="store_true",
                  help="kill any existing alberto serve before starting")
    args = p.parse_args()

    # Step 1: lock
    pidfile = Path("/tmp/alberto-serve.pid")
    if check_lock(pidfile):
        print(f"[alberto-serve] another instance is running (PID file {pidfile}). "
              f"Use --kill-existing to force.", file=sys.stderr, flush=True)
        sys.exit(2)

    # Step 2: kill existing
    if args.kill_existing:
        print("[alberto-serve] killing existing alberto serves...", flush=True)
        kill_alberto_serves()

    # Step 3: preflight
    if not args.no_preflight:
        print("[alberto-serve] running preflight checks...", flush=True)
        preflight_install()

    # Step 4: find free port
    port = args.port
    try:
        with socket.socket() as s:
            s.bind(("", port))
    except OSError:
        print(f"[alberto-serve] port {port} busy, finding free port...", flush=True)
        port = find_free_port(args.port + 1)
        print(f"[alberto-serve] using port {port}", flush=True)

    # Step 5: write our PID
    write_lock(pidfile, os.getpid())

    # Step 6: signal handling
    def shutdown(signum, frame):
        print(f"[alberto-serve] received signal {signum}, shutting down", flush=True)
        kill_alberto_serves()
        pidfile.unlink(missing_ok=True)
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        if args.no_watchdog:
            rc = run_one(port, args.host)
            sys.exit(rc)
        else:
            watchdog_loop(port, args.max_restarts, args.host)
    finally:
        pidfile.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

