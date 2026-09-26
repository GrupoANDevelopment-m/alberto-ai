"""Meta Controller — Alberto's "executive function".

This is the layer that turns Alberto from "an agent with skills" into
"a platform that knows which skills to use when".

Cycle:
  1. OBJECTIVE: accept a high-level goal
  2. PLANNING: decompose into subtasks, pick initial skills
  3. EXECUTION: run subtasks via Skill Manager
  4. MONITOR: detect errors, obstacles
  5. RESEARCH: if blocked, search the web/local skills for solutions
  6. LEARN: extract lesson learned
  7. CREATE SKILL: if obstacle is novel, create a new skill
  8. EVOLVE: if a skill failed, evolve it (add improvements)
  9. UPDATE MEMORY: persist knowledge
  10. CONTINUE: re-evaluate, repeat

The MetaController orchestrates all of this.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class SubTask:
    """A unit of work within a Plan."""
    id: str
    description: str
    skill: Optional[str] = None  # chosen skill
    status: str = "pending"  # pending | running | done | failed | blocked
    output: Any = None
    error: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class Plan:
    """Decomposed objective."""
    objective: str
    subtasks: List[SubTask] = field(default_factory=list)
    status: str = "planning"  # planning | executing | blocked | done | failed
    iterations: int = 0
    context: Dict[str, Any] = field(default_factory=dict)


class SkillManager:
    """Manages the skill catalog: load, search, recommend, evolve.

    Builds a semantic-ish index from skill metadata (name + description + tags)
    and tracks per-skill statistics: success_count, fail_count, avg_time, last_used.
    """
    def __init__(self, alberto):
        self.alberto = alberto
        self.index = {}  # name -> metadata + stats
        self._load_all()
        self._stats_path = alberto.sandbox.home() / ".mimo" / "skill_stats.json"
        self._load_stats()

    def _load_all(self) -> None:
        from alberto.upstream_bridge import list_upstream_skills
        for s in list_upstream_skills():
            self.index[s["name"]] = {
                "name": s["name"],
                "description": s.get("description", ""),
                "category": s.get("category", ""),
                "tags": s.get("tags", []),
                "path": s.get("path", ""),
                "version": s.get("version", "0.0.0"),
                "stats": {
                    "success": 0, "fail": 0,
                    "total_time": 0.0, "last_used": None,
                }
            }

    def _load_stats(self) -> None:
        if self._stats_path.exists():
            try:
                stats = json.loads(self._stats_path.read_text())
                for name, s in stats.items():
                    if name in self.index:
                        self.index[name]["stats"].update(s)
                    else:
                        # Auto-register dynamic skill from stats
                        self.index[name] = {
                            "name": name, "description": "(dynamic)",
                            "category": "dynamic", "tags": [], "path": "",
                            "version": "0.0.0", "stats": dict(s),
                        }
            except Exception:
                pass
        else:
            self._stats_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_stats()

    def _save_stats(self) -> None:
        data = {n: m["stats"] for n, m in self.index.items()}
        self._stats_path.write_text(json.dumps(data, indent=2))

    def total(self) -> int:
        return len(self.index)

    def list_skills(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        skills = list(self.index.values())
        if category:
            skills = [s for s in skills if s["category"] == category]
        return skills

    def search(self, query: str, *, limit: int = 10,
               min_score: float = 0.0) -> List[Dict[str, Any]]:
        """Find best-matching skills for a query.

        Scoring: word overlap on name/description/tags + category bonus.
        """
        q_words = set(re.findall(r"\w+", query.lower()))
        scored = []
        for s in self.index.values():
            text = (s["name"] + " " + s["description"] + " " +
                    " ".join(s["tags"]) + " " + s["category"]).lower()
            score = sum(1 for w in q_words if w in text) / max(len(q_words), 1)
            # Bonus for category match
            if s["category"].lower() in query.lower():
                score += 0.2
            # Penalty for skills that have failed a lot
            stats = s["stats"]
            if stats["fail"] > 0 and stats["success"] == 0:
                score -= 0.3
            if score >= min_score:
                scored.append({"skill": s, "score": round(score, 3)})
        scored.sort(key=lambda x: -x["score"])
        return scored[:limit]

    def recommend(self, task_description: str, *, top: int = 3) -> List[Dict[str, Any]]:
        """Recommend the top-N skills for a task. Considers success rate."""
        candidates = self.search(task_description, limit=top * 3)
        # Re-rank by score + success_rate
        for c in candidates:
            stats = c["skill"]["stats"]
            total = stats["success"] + stats["fail"]
            if total > 0:
                success_rate = stats["success"] / total
                c["score"] = c["score"] * 0.7 + success_rate * 0.3
        candidates.sort(key=lambda x: -x["score"])
        return candidates[:top]

    def record_outcome(self, skill_name: str, *, success: bool, duration: float = 0.0) -> None:
        """Record that a skill was used. Updates stats."""
        if skill_name not in self.index:
            # Auto-register unknown skill (for dynamic skill creation)
            self.index[skill_name] = {
                "name": skill_name, "description": "(auto-registered)",
                "category": "dynamic", "tags": [], "path": "",
                "version": "0.0.0",
                "stats": {"success": 0, "fail": 0, "total_time": 0.0, "last_used": None}
            }
        stats = self.index[skill_name]["stats"]
        if success:
            stats["success"] += 1
        else:
            stats["fail"] += 1
        stats["total_time"] += duration
        stats["last_used"] = time.time()
        self._save_stats()

    def get_stats(self, skill_name: str) -> Dict[str, Any]:
        if skill_name not in self.index:
            return {}
        return self.index[skill_name]["stats"]

    def get_top_performers(self, *, n: int = 10) -> List[Dict[str, Any]]:
        """Skills with highest success rate (min 5 uses)."""
        performers = []
        for s in self.index.values():
            stats = s["stats"]
            total = stats["success"] + stats["fail"]
            if total < 1:
                continue
            rate = stats["success"] / total
            performers.append({"name": s["name"], "category": s["category"],
                              "success": stats["success"], "fail": stats["fail"],
                              "success_rate": round(rate, 3)})
        performers.sort(key=lambda x: -x["success_rate"])
        return performers[:n]

    def get_failure_prone(self, *, n: int = 10) -> List[Dict[str, Any]]:
        """Skills that fail most often."""
        failures = []
        for s in self.index.values():
            stats = s["stats"]
            if stats["fail"] > 0:
                failures.append({"name": s["name"], "category": s["category"],
                                "success": stats["success"], "fail": stats["fail"]})
        failures.sort(key=lambda x: -x["fail"])
        return failures[:n]


class MetaController:
    """The executive function. Runs the full cycle."""
    def __init__(self, alberto):
        self.alberto = alberto
        self.skill_manager = SkillManager(alberto)
        self.researcher = alberto.researcher
        self.learner = alberto.learner
        self.plans: Dict[str, Plan] = {}
        self._on_event: Optional[Callable[[str, Dict], None]] = None
        # Plan history (for auditing)
        self._history_path = alberto.sandbox.home() / ".mimo" / "meta_history.json"
        self._history: List[Dict] = []
        if self._history_path.exists():
            try:
                self._history = json.loads(self._history_path.read_text())
            except Exception:
                self._history = []
        self._save_history()

    def on_event(self, callback: Callable[[str, Dict], None]) -> None:
        """Subscribe to meta-controller events (plan_created, subtask_done, etc)."""
        self._on_event = callback

    def _emit(self, event: str, data: Dict) -> None:
        if self._on_event:
            try:
                self._on_event(event, data)
            except Exception:
                pass

    def _save_history(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep only last 50 plans
        self._history = self._history[-50:]
        self._history_path.write_text(json.dumps(self._history, indent=2, default=str))

    def plan_objective(self, objective: str) -> Plan:
        """Decompose objective into subtasks and pick initial skills."""
        plan = Plan(objective=objective)
        # Simple decomposition: break by sentences/phrases
        # Real implementation: use LLM to decompose
        subtasks = self._decompose(objective)
        for i, st in enumerate(subtasks):
            skill_name = self._pick_skill(st)
            plan.subtasks.append(SubTask(
                id=f"st-{i+1}",
                description=st,
                skill=skill_name,
            ))
        plan.status = "executing"
        self.plans[objective] = plan
        self._record_plan(plan)
        self._emit("plan_created", {"objective": objective, "subtasks": len(plan.subtasks)})
        return plan

    def _decompose(self, objective: str) -> List[str]:
        """Decompose objective. Simple heuristic; can be replaced by LLM call."""
        # Split by common separators
        parts = re.split(r"\s+e\s+|\s*;\s*|\.\s+(?=[A-Z])", objective)
        parts = [p.strip().rstrip(".") for p in parts if p.strip()]
        if not parts:
            parts = [objective]
        return parts

    def _pick_skill(self, task: str) -> Optional[str]:
        """Use SkillManager.recommend to pick the best skill."""
        recs = self.skill_manager.recommend(task, top=1)
        return recs[0]["skill"]["name"] if recs else None

    def execute(self, plan: Plan) -> Plan:
        """Run the plan. Returns updated plan."""
        self._emit("execute_start", {"objective": plan.objective})
        for st in plan.subtasks:
            if st.status in ("done",):
                continue
            self._execute_subtask(plan, st)
        # Re-evaluate
        plan.status = "done" if all(s.status == "done" for s in plan.subtasks) else "failed"
        plan.iterations += 1
        self._emit("execute_end", {"objective": plan.objective, "status": plan.status})
        self._record_plan(plan)
        return plan

    def _execute_subtask(self, plan: Plan, st: SubTask) -> None:
        """Execute one subtask, with full cycle (execute → monitor → research → learn → create skill)."""
        st.started_at = time.time()
        st.status = "running"
        st.attempts += 1
        self._emit("subtask_start", {"id": st.id, "description": st.description, "skill": st.skill})
        if not st.skill:
            st.status = "blocked"
            st.error = "no skill chosen"
            self._emit("subtask_blocked", {"id": st.id, "reason": "no skill chosen"})
            return
        # Try to run
        success, output, error = self._try_skill(st)
        if success:
            st.status = "done"
            st.output = output
            self.skill_manager.record_outcome(st.skill, success=True,
                                              duration=time.time() - st.started_at)
            self._emit("subtask_done", {"id": st.id, "skill": st.skill})
            return
        # Failure path: research, learn, evolve, create new skill
        st.error = error
        self.skill_manager.record_outcome(st.skill, success=False,
                                          duration=time.time() - st.started_at)
        # Detect obstacle
        obstacle = self._detect_obstacle(st)
        if obstacle:
            self._emit("obstacle_detected", {"id": st.id, "obstacle": obstacle})
            # 1. Research
            research = self.researcher.search(obstacle, sources=["local_skills", "duckduckgo"], limit=3)
            self._emit("research_done", {"id": st.id, "sources": list(research["sources"].keys())})
            # 2. Lesson learned
            self.learner.lesson_learned(
                mistake=f"skill '{st.skill}' failed: {obstacle}",
                why=error or "unknown",
                fix=f"see research results: {research.get('total_hits', 0)} hits",
                context=st.description,
                severity="warning",
            )
            # 3. Try evolved skill
            evolved = self._try_evolve_skill(st.skill, error, obstacle)
            if evolved:
                # Retry with evolved skill
                self._emit("skill_evolved", {"name": st.skill, "path": str(evolved)})
                success2, output2, _ = self._try_skill(st, skill_override=st.skill)
                if success2:
                    st.status = "done"
                    st.output = output2
                    self._emit("subtask_recovered", {"id": st.id})
                    return
            # 4. Create new skill if obstacle is novel
            if research.get("total_hits", 0) == 0:
                new_skill = self.learner.overcome_obstacle(
                    obstacle, tried=[st.skill], workaround=f"see research cache"
                )
                if new_skill:
                    self._emit("skill_created", {"path": str(new_skill)})
        # Final status
        st.status = "failed" if st.attempts >= st.max_attempts else "blocked"
        st.finished_at = time.time()
        self._emit("subtask_failed", {"id": st.id, "status": st.status, "attempts": st.attempts})

    def _try_skill(self, st: SubTask, *, skill_override: Optional[str] = None) -> tuple:
        """Try to execute a skill. Returns (success, output, error)."""
        skill_name = skill_override or st.skill
        if not skill_name:
            return False, None, "no skill"
        from alberto.runtime.skill_engine import find_skill, extract_code_blocks
        path = find_skill(skill_name)
        if not path:
            return False, None, f"skill {skill_name} not found"
        content = path.read_text(encoding="utf-8", errors="replace")
        blocks = extract_code_blocks(content)
        # Find first executable block
        for b in blocks:
            if b["lang"] in ("bash", "sh", "shell", "python", "python3", "py"):
                import subprocess, sys as _sys
                try:
                    if b["lang"].startswith("python"):
                        result = subprocess.run(
                            [_sys.executable, "-c", b["code"][:2000]],
                            capture_output=True, text=True, timeout=10,
                        )
                    else:
                        result = subprocess.run(
                            ["bash", "-c", b["code"][:2000]],
                            capture_output=True, text=True, timeout=10,
                        )
                    return result.returncode == 0, result.stdout, result.stderr
                except subprocess.TimeoutExpired:
                    return False, None, "timeout"
                except Exception as e:
                    return False, None, str(e)
        return False, None, "no executable block"

    def _try_evolve_skill(self, name: str, error: str, obstacle: str):
        """Evolve a skill after failure."""
        try:
            return self.learner.evolve_skill(
                name,
                improvements=f"Auto-evolved after failure: {obstacle}\nError: {error}\nAdded: better error handling",
            )
        except Exception:
            return None

    def _detect_obstacle(self, st: SubTask) -> Optional[str]:
        """Extract obstacle from error/output."""
        if st.error:
            return st.error[:200]
        return None

    def _record_plan(self, plan: Plan) -> None:
        self._history.append({
            "objective": plan.objective,
            "status": plan.status,
            "iterations": plan.iterations,
            "subtasks": [{"id": s.id, "description": s.description, "skill": s.skill,
                          "status": s.status, "error": s.error} for s in plan.subtasks],
            "at": time.time(),
        })
        self._save_history()

    def get_history(self, *, limit: int = 10) -> List[Dict]:
        return self._history[-limit:]


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto meta")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_p = sub.add_parser("plan")
    p_p.add_argument("objective")
    p_p.add_argument("--run", action="store_true")
    p_s = sub.add_parser("skills")
    p_s.add_argument("action", choices=["list", "search", "recommend", "stats", "top", "failures"])
    p_s.add_argument("args", nargs="*")
    p_s.add_argument("--limit", type=int, default=10)
    p_s.add_argument("--query", default="")
    p_h = sub.add_parser("history")
    p_h.add_argument("--limit", type=int, default=10)
    args = p.parse_args(argv)
    from alberto import Alberto
    a = Alberto()
    mc = MetaController(a)
    if args.cmd == "plan":
        plan = mc.plan_objective(args.objective)
        print(f"Plan: {plan.objective}")
        for st in plan.subtasks:
            print(f"  - {st.id}: {st.description[:60]} → skill={st.skill}")
        if args.run:
            print("\nExecuting...")
            plan = mc.execute(plan)
            print(f"Status: {plan.status}")
            for st in plan.subtasks:
                print(f"  {st.id}: {st.status} skill={st.skill}")
    elif args.cmd == "skills":
        if args.action == "list":
            print(f"{mc.skill_manager.total()} skills managed")
        elif args.action == "search":
            q = " ".join(args.args) or args.query
            for r in mc.skill_manager.search(q, limit=args.limit):
                print(f"  {r['score']:.2f} {r['skill']['name']:30s} [{r['skill']['category']}]")
        elif args.action == "recommend":
            q = " ".join(args.args) or args.query
            for r in mc.skill_manager.recommend(q, top=args.limit):
                s = r["skill"]
                print(f"  {r['score']:.2f} {s['name']:30s} [{s['category']}] — {s['description'][:60]}")
        elif args.action == "stats":
            for n, m in list(mc.skill_manager.index.items())[:args.limit]:
                stats = m["stats"]
                print(f"  {n:30s} ok={stats['success']} fail={stats['fail']} last={stats.get('last_used')}")
        elif args.action == "top":
            for p in mc.skill_manager.get_top_performers(n=args.limit):
                print(f"  {p['name']:30s} {p['success_rate']*100:.0f}% ({p['success']}/{p['success']+p['fail']})")
        elif args.action == "failures":
            for p in mc.skill_manager.get_failure_prone(n=args.limit):
                print(f"  {p['name']:30s} fails={p['fail']}")
    elif args.cmd == "history":
        for h in mc.get_history(limit=args.limit):
            print(f"  {h['objective'][:60]:60s} → {h['status']} ({h['iterations']}x)")
    a.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
