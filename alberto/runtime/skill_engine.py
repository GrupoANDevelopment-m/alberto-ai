"""Skill execution engine — runs the bash/python/curl commands from a SKILL.md.

Skills are doc-driven: SKILL.md contains code blocks with the actual commands
to run. This engine:
1. Parses SKILL.md to extract code blocks
2. Identifies the "primary" block (usually the first bash/python one)
3. Substitutes {{args}} placeholders with user input
4. Executes via subprocess (with sandboxing via LocalSandbox policies)

Usage:
  alberto skill list                          # list all skills
  alberto skill show <name>                   # show SKILL.md
  alberto skill run <name> [args...]          # run primary block
  alberto skill commands <name>               # list all code blocks
  alberto skill auto-invoke "<intent>"        # auto-pick best skill for intent
"""
from __future__ import annotations
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SKILL_DIRS = [
    Path(__file__).parent.parent.parent / "skills",
    Path(__file__).parent.parent.parent / "upstream" / "hermes" / "skills",
]


def find_skill(name: str) -> Optional[Path]:
    """Find a SKILL.md by name across all skill dirs."""
    for d in SKILL_DIRS:
        if not d.exists():
            continue
        for skill_md in d.rglob("SKILL.md"):
            try:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
                # Parse frontmatter
                m = re.match(r"^---\n(.*?)\n---", content, re.S)
                if m:
                    try:
                        import yaml
                        meta = yaml.safe_load(m.group(1)) or {}
                        if meta.get("name") == name:
                            return skill_md
                    except Exception:
                        pass
                # Fallback: dir name matches
                if skill_md.parent.name == name:
                    return skill_md
            except Exception:
                pass
    return None


def extract_code_blocks(content: str) -> List[Dict[str, str]]:
    """Extract all code blocks from markdown. Returns list of {lang, code}."""
    blocks = []
    # Match ```lang\ncode\n``` (multiline)
    for m in re.finditer(r"```(\w+)?\n(.*?)\n```", content, re.S):
        lang = (m.group(1) or "text").lower()
        code = m.group(2)
        blocks.append({"lang": lang, "code": code})
    return blocks


def substitute_args(text: str, args: List[str], lang: str = "bash") -> str:
    """Substitute placeholders using language-aware argument escaping.

    Shell arguments are quoted with shlex.quote; Python arguments become
    string literals via repr. The {{args}} placeholder expands all arguments,
    while {{args[N]}} selects one argument. Placeholders must be unquoted in
    executable code blocks.
    """
    if not args:
        return re.sub(r"\{\{[^}]+\}\}", "", text)

    def encode(value: str) -> str:
        if lang in ("bash", "sh", "shell"):
            return shlex.quote(value)
        if lang in ("python", "python3", "py"):
            return repr(value)
        return value

    def replace(match):
        index_text = match.group(1)
        if index_text is None:
            selected = args
        else:
            index = int(index_text)
            selected = args[index:index + 1]
        encoded = [encode(value) for value in selected]
        if lang in ("python", "python3", "py"):
            return ", ".join(encoded)
        return " ".join(encoded)

    return re.sub(r"\{\{args(?:\[(\d+)\])?\}\}", replace, text)


def show_skill(name: str) -> Dict[str, Any]:
    """Show skill metadata and SKILL.md content."""
    path = find_skill(name)
    if not path:
        return {"ok": False, "error": f"skill '{name}' not found"}
    content = path.read_text(encoding="utf-8", errors="replace")
    blocks = extract_code_blocks(content)
    # Frontmatter
    meta = {}
    m = re.match(r"^---\n(.*?)\n---", content, re.S)
    if m:
        try:
            import yaml
            meta = yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass
    return {
        "ok": True,
        "name": meta.get("name", path.parent.name),
        "version": meta.get("version", "0.0.0"),
        "description": (meta.get("description") or "").strip(),
        "author": meta.get("metadata", {}).get("author", "unknown"),
        "tags": meta.get("metadata", {}).get("alberto", {}).get("tags", []) or
                meta.get("metadata", {}).get("hermes", {}).get("tags", []),
        "platforms": meta.get("platforms", []),
        "code_blocks": len(blocks),
        "languages": [b["lang"] for b in blocks],
        "path": str(path),
        "content": content[:5000] if len(content) <= 5000 else content[:5000] + "\n\n... (truncated)",
    }


