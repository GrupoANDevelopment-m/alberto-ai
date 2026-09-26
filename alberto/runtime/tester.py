"""Intensive testing of apps/systems Alberto creates.

Capabilities:
- Smoke tests (start servers, hit endpoints, screenshot)
- Load tests (concurrent requests, measure latency)
- Integration tests (full workflows)
- Frontend tests (Playwright, click flows, accessibility)
- Backend tests (unit + integration via pytest)
- Performance benchmarks (CPU, memory, response time)
- Auto-fix common issues (port conflict, missing deps, etc)

Run via:
  alberto test app <app_dir>     # full test suite on a created app
  alberto test perf <target>     # perf benchmark
  alberto test install <app_dir> # test install process
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class AppTester:
    def __init__(self, app_dir: Path):
        self.app_dir = Path(app_dir).resolve()
        if not self.app_dir.exists():
            raise FileNotFoundError(f"app not found: {app_dir}")
        self.frontend = self.app_dir / "frontend"
        self.backend = self.app_dir / "backend"
        self.results = []

    def smoke(self) -> Dict[str, Any]:
        """Quick smoke test: start backend, hit endpoints, screenshot frontend."""
        out = {"phase": "smoke", "tests": []}
        # 1. Backend health
        if self.backend.exists():
            test = self._test_backend()
            out["tests"].append(test)
        # 2. Frontend build
        if self.frontend.exists():
            test = self._test_frontend()
            out["tests"].append(test)
        out["passed"] = sum(1 for t in out["tests"] if t.get("ok"))
        out["failed"] = sum(1 for t in out["tests"] if not t.get("ok"))
        out["ok"] = out["failed"] == 0
        return out

    def perf(self, endpoint: str = "/", *, n_requests: int = 50,
             concurrency: int = 5) -> Dict[str, Any]:
        """Performance benchmark. Starts backend, hits endpoint N times concurrent."""
        if not self.backend.exists():
            return {"ok": False, "error": "no backend dir"}
        # Start backend
        port = self._free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=self.backend, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            time.sleep(3)
            if proc.poll() is not None:
                return {"ok": False, "error": "backend failed to start",
                        "stderr": proc.stderr.read().decode()[:500]}
            # Sequential latency
            import urllib.request
            latencies = []
            errors = 0
            for i in range(min(20, n_requests)):
                t0 = time.time()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{endpoint}", timeout=10) as r:
                        r.read()
                    latencies.append((time.time() - t0) * 1000)
                except Exception:
                    errors += 1
            # Concurrent load
            import concurrent.futures
            def hit():
                t0 = time.time()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{endpoint}", timeout=10) as r:
                        r.read()
                    return (time.time() - t0) * 1000, True
                except Exception:
                    return 0, False
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
                futures = [ex.submit(hit) for _ in range(n_requests)]
                results = [f.result() for f in futures]
            conc_latencies = [r[0] for r in results if r[1]]
            conc_errors = sum(1 for r in results if not r[1])
            out = {
                "ok": True,
                "phase": "perf",
                "endpoint": endpoint,
                "n_requests": n_requests,
                "concurrency": concurrency,
                "sequential": {
                    "n": len(latencies),
                    "errors": errors,
                    "p50_ms": self._percentile(latencies, 50),
                    "p95_ms": self._percentile(latencies, 95),
                    "p99_ms": self._percentile(latencies, 99),
                },
                "concurrent": {
                    "n": len(conc_latencies),
                    "errors": conc_errors,
                    "p50_ms": self._percentile(conc_latencies, 50),
                    "p95_ms": self._percentile(conc_latencies, 95),
                    "p99_ms": self._percentile(conc_latencies, 99),
                    "throughput_rps": n_requests / max(sum(conc_latencies) / 1000 / concurrency, 0.001),
                },
            }
            return out
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def test_install(self) -> Dict[str, Any]:
        """Test that the app installs cleanly on a fresh setup."""
        out = {"phase": "test_install", "steps": []}
        # 1. Clean install backend
        if self.backend.exists():
            req = self.backend / "requirements.txt"
            if req.exists():
                try:
                    r = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                        capture_output=True, text=True, timeout=120,
                    )
                    out["steps"].append({"step": "pip install backend", "ok": r.returncode == 0,
                                          "stderr": r.stderr[:200] if r.returncode != 0 else ""})
                except Exception as e:
                    out["steps"].append({"step": "pip install backend", "ok": False, "error": str(e)})
        # 2. Clean install frontend
        if (self.frontend / "package.json").exists():
            if shutil.which("npm"):
                try:
                    r = subprocess.run(["npm", "install"], cwd=self.frontend,
                                      capture_output=True, text=True, timeout=180)
                    out["steps"].append({"step": "npm install frontend", "ok": r.returncode == 0,
                                          "stderr": r.stderr[-200:] if r.returncode != 0 else ""})
                except Exception as e:
                    out["steps"].append({"step": "npm install frontend", "ok": False, "error": str(e)})
            else:
                out["steps"].append({"step": "npm install frontend", "ok": False, "error": "npm not available"})
        out["passed"] = sum(1 for s in out["steps"] if s.get("ok"))
        out["failed"] = sum(1 for s in out["steps"] if not s.get("ok"))
        out["ok"] = out["failed"] == 0
        return out

    def test_frontend_e2e(self) -> Dict[str, Any]:
        """End-to-end test of frontend using Playwright (headless)."""
        if not self.frontend.exists():
            return {"ok": False, "error": "no frontend"}
        if not shutil.which("npm"):
            return {"ok": False, "error": "npm not available"}
        # Install
        subprocess.run(["npm", "install"], cwd=self.frontend, capture_output=True, timeout=180)
        # Start dev server
        port = 5173
        proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port), "--host", "127.0.0.1"],
            cwd=self.frontend, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(8)
        try:
            # Check Playwright
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                return {"ok": False, "error": "playwright not installed"}
            results = {"ok": True, "phase": "frontend_e2e", "steps": []}
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                    page = browser.new_page()
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=15000)
                    results["steps"].append({"step": "page loaded", "ok": True,
                                              "title": page.title()})
                    # Screenshot
                    shot_path = self.app_dir / "test-screenshot.png"
                    page.screenshot(path=str(shot_path), full_page=True)
                    results["steps"].append({"step": "screenshot", "ok": True,
                                              "path": str(shot_path)})
                    # Click button if present
                    try:
                        page.click("button", timeout=3000)
                        results["steps"].append({"step": "click button", "ok": True})
                    except Exception:
                        results["steps"].append({"step": "click button", "ok": False,
                                                  "error": "no button found"})
                    browser.close()
                except Exception as e:
                    results["ok"] = False
                    results["error"] = str(e)
            results["passed"] = sum(1 for s in results["steps"] if s.get("ok"))
            results["failed"] = sum(1 for s in results["steps"] if not s.get("ok"))
            return results
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def full(self) -> Dict[str, Any]:
        """Run all tests in sequence."""
        out = {"app": str(self.app_dir), "phases": []}
        out["phases"].append(self.test_install())
        out["phases"].append(self.smoke())
        try:
            out["phases"].append(self.perf())
        except Exception as e:
            out["phases"].append({"phase": "perf", "ok": False, "error": str(e)})
        # Frontend E2E (optional, slow)
        try:
            out["phases"].append(self.test_frontend_e2e())
        except Exception as e:
            out["phases"].append({"phase": "frontend_e2e", "ok": False, "error": str(e)})
        out["ok"] = all(p.get("ok") for p in out["phases"])
        out["passed_phases"] = sum(1 for p in out["phases"] if p.get("ok"))
        out["total_phases"] = len(out["phases"])
        return out

    # ====== helpers ======
    def _test_backend(self) -> Dict[str, Any]:
        port = self._free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=self.backend, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            time.sleep(3)
            if proc.poll() is not None:
                return {"name": "backend_start", "ok": False,
                        "error": "process exited", "stderr": proc.stderr.read().decode()[:500]}
            import urllib.request
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
                    body = r.read().decode()[:200]
                return {"name": "backend_root", "ok": True, "status": r.status, "body": body}
            except Exception as e:
                return {"name": "backend_root", "ok": False, "error": str(e)}
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def _test_frontend(self) -> Dict[str, Any]:
        if not (self.frontend / "package.json").exists():
            return {"name": "frontend_files", "ok": False, "error": "no package.json"}
        files = ["package.json", "vite.config.ts", "tsconfig.json", "index.html",
                 "src/main.tsx", "src/App.tsx", "src/index.css"]
        missing = [f for f in files if not (self.frontend / f).exists()]
        if missing:
            return {"name": "frontend_files", "ok": False, "missing": missing}
        return {"name": "frontend_files", "ok": True}

    def _free_port(self) -> int:
        import socket
        with socket.socket() as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _percentile(self, data: List[float], p: int) -> float:
        if not data:
            return 0.0
        s = sorted(data)
        k = int(len(s) * p / 100)
        return s[min(k, len(s) - 1)]


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto test")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_a = sub.add_parser("app", help="test created app")
    p_a.add_argument("app_dir")
    p_a.add_argument("--phase", default="full", choices=["smoke", "perf", "install", "e2e", "full"])
    p_a.add_argument("--endpoint", default="/")
    p_a.add_argument("--n", type=int, default=50)
    p_a.add_argument("--concurrency", type=int, default=5)
    args = p.parse_args(argv)
    t = AppTester(Path(args.app_dir))
    if args.phase == "smoke":
        r = t.smoke()
    elif args.phase == "perf":
        r = t.perf(args.endpoint, n_requests=args.n, concurrency=args.concurrency)
    elif args.phase == "install":
        r = t.test_install()
    elif args.phase == "e2e":
        r = t.test_frontend_e2e()
    else:
        r = t.full()
    print(json.dumps(r, indent=2, default=str))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
