"""Learner — Alberto learns from experience, creates new skills, evolves existing ones.

Capabilities:
1. create_skill() — Generate a new SKILL.md from a "golden path" (template + content)
2. evolve_skill() — Update an existing skill with improvements
3. lesson_learned() — Persist lessons from mistakes to avoid repeating
4. adapt_to_user() — Track user's style/patterns and adapt responses
5. overcome_obstacle() — When blocked, create a new skill to handle the obstacle

Storage:
- Skills created/evolved: skills/user/<name>/
- Lessons learned: .mimo/lessons.json
- User profile: .mimo/user_profile.json
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class Learner:
    def __init__(self, sandbox, mimo):
        self.sandbox = sandbox
        self.mimo = mimo
        self.lessons_path = sandbox.home() / ".mimo" / "lessons.json"
        self.profile_path = sandbox.home() / ".mimo" / "user_profile.json"
        self.user_skills_dir = Path(__file__).parent.parent.parent / "skills" / "user"
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)
        self._load_lessons()
        self._load_profile()

    def _load_lessons(self) -> None:
        if self.lessons_path.exists():
            try:
                self.lessons = json.loads(self.lessons_path.read_text())
            except Exception:
                self.lessons = []
        else:
            self.lessons = []

    def _save_lessons(self) -> None:
        self.lessons_path.parent.mkdir(parents=True, exist_ok=True)
        self.lessons_path.write_text(json.dumps(self.lessons, indent=2, ensure_ascii=False))

    def _load_profile(self) -> None:
        if self.profile_path.exists():
            try:
                self.profile = json.loads(self.profile_path.read_text())
            except Exception:
                self.profile = {}
        else:
            self.profile = {"interactions": 0, "common_topics": {}, "preferences": {}}

    def _save_profile(self) -> None:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(json.dumps(self.profile, indent=2, ensure_ascii=False))

    # ====== Skill creation ======
    def create_skill(self, name: str, *, description: str, content: str,
                     category: str = "user", tags: Optional[List[str]] = None,
                     code_blocks: Optional[List[Dict]] = None,
                     author: str = "alberto") -> Path:
        """Create a new SKILL.md and supporting files.

        code_blocks: optional list of {lang, code} dicts to include in markdown
        """
        target = self.user_skills_dir / name
        target.mkdir(parents=True, exist_ok=True)
        # Build SKILL.md
        tags_str = ", ".join(tags) if tags else "user-created, alberto"
        body = f"""---
name: {name}
description: >
  {description}
version: 0.1.0
author: {author}
license: Apache-2.0
metadata:
  alberto:
    category: {category}
    tags: [{tags_str}]
    created_by: learner
---

# {name}

{description}