def _sandbox_policy_error(sandbox) -> Optional[str]:
    """Return an error unless skill execution has a configured isolated sandbox."""
    if sandbox is None or not callable(getattr(sandbox, "run", None)) or not callable(getattr(sandbox, "home", None)):
        return "a configured sandbox is required to execute skills"
    isolation = getattr(sandbox, "isolation_level", None)
    docker_isolated = isolation == "docker-container" or getattr(sandbox, "_mode", None) == "docker"
    allow_host = os.environ.get("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if not docker_isolated and not allow_host:
        return (
            "skill execution refused: Docker isolation is required; "
            "host execution requires explicit ALBERTO_ALLOW_HOST_SKILL_EXECUTION=1"
        )
    return None


def run_skill(name: str, args: List[str], *, sandbox=None, timeout: int = 60) -> Dict[str, Any]:
    """Run the first executable skill block through the configured sandbox."""
    path = find_skill(name)
    if not path:
        return {"ok": False, "error": f"skill '{name}' not found"}
    content = path.read_text(encoding="utf-8", errors="replace")
    blocks = extract_code_blocks(content)
    if not blocks:
        return {"ok": False, "error": f"no code blocks in {name}"}
    executable_langs = ("bash", "sh", "shell", "python", "python3", "py")
    primary = next((block for block in blocks if block["lang"] in executable_langs), None)
    if primary is None:
        return {"ok": False, "error": f"no executable code block in {name}"}
    policy_error = _sandbox_policy_error(sandbox)
    if policy_error:
        return {"ok": False, "error": policy_error}
    code = substitute_args(primary["code"], args, lang=primary["lang"])
    try:
        if primary["lang"] in ("python", "python3", "py"):
            python_executable = "python3" if getattr(sandbox, "_mode", None) == "docker" else sys.executable
            cmd = [python_executable, "-c", code]
        else:
            cmd = ["bash", "-c", code]
        result = sandbox.run(cmd, timeout=timeout, cwd=str(sandbox.home()))
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        return {
            "ok": result.returncode == 0,
            "lang": primary["lang"],
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "command": " ".join(cmd[:2]) + ("..." if len(cmd) > 2 else ""),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def get_skill_content(name: str) -> str:
    """Return raw SKILL.md content for a named skill, or an empty string."""
    path = find_skill(name)
    if not path:
        return ""
    return path.read_text(encoding="utf-8", errors="replace")

def list_skills(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all skills with metadata."""
    from alberto.upstream_bridge import list_upstream_skills
    all_skills = list_upstream_skills()
    if category:
        all_skills = [s for s in all_skills if s["category"] == category]
    return all_skills


# === Skill auto-invocation ===
# Map of keyword patterns → skill names. When LLM detects these patterns in
# user prompt, the corresponding skill is auto-loaded.

SKILL_KEYWORDS: List[Dict[str, Any]] = [
    {
        "patterns": [r"\b(agent.?reach|pesquise?\s+na\s+internet|busque?\s+no\s+x|twitter|reddit|youtube|bilibili|b\s*station|小红书)\b",
                     r"\binternet\s+(research|search|busca)\b",
                     r"\b(research|pesquise|investigue)\s+(.+)\s+(on|na|no)\s+(internet|x|reddit|twitter|youtube)"],
        "skill": "agent-reach",
        "description": "Internet research across 15 platforms (Twitter, Reddit, YouTube, Bilibili, etc)",
    },
    {
        "patterns": [r"\b(browser-use|navega[r]?)\b",
                     r"\b(abrir?|navigate|go to|visit)\s+(?:a\s+|para\s+)?(https?://|\.com|\.io|\.org|\.net)"],
        "skill": "browser-skill-click",
        "description": "Browser automation with click/extract/fill actions",
    },
    {
        "patterns": [r"\b(computer.?use|desktop|automate\s+desktop|click\s+on\s+screen)\b",
                     r"\b(click|type|press)\s+(?:on\s+)?(?:screen|desktop|window)"],
        "skill": "computer-use",
        "description": "Desktop automation (click, type, screenshot)",
    },
    {
        "patterns": [r"\b(self.?heal|auto.?heal|cura[r]?)\s+(?:de|do)?\s*(?:errors?|erros?)?\b",
                     r"\bimport\s+error\b", r"\bmodule\s+not\s+found\b"],
        "skill": "self-healing-agent",
        "description": "Auto-heal broken code, missing deps, port conflicts",
    },
    {
        "patterns": [r"\b(vercel|deploy\s+(?:to|on|para)\s+vercel|vercel\s+deploy)\b"],
        "skill": "deploy-to-vercel",
        "description": "Deploy to Vercel",
    },
    {
        "patterns": [r"\b(github|gh|git\s+commit|pr|pull\s+request|merge|branch)\b",
                     r"\b(clone|fork|repo|commit|push)\s+(?:to\s+|on\s+|em\s+)?github"],
        "skill": "github",
        "description": "GitHub operations (commit, PR, branch, clone)",
    },
    {
        "patterns": [r"\b(playwright|cypress|jest|pytest|qa\s+test|test\s+automation)\b"],
        "skill": "playwright",
        "description": "Browser test automation with Playwright",
    },
    {
        "patterns": [r"\b(videoflow|video\s+generation|gera[r]? v[ií]deo)\b"],
        "skill": "videoflow",
        "description": "Video generation pipeline",
    },
    {
        "patterns": [r"\b(image\s+generation|gera[r]? imagem|flux\s*2)\b",
                     r"\b(gera[rc]rie|create)\s+(um|uma|an?)\s+(image|figura|imagem)"],
        "skill": "flux-2",
        "description": "Image generation (Flux 2 API)",
    },
    {
        "patterns": [r"\b(voice|tts|elevenlabs|text.?to.?speech|fala|voz)\b"],
        "skill": "voice-mode",
        "description": "Voice TTS/STT (ElevenLabs, Edge TTS, OpenAI TTS)",
    },
]


def auto_invoke_skill(prompt: str) -> Optional[Dict[str, Any]]:
    """Detect which skill should be auto-invoked based on prompt keywords.

    Returns None if no match, otherwise {skill, description, matched_pattern}.
    """
    import re as _re
    prompt_lower = prompt.lower()
    best_match = None
    best_score = 0

    for rule in SKILL_KEYWORDS:
        score = 0
        for pat in rule["patterns"]:
            if _re.search(pat, prompt_lower):
                score += 1
        if score > best_score:
            best_score = score
            best_match = {
                "skill": rule["skill"],
                "description": rule["description"],
                "matched_patterns": score,
            }
    return best_match if best_match else None


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto skill")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_show = sub.add_parser("show")
    p_show.add_argument("name")
    p_run = sub.add_parser("run")
    p_run.add_argument("name")
    p_run.add_argument("args", nargs="*")
    p_run.add_argument("--timeout", type=int, default=60)
    p_runall = sub.add_parser("run-all")
    p_runall.add_argument("name")
    p_runall.add_argument("args", nargs="*")
    p_runall.add_argument("--timeout", type=int, default=60)
    p_cmd = sub.add_parser("commands")
    p_cmd.add_argument("name")
    args = p.parse_args(argv)
    import json
    if args.cmd == "list":
        skills = list_skills()
        from collections import defaultdict
        by_cat = defaultdict(int)
        for s in skills:
            by_cat[s["category"]] += 1
        print(f"{len(skills)} skills total:")
        for cat, count in sorted(by_cat.items()):
            print(f"  {cat:25s} {count:3d}")
    elif args.cmd == "show":
        print(json.dumps(show_skill(args.name), indent=2, ensure_ascii=False))
    elif args.cmd == "run":
        from alberto.sandbox.base import make_sandbox
        sandbox_kind = os.environ.get("ALBERTO_SANDBOX_KIND", "local").strip().lower()
        sandbox = make_sandbox(sandbox_kind)
        r = run_skill(args.name, args.args, sandbox=sandbox, timeout=args.timeout)
        if r.get("ok"):
            print(r.get("stdout", ""))
        else:
            print(f"FAIL: {r.get('error')}")
            if r.get("stderr"):
                print(r["stderr"], file=sys.stderr)
        return 0 if r.get("ok") else 1
    elif args.cmd == "run-all":
        from alberto.sandbox.base import make_sandbox
        sandbox_kind = os.environ.get("ALBERTO_SANDBOX_KIND", "local").strip().lower()
        sandbox = make_sandbox(sandbox_kind)
        path = find_skill(args.name)
        if not path:
            print(f"skill '{args.name}' not found", file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8", errors="replace")
        blocks = extract_code_blocks(content)
        executable_langs = ("bash", "sh", "shell", "python", "python3", "py")
        executable_blocks = [block for block in blocks if block["lang"] in executable_langs]
        if executable_blocks:
            policy_error = _sandbox_policy_error(sandbox)
            if policy_error:
                print(f"FAIL: {policy_error}", file=sys.stderr)
                return 1
        failed = False
        for i, block in enumerate(blocks):
            if block["lang"] not in executable_langs:
                continue
            code = substitute_args(block["code"], args.args, lang=block["lang"])
            print(f"\n--- block {i+1} ({block['lang']}) ---")
            if block["lang"] in ("python", "python3", "py"):
                python_executable = "python3" if getattr(sandbox, "_mode", None) == "docker" else sys.executable
                cmd = [python_executable, "-c", code]
            else:
                cmd = ["bash", "-c", code]
            try:
                result = sandbox.run(cmd, timeout=args.timeout, cwd=str(sandbox.home()))
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, end="", file=sys.stderr)
                if result.returncode != 0:
                    failed = True
                    print(f"block exited with code {result.returncode}", file=sys.stderr)
            except subprocess.TimeoutExpired:
                failed = True
                print(f"timeout after {args.timeout}s", file=sys.stderr)
        return 1 if failed else 0
    elif args.cmd == "commands":
        path = find_skill(args.name)
        if not path:
            print(f"skill '{args.name}' not found", file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8", errors="replace")
        blocks = extract_code_blocks(content)
        for i, b in enumerate(blocks):
            print(f"\n--- block {i+1} ({b['lang']}) ---")
            print(b["code"][:400])

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
