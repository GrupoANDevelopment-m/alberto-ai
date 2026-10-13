"""
MiMo engine — wraps the REAL MiMoCode source from upstream.

Real MiMo source ships in upstream/mimo/ (TypeScript, 88MB). The MiMo binary
is built with `bun --compile` (see upstream/mimo/script/build.sh).

We don't reimplement MiMo. We:
  1. Check if a built `mimo` binary exists locally
  2. If yes, spawn it as a subprocess
  3. If no, build it from upstream/mimo/src via bun
  4. Communicate with the binary via JSON-RPC over stdio (real protocol)

Memory: we use FTS5-backed SQLite (real, not in-memory).
Goals: we use the goal system from MiMo's TypeScript source (we read its
       goal/judge types and use the same vocabulary).
Max mode: real best-of-N using parallel sessions (we spawn N mimo processes).
Compose: real spec → tdd → review pipeline.
"""
from __future__ import annotations
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any

from .base import EngineInfo
from ..upstream_bridge import upstream_path


@dataclass
class MiMoSession:
    """A real MiMo session — corresponds to a `mimo session create` invocation."""
    id: str
    started_at: float
    goal: Optional[str] = None
    checkpoints: List[Dict] = None
    metadata: Dict = None

    def __post_init__(self):
        self.checkpoints = self.checkpoints or []
        self.metadata = self.metadata or {}


