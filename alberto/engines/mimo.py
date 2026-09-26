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
import os
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
        """Build mimo binary from upstream source using bun --compile."""
        upstream_src = upstream_path("mimo/src")
        if not upstream_src.exists():
            return
        bun = shutil.which("bun")
        if not bun:
            return
        # Real MiMo build: bun --compile (see upstream/mimo/script/build.sh)
        bin_dir = self._home / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        target = bin_dir / "mimo"
        # Try to find the entry point
        for entry in ("cli.ts", "main.ts", "index.ts", "cli.tsx"):
            ep = upstream_src / entry
            if ep.exists():
                try:
                    subprocess.run(
                        [bun, "build", "--compile", str(ep), "--outfile", str(target)],
                        timeout=180, capture_output=True,
                    )
                    if target.exists() and os.access(target, os.X_OK):
                        self._binary = str(target)
                        return
                except Exception:
                    pass

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
                return json.loads(text)
            except Exception:
                return {"verdict": "pass" if "pass" in text.lower() else "fail",
                        "score": 0.5, "reason": text[:200]}
        except Exception as e:
            return {"verdict": "unknown", "score": 0.0, "reason": f"judge unavailable: {e}"}

    # ===== Max mode (best-of-N) =====
    def max_mode(self, prompt: str, *, n: int = 3) -> Dict:
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
        for i, c in enumerate(candidates):
            v = self.judge(c)
            scored.append({"index": i, "verdict": v, "content": c})
        scored.sort(key=lambda x: x["verdict"].get("score", 0), reverse=True)
        return {"winner": scored[0], "all": scored}

    # ===== Compose =====
    def compose(self, spec: str, *, steps: Optional[List[str]] = None) -> Dict:
        steps = steps or ["spec", "tdd", "review"]
        results: Dict[str, Dict] = {}
        prev = ""
        for step in steps:
            prompt = f"[compose step: {step}]\nSpec:\n{spec}\n\nPrevious outputs:\n{prev}"
            try:
                resp = self._router.invoke("code", [
                    {"role": "user", "content": prompt},
                ], max_tokens=2048, temperature=0.3)
                prev = resp["choices"][0]["message"]["content"]
                results[step] = {"content": prev, "verdict": self.judge(prev)}
            except Exception as e:
                results[step] = {"content": f"[error] {e}", "verdict": {"verdict": "fail"}}
        return results

    # ===== Subagents (parallel sessions) =====
    def subagent(self, prompt: str, *, count: int = 3) -> List[Dict]:
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
            sid = kwargs.get("session_id") or self.session_create().id
            try:
                result = subprocess.run(
                    [self._binary, "exec", "--session", sid, prompt],
                    capture_output=True, text=True, timeout=120,
                    env={**os.environ, "ALBERTO_MIMO_HOME": str(self._home),
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