"""
Alberto AI — upstream bridge.

This module wraps the REAL upstream code from NemoClaw, MiMo, Hermes, and AIoX
that ships in /workspace/alberto-ai/upstream/. We don't reimplement, we wrap.

Upstream structure (all real, not stubs):
  upstream/nemoclaw/    — NemoClaw plugin (TypeScript, 30MB)
  upstream/mimo/        — MiMoCode source (TypeScript, 88MB)
  upstream/hermes/      — Hermes agent (Python, 18MB)
                          - tools/  : 90 real Python tools
                          - skills/ : 18 real skills
                          - gateway/: gateway server
  upstream/aiox/        — AIoX squads (YAML, 9.6MB)
                          - squads/ : real squads (claude-code-mastery, etc)

Alberto only adds:
  - the chat/conversation layer
  - the model router (universal OpenAI-compat)
  - the orchestrator (strategy decision)
  - the persona registry + system prompt loading
  - the shortcut registry (JSON-backed)
  - the HTTP server (FastAPI)
  - the 3D frontend

When the user runs `alberto`, they get:
  - engines: real MiMo via upstream/mimo, real Hermes via upstream/hermes
  - tools: real ones from upstream/hermes/tools
  - squads: real ones from upstream/aiox/squads
  - personas: ours (we curate these) + the AIOX one if present
"""
from __future__ import annotations
import os
import sys
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional

# Path resolution
ALBERTO_ROOT = Path(__file__).parent.parent.resolve()
UPSTREAM_ROOT = ALBERTO_ROOT / "upstream"
HERMES_TOOLS = UPSTREAM_ROOT / "hermes" / "tools"
HERMES_SKILLS = UPSTREAM_ROOT / "hermes" / "skills"
AIOX_SQUADS = UPSTREAM_ROOT / "aiox" / "squads"
# Local skills dir (all 177 skills live here)
LOCAL_SKILLS = ALBERTO_ROOT / "skills"


def upstream_path(name: str) -> Path:
    """Get path to an upstream subdir, e.g. 'hermes/tools'."""
    return UPSTREAM_ROOT / name


def hermes_tools_path() -> Path:
    return HERMES_TOOLS


def hermes_skills_path() -> Path:
    return HERMES_SKILLS


def aiox_squads_path() -> Path:
    return AIOX_SQUADS


def list_upstream_tools() -> List[Dict[str, str]]:
    """List real tools from upstream/hermes/tools/*.py.

    Returns metadata extracted from each tool's docstring (no execution).
    """
    tools = []
    if not HERMES_TOOLS.exists():
        return tools
    for py in sorted(HERMES_TOOLS.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Parse first 30 lines as docstring
        doc = []
        in_doc = False
        for line in content.split("\n")[:60]:
            if line.strip().startswith('"""') or line.strip().startswith("'''"):
                in_doc = not in_doc
                continue
            if in_doc:
                doc.append(line.strip())
        summary = " ".join(doc[:3])[:200]
        tools.append({
            "name": py.stem,
            "file": f"upstream/hermes/tools/{py.name}",
            "summary": summary,
            "size_bytes": py.stat().st_size,
        })
    return tools


def list_upstream_skills() -> List[Dict[str, str]]:
    """List real skills from upstream/hermes/skills/ + local skills/ dir.

    Scans every category recursively. Parses YAML frontmatter to extract
    name + description. Returns full metadata for the UI.
    """
    skills = []
    seen = set()
    # All skill roots to scan
    roots = [HERMES_SKILLS, LOCAL_SKILLS]
    for root in roots:
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            try:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
                meta = _parse_skill_frontmatter(content)
                name = meta.get("name") or skill_md.parent.name
                # Skip duplicates (same name from multiple roots)
                # If duplicate, prefer the path name to disambiguate
                if name in seen:
                    # Use path dir name as fallback
                    alt_name = skill_md.parent.name
                    if alt_name and alt_name != name:
                        name = alt_name
                    else:
                        continue
                seen.add(name)
                # Category = parent dir of skill dir (relative to root)
                try:
                    rel = skill_md.parent.relative_to(root)
                    category = rel.parts[0] if len(rel.parts) > 1 else "root"
                except ValueError:
                    category = "external"
                skills.append({
                    "name": name,
                    "description": (meta.get("description") or "").strip()[:200],
                    "version": meta.get("version", "0.0.0"),
                    "category": category,
                    "tags": meta.get("metadata", {}).get("alberto", {}).get("tags", []) or
                            meta.get("metadata", {}).get("hermes", {}).get("tags", []),
                    "path": str(skill_md.relative_to(ALBERTO_ROOT)),
                    "author": meta.get("metadata", {}).get("author", "unknown"),
                })
            except Exception:
                pass
    return sorted(skills, key=lambda s: (s["category"], s["name"]))


def _parse_skill_frontmatter(content: str) -> Dict:
    """Extract YAML frontmatter from a SKILL.md file."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        import yaml
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def list_upstream_squads() -> List[Dict[str, str]]:
    """List real squads from upstream/aiox/squads/."""
    squads = []
    if not AIOX_SQUADS.exists():
        return squads
    for entry in sorted(AIOX_SQUADS.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir() and (entry / "config.yaml").exists():
            # Read config.yaml for description
            cfg = entry / "config.yaml"
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                # Try YAML first
                desc = ""
                try:
                    import yaml
                    parsed = yaml.safe_load(content)
                    if isinstance(parsed, dict):
                        desc = parsed.get("description", "") or parsed.get("name", "")
                except Exception:
                    # Fallback: regex for "name:" or "description:"
                    import re
                    m = re.search(r"description:\s*['\"]?(.+?)(?:['\"]?\s*$|\n)", content, re.M)
                    if m:
                        desc = m.group(1).strip()
            except Exception:
                desc = ""
            squads.append({
                "name": entry.name,
                "description": desc,
                "path": f"upstream/aiox/squads/{entry.name}",
            })
    return squads


def import_hermes_tool(module_name: str):
    """Dynamically import a real tool from upstream/hermes/tools/.

    Example: import_hermes_tool("code_execution_tool")
    """
    spec_path = HERMES_TOOLS / f"{module_name}.py"
    if not spec_path.exists():
        raise ImportError(f"hermes tool not found: {module_name}")
    spec = importlib.util.spec_from_file_location(f"hermes_{module_name}", spec_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def get_upstream_summary() -> Dict[str, Any]:
    """Summary of what's in upstream/ (for status display)."""
    return {
        "aiox": {
            "squads": len(list_upstream_squads()),
            "path": str(AIOX_SQUADS),
        },
        "hermes": {
            "tools": len(list_upstream_tools()),
            "skills": len(list_upstream_skills()),
            "tools_path": str(HERMES_TOOLS),
            "skills_path": str(HERMES_SKILLS),
        },
        "mimo": {
            "exists": (UPSTREAM_ROOT / "mimo" / "src").exists(),
            "path": str(UPSTREAM_ROOT / "mimo"),
        },
        "nemoclaw": {
            "exists": (UPSTREAM_ROOT / "nemoclaw" / "nemoclaw").exists(),
            "path": str(UPSTREAM_ROOT / "nemoclaw"),
        },
    }

def list_upstream_hermes_tools():
    return list_upstream_tools()


def list_upstream_hermes_skills():
    return list_upstream_skills()