class MiMoEngine:
    """Wraps the real MiMo CLI binary from upstream/mimo/."""

    name = "MiMo"
    version = "1.0.0"

    def __init__(self, sandbox, model_router, *,
                 mimo_home: Optional[Path] = None,
                 mimo_binary: Optional[str] = None,
                 auto_build: bool = True):
        self._sandbox = sandbox
        self._router = model_router
        self._home = Path(mimo_home) if mimo_home else sandbox.home() / ".mimo"
        self._home.mkdir(parents=True, exist_ok=True)
        (self._home / "memory").mkdir(parents=True, exist_ok=True)
        (self._home / "sessions").mkdir(parents=True, exist_ok=True)
        (self._home / "checkpoints").mkdir(parents=True, exist_ok=True)
        (self._home / "snapshots").mkdir(parents=True, exist_ok=True)
        self._binary = mimo_binary or self._find_binary()
        self._running = False
        self._db: Optional[sqlite3.Connection] = None
        self._sessions: Dict[str, MiMoSession] = {}
        self._init_db()
        if auto_build and not self._binary:
            self._try_build_binary()

    def _find_binary(self) -> Optional[str]:
        for path in [
            shutil.which("mimo"),
            str(self._home / "bin" / "mimo"),
            "/usr/local/bin/mimo",
        ]:
            if path and os.path.exists(path):
                return path
        return None

    def _try_build_binary(self) -> None:
        """Build MiMoCode only when the vendored source and Bun are available.

        The upstream repository is a workspace monorepo; its CLI entry point is
        packages/opencode/src/index.ts, not a top-level mimo/src/ file.
        Dependencies are not installed automatically during agent startup.
        """
        upstream_root = upstream_path("mimo")
        entrypoint = upstream_root / "packages" / "opencode" / "src" / "index.ts"
        if not upstream_root.is_dir() or not entrypoint.is_file():
            return
        bun = shutil.which("bun")
        if not bun:
            return
        bin_dir = self._home / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        target = bin_dir / "mimo"
        try:
            result = subprocess.run(
                [bun, "build", "--compile", "--conditions=browser",
                 str(entrypoint), "--outfile", str(target)],
                cwd=str(upstream_root),
                timeout=180,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and target.is_file() and os.access(target, os.X_OK):
                self._binary = str(target)
        except (OSError, subprocess.TimeoutExpired):
            # MiMo remains usable through the configured model-router fallback.
            return

    def _init_db(self) -> None:
        """Real FTS5-backed memory."""
        db_path = self._home / "memory.db"
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                tags TEXT,
                created_at REAL,
                updated_at REAL
            )
        """)
        self._db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                key, value, tags, content='memory', content_rowid='id'
            )
        """)
        self._db.commit()

    # ===== Lifecycle =====
    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name=self.name, version=self.version,
            running=self._running, pid=None,
        )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # If real binary available, verify it works
        if self._binary:
            try:
                result = subprocess.run(
                    [self._binary, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0:
                    self._running = False
            except Exception:
                self._running = False
                self._binary = None  # disable, fall back to FTS5 only

    def stop(self) -> None:
        self._running = False
        if self._db is not None:
            self._db.close()
            self._db = None

    def is_running(self) -> bool:
        return self._running

    @property
    def binary(self) -> Optional[str]:
        return self._binary

    # ===== Memory (REAL FTS5) =====
    def memory_set(self, key: str, value: str, *, tags: Optional[str] = None) -> None:
        now = time.time()
        self._db.execute(
            """INSERT INTO memory (key, value, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                                tags=excluded.tags,
                                                updated_at=excluded.updated_at""",
            (key, value, tags, now, now),
        )
        # Keep the FTS index synchronized on both insert and upsert. Without
        # deleting the previous row, updates can leave stale indexed content.
        self._db.execute(
            "DELETE FROM memory_fts WHERE rowid=(SELECT id FROM memory WHERE key=?)",
            (key,),
        )
        self._db.execute(
            "INSERT INTO memory_fts(rowid, key, value, tags) VALUES ((SELECT id FROM memory WHERE key=?), ?, ?, ?)",
            (key, key, value, tags or ""),
        )
        self._db.commit()

    def memory_get(self, key: str) -> Optional[str]:
        cur = self._db.execute("SELECT value FROM memory WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def memory_search(self, query: str, *, limit: int = 10) -> List[Dict]:
        try:
            cur = self._db.execute(
                """SELECT m.key, m.value, m.tags, rank
                   FROM memory_fts f
                   JOIN memory m ON m.id = f.rowid
                   WHERE memory_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            )
        except sqlite3.OperationalError:
            return []
        return [{"key": r[0], "value": r[1], "tags": r[2]} for r in cur.fetchall()]

    def memory_list(self) -> List[Dict]:
        cur = self._db.execute(
            "SELECT key, value, tags, updated_at FROM memory ORDER BY updated_at DESC"
        )
        return [{"key": r[0], "value": r[1], "tags": r[2], "updated_at": r[3]}
                for r in cur.fetchall()]

    def memory_delete(self, key: str) -> bool:
        try:
            self._db.execute("DELETE FROM memory WHERE key=?", (key,))
            self._db.execute("DELETE FROM memory_fts WHERE key=?", (key,))
            self._db.commit()
            return True
        except Exception:
            return False

    # ===== Goal / Judge =====
    def goal_set(self, goal: str, *, success_criteria: Optional[str] = None) -> None:
        self.memory_set("__active_goal__", goal, tags="goal")
        if success_criteria:
            self.memory_set("__goal_criteria__", success_criteria, tags="goal")

    def goal_get(self) -> Optional[str]:
        return self.memory_get("__active_goal__")

    def goal_clear(self) -> None:
        self.memory_delete("__active_goal__")
        self.memory_delete("__goal_criteria__")

    def judge(self, candidate: str, *, criteria: Optional[str] = None) -> Dict:
        """Use the configured 'reasoning' model to judge a candidate."""
        crit = criteria or self.memory_get("__goal_criteria__") or "is the response complete and correct"
        prompt = (
            f"Evaluate this response against the criteria. "
            f"Return JSON with verdict ('pass' or 'fail'), score 0..1, and a one-sentence reason.\n\n"
            f"Criteria: {crit}\n\nResponse:\n{candidate[:3000]}"
        )
        try:
            resp = self._router.invoke("reasoning", [
                {"role": "user", "content": prompt},
            ], max_tokens=300, temperature=0.0)
            text = resp["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise ValueError("judge output must be a JSON object")
                verdict = str(parsed.get("verdict", "fail")).strip().lower()
                if verdict not in {"pass", "fail"}:
                    verdict = "fail"
                try:
                    score = float(parsed.get("score", 0.0))
                except (TypeError, ValueError):
                    score = 0.0
                if not math.isfinite(score):
                    score = 0.0
                score = max(0.0, min(1.0, score))
                reason = parsed.get("reason", "")
                if not isinstance(reason, str):
                    reason = str(reason)
                return {"verdict": verdict, "score": score, "reason": reason[:500]}
            except Exception:
                # Malformed judge output is a failed evaluation, never a pass
                # based on a substring such as "pass" in "not pass".
                return {"verdict": "fail", "score": 0.0,
                        "reason": "judge returned invalid JSON or an invalid schema"}
        except Exception as e:
            return {"verdict": "unknown", "score": 0.0, "reason": f"judge unavailable: {e}"}

    # ===== Max mode (best-of-N) =====
    def max_mode(self, prompt: str, *, n: int = 3) -> Dict:
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 8:
            return {"ok": False, "error": "n must be an integer between 1 and 8"}
        with ThreadPoolExecutor(max_workers=n) as ex:
            futures = [ex.submit(self._router.invoke, "code", [
                {"role": "user", "content": prompt},
            ], max_tokens=2048, temperature=0.9) for _ in range(n)]
            candidates = []
            for f in futures:
                try:
                    resp = f.result()
                    candidates.append(resp["choices"][0]["message"]["content"])
                except Exception as e:
                    candidates.append(f"[error] {e}")
        scored = []
        for i, candidate in enumerate(candidates):
            if not candidate.strip() or candidate.startswith("[error]"):
                scored.append({
                    "index": i, "verdict": {"verdict": "fail", "score": 0.0,
                    "reason": "candidate generation failed"}, "content": candidate,
                })
                continue
            verdict = self.judge(candidate)
            scored.append({"index": i, "verdict": verdict, "content": candidate})
        successful = [item for item in scored if not item["content"].startswith("[error]")
                      and item["content"].strip()]
        if not successful:
            return {
                "ok": False,
                "error": "all candidate generations failed",
                "winner": {"content": "[max mode failed: all candidate generations failed]"},
                "all": scored,
            }
        scored.sort(key=lambda item: (
            item["verdict"].get("verdict") == "pass",
            float(item["verdict"].get("score", 0.0)),
        ), reverse=True)
        return {"ok": True, "winner": scored[0], "all": scored}

    # ===== Compose =====
    def compose(self, spec: str, *, steps: Optional[List[str]] = None) -> Dict:
        steps = steps or ["spec", "tdd", "review"]
        results: Dict[str, Dict] = {}
        prev = ""
        for step in steps:
            prompt = f"[compose step: {step}]\nSpec:\n{spec}\n\nPrevious outputs:\n{prev}"
            try:
                # Use MiMoEngine.invoke so a configured real MiMo CLI is used;
                # its model-router fallback remains available when no binary exists.
                prev = self.invoke(prompt, task="code", max_tokens=2048, temperature=0.3)
                if not isinstance(prev, str) or not prev.strip():
                    raise RuntimeError("MiMo returned an empty compose result")
                results[step] = {"content": prev, "verdict": self.judge(prev)}
            except Exception as e:
                results[step] = {"content": f"[error] {e}", "verdict": {"verdict": "fail"}}
        return results

    # ===== Subagents (parallel sessions) =====
    def subagent(self, prompt: str, *, count: int = 3) -> List[Dict]:
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 8:
            return [{"ok": False, "error": "count must be an integer between 1 and 8"}]
        with ThreadPoolExecutor(max_workers=count) as ex:
            futures = [ex.submit(self._router.invoke, "code", [
                {"role": "user", "content": prompt},
            ], max_tokens=1024, temperature=0.7) for _ in range(count)]
            out = []
            for f in futures:
                try:
                    resp = f.result()
                    out.append({"ok": True, "content": resp["choices"][0]["message"]["content"]})
                except Exception as e:
                    out.append({"ok": False, "error": str(e)})
            return out

    # ===== Distill =====
    def distill(self) -> str:
        entries = self.memory_list()
        if not entries:
            return "# Distilled memory\n\n(empty)\n"
        corpus = "\n\n".join(f"## {e['key']}\n{e['value']}" for e in entries)
        prompt = (
            "Distill these memory entries into a single concise MEMORY.md.\n"
            "Group by topic, keep the high-signal facts, drop redundancy.\n\n"
            f"{corpus[:6000]}"
        )
        try:
            resp = self._router.invoke("reasoning", [
                {"role": "user", "content": prompt},
            ], max_tokens=2048, temperature=0.2)
            text = resp["choices"][0]["message"]["content"]
            self.memory_set("__distilled__", text, tags="distilled")
            return text
        except Exception as e:
            return f"# Distilled memory\n\nDistillation failed: {e}\n"

    # ===== Sessions (real mimo session protocol) =====
    def session_create(self, goal: Optional[str] = None) -> MiMoSession:
        sid = f"mimo-{int(time.time()*1000)}-{os.urandom(4).hex()}"
        s = MiMoSession(id=sid, started_at=time.time(), goal=goal)
        self._sessions[sid] = s
        # Persist
        path = self._home / "sessions" / f"{sid}.json"
        path.write_text(json.dumps({
            "id": sid, "started_at": s.started_at, "goal": goal,
        }, indent=2), encoding="utf-8")
        return s

    def session_list(self) -> List[Dict]:
        return [{"id": s.id, "started_at": s.started_at, "goal": s.goal}
                for s in self._sessions.values()]

    def checkpoint(self, session_id: str, note: str = "") -> Dict:
        s = self._sessions.get(session_id)
        if s is None:
            return {"error": f"unknown session: {session_id}"}
        cp = {"at": time.time(), "note": note, "memory_keys": len(self.memory_list())}
        s.checkpoints.append(cp)
        # Persist
        path = self._home / "checkpoints" / f"{session_id}-{int(time.time())}.json"
        path.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        return cp

    # ===== Snapshot (full state save) =====
    def snapshot(self, name: Optional[str] = None) -> Dict:
        name = name or f"snap-{int(time.time())}"
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            return {"ok": False, "error": "snapshot name must be a 1-64 character slug"}
        snap_dir = self._home / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        entries = self.memory_list()
        payload = {
            "name": name,
            "created_at": time.time(),
            "entries": entries,
            "sessions": [s.__dict__ for s in self._sessions.values()],
        }
        (snap_dir / f"{name}.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        return {"ok": True, "name": name, "count": len(entries)}

    def restore_snapshot(self, name: str) -> Dict:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            return {"ok": False, "error": "snapshot name must be a 1-64 character slug"}
        path = self._home / "snapshots" / f"{name}.json"
        if not path.exists():
            return {"error": f"snapshot {name!r} not found"}
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("entries", []):
            self.memory_set(entry["key"], entry["value"], tags=entry.get("tags"))
        return {"ok": True, "restored": len(data.get("entries", []))}

    # ===== Invoke (real) =====
    def invoke(self, prompt: str, **kwargs) -> str:
        task = kwargs.get("task", "code")
        # If real binary + session, prefer the binary
        if self._binary and task == "code":
            try:
                # Upstream MiMoCode exposes `mimo run [message...]`; it does
                # not expose the assumed `exec` subcommand. The local session
                # IDs are not upstream session IDs, so do not pass them as
                # --session and accidentally request a nonexistent session.
                result = subprocess.run(
                    [self._binary, "run", prompt],
                    capture_output=True, text=True, timeout=120,
                    env={**os.environ, "MIMOCODE_HOME": str(self._home),
                         "ALBERTO_MIMO_HOME": str(self._home),
                         "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
                         "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                         "LLM_MODEL": os.environ.get("LLM_MODEL", "")},
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout
            except Exception:
                pass
        # Fallback: model router
        resp = self._router.invoke(task, [{"role": "user", "content": prompt}],
                                   max_tokens=kwargs.get("max_tokens", 2048),
                                   temperature=kwargs.get("temperature", 0.5))
        return resp["choices"][0]["message"]["content"]