{content}
"""
        if code_blocks:
            for b in code_blocks:
                body += f"\n```{b.get('lang', 'bash')}\n{b['code']}\n```\n"
        skill_md = target / "SKILL.md"
        skill_md.write_text(body)
        return skill_md

    def evolve_skill(self, name: str, *, improvements: str,
                     new_code_blocks: Optional[List[Dict]] = None,
                     version_bump: str = "0.0.1") -> Optional[Path]:
        """Evolve an existing skill: add improvements + new code blocks.

        Reads the existing SKILL.md, appends a "## Evolution" section,
        bumps version, and re-writes.
        """
        from alberto.runtime.skill_engine import find_skill
        path = find_skill(name)
        if not path:
            return None
        content = path.read_text(encoding="utf-8", errors="replace")
        # Bump version
        m = re.search(r"version:\s*(\d+\.\d+\.\d+)", content)
        if m:
            old = m.group(1)
            parts = list(map(int, old.split(".")))
            # Bump patch by default
            if version_bump == "0.0.1":
                parts[2] += 1
            elif version_bump == "0.1.0":
                parts[1] += 1
                parts[2] = 0
            elif version_bump == "1.0.0":
                parts[0] += 1
                parts[1] = 0
                parts[2] = 0
            new_version = ".".join(map(str, parts))
            content = content.replace(f"version: {old}", f"version: {new_version}", 1)
        # Append evolution section
        evolution_section = f"\n\n## Evolution (v{new_version if m else '0.0.1'})\n\n{improvements}\n"
        if new_code_blocks:
            for b in new_code_blocks:
                evolution_section += f"\n```{b.get('lang', 'bash')}\n{b['code']}\n```\n"
        # Insert before the last H1 or append
        content = content.rstrip() + "\n" + evolution_section
        path.write_text(content)
        return path

    # ====== Lesson learned ======
    def lesson_learned(self, *, mistake: str, why: str, fix: str,
                       context: str = "", severity: str = "info") -> Dict[str, Any]:
        """Record a lesson learned from a mistake. Used to avoid repeating it."""
        lesson = {
            "id": f"lesson-{int(time.time()*1000)}",
            "at": time.time(),
            "mistake": mistake,
            "why": why,
            "fix": fix,
            "context": context,
            "severity": severity,  # info | warning | error
        }
        self.lessons.append(lesson)
        self._save_lessons()
        return lesson

    def recall_lessons(self, query: str = "", *, limit: int = 5) -> List[Dict]:
        """Recall relevant lessons. If query empty, return recent."""
        if not query:
            return sorted(self.lessons, key=lambda l: l["at"], reverse=True)[:limit]
        q_words = set(re.findall(r"\w+", query.lower()))
        scored = []
        for l in self.lessons:
            text = (l["mistake"] + " " + l["why"] + " " + l["fix"]).lower()
            score = sum(1 for w in q_words if w in text)
            if score > 0:
                l2 = dict(l); l2["score"] = score
                scored.append(l2)
        scored.sort(key=lambda l: l["score"], reverse=True)
        return scored[:limit]

    def apply_lessons(self, action: str) -> List[str]:
        """Check if any past lessons apply to this action, return warnings."""
        warnings = []
        for l in self.lessons:
            if l["severity"] in ("error", "warning"):
                text = l["mistake"].lower()
                if any(w in action.lower() for w in re.findall(r"\w+", text)):
                    warnings.append(f"⚠️ {l['mistake']} → {l['fix']}")
        return warnings

    # ====== User profile ======
    def observe_interaction(self, user_msg: str, response: str) -> None:
        """Track user patterns and adapt."""
        self.profile["interactions"] = self.profile.get("interactions", 0) + 1
        # Extract topics (simple word frequency)
        words = re.findall(r"\b[a-zà-ú]{4,}\b", user_msg.lower())
        for w in words:
            self.profile.setdefault("common_topics", {}).setdefault(w, 0)
            self.profile["common_topics"][w] += 1
        # Detect language
        pt_indicators = ["que", "para", "não", "você", "como", "mais", "está", "então"]
        en_indicators = ["the", "and", "is", "you", "are", "what", "how", "for"]
        pt_count = sum(1 for w in words if w in pt_indicators)
        en_count = sum(1 for w in words if w in en_indicators)
        if pt_count > en_count:
            self.profile["preferences"]["language"] = "pt-BR"
        elif en_count > 0:
            self.profile["preferences"]["language"] = "en"
        # Detect style preferences
        if "rápido" in user_msg.lower() or "resum" in user_msg.lower():
            self.profile["preferences"]["response_style"] = "concise"
        if "detalh" in user_msg.lower() or "explique" in user_msg.lower():
            self.profile["preferences"]["response_style"] = "detailed"
        self._save_profile()

    def get_adaptation_hints(self) -> Dict[str, Any]:
        """Return hints to adapt responses based on profile."""
        prefs = self.profile.get("preferences", {})
        hints = {}
        if prefs.get("language") == "pt-BR":
            hints["language"] = "Respond in Brazilian Portuguese"
        if prefs.get("response_style") == "concise":
            hints["style"] = "Be brief and direct"
        elif prefs.get("response_style") == "detailed":
            hints["style"] = "Provide thorough explanations with examples"
        # Most common topics
        topics = sorted(self.profile.get("common_topics", {}).items(),
                       key=lambda x: x[1], reverse=True)[:5]
        if topics:
            hints["interests"] = [t[0] for t in topics]
        return hints

    # ====== Overcome obstacle ======
    def overcome_obstacle(self, obstacle: str, *, tried: List[str] = None,
                          workaround: str = "") -> Optional[Path]:
        """When blocked by an obstacle, create a skill to handle it.

        Records the lesson AND creates a SKILL.md so future runs know what to do.
        """
        tried = tried or []
        lesson = self.lesson_learned(
            mistake=f"obstacle: {obstacle}",
            why=f"Tried: {tried}" if tried else "no attempts",
            fix=workaround or f"See skill: {obstacle.replace(' ', '_')}",
            context="obstacle",
            severity="warning",
        )
        # Create skill capturing the workaround
        name = re.sub(r"[^a-z0-9]+", "_", obstacle.lower())[:30].strip("_")
        if not name:
            return None
        path = self.create_skill(
            name=f"obstacle_{name}",
            description=f"Workaround for obstacle: {obstacle}",
            content=f"## Obstacle\n{obstacle}\n\n## Attempts\n" +
                    "\n".join(f"- {t}" for t in tried) +
                    f"\n\n## Workaround\n{workaround}\n",
            category="obstacles",
            tags=["obstacle", "workaround", "auto-generated"],
            author="alberto-learner",
        )
        return path


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto learn")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_cs = sub.add_parser("create-skill")
    p_cs.add_argument("name")
    p_cs.add_argument("--description", required=True)
    p_cs.add_argument("--content", required=True)
    p_cs.add_argument("--category", default="user")
    p_es = sub.add_parser("evolve-skill")
    p_es.add_argument("name")
    p_es.add_argument("--improvements", required=True)
    p_ll = sub.add_parser("lesson")
    p_ll.add_argument("--mistake", required=True)
    p_ll.add_argument("--why", default="")
    p_ll.add_argument("--fix", required=True)
    p_ll.add_argument("--context", default="")
    p_ll.add_argument("--severity", default="info")
    p_rl = sub.add_parser("recall-lessons")
    p_rl.add_argument("query", nargs="?")
    p_rl.add_argument("--limit", type=int, default=5)
    p_oo = sub.add_parser("overcome")
    p_oo.add_argument("obstacle")
    p_oo.add_argument("--tried", nargs="*", default=[])
    p_oo.add_argument("--workaround", default="")
    p_obs = sub.add_parser("observe")
    p_obs.add_argument("user_msg")
    p_obs.add_argument("response")
    p_ad = sub.add_parser("adapt")
    args = p.parse_args(argv)
    from alberto import Alberto
    a = Alberto()
    learner = Learner(a.sandbox, a.mimo)
    if args.cmd == "create-skill":
        path = learner.create_skill(args.name, description=args.description, content=args.content, category=args.category)
        print(f"created: {path}")
    elif args.cmd == "evolve-skill":
        path = learner.evolve_skill(args.name, improvements=args.improvements)
        print(f"evolved: {path}")
    elif args.cmd == "lesson":
        l = learner.lesson_learned(mistake=args.mistake, why=args.why, fix=args.fix, context=args.context, severity=args.severity)
        print(f"lesson recorded: {l['id']}")
    elif args.cmd == "recall-lessons":
        lessons = learner.recall_lessons(args.query or "", limit=args.limit)
        for l in lessons:
            print(f"  [{l.get('severity','info')}] {l['mistake']} → {l['fix']}")
    elif args.cmd == "overcome":
        path = learner.overcome_obstacle(args.obstacle, tried=args.tried, workaround=args.workaround)
        print(f"obstacle skill: {path}")
    elif args.cmd == "observe":
        learner.observe_interaction(args.user_msg, args.response)
        print("observed")
    elif args.cmd == "adapt":
        print(json.dumps(learner.get_adaptation_hints(), indent=2, ensure_ascii=False))
    a.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
