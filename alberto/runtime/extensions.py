"""Extension installer — install skills, plugins, MCP servers, providers.

Sources:
- skills/   (Skill.md + optional assets)
- plugins/  (Python packages with entry_points)
- mcp/      (MCP server JSON descriptors)
- providers/(OpenAI-compat API descriptors)

All extensions are opt-in. User explicitly runs `alberto install <name>`.

Manifests are stored at:
- ~/.local/share/alberto/extensions/  (installed files)
- ~/.config/alberto/extensions.json   (registry)
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


EXT_TYPES = ("skill", "plugin", "mcp", "provider", "persona", "squad")


@dataclass
class Extension:
    name: str
    ext_type: str  # one of EXT_TYPES
    version: str = "0.0.0"
    source: str = ""  # git url, path, or registry id
    description: str = ""
    manifest: Dict[str, Any] = field(default_factory=dict)
    installed_at: Optional[float] = None
    enabled: bool = True


class ExtensionInstaller:
    def __init__(self):
        self.home = Path.home() / ".local" / "share" / "alberto" / "extensions"
        self.home.mkdir(parents=True, exist_ok=True)
        self.config = Path.home() / ".config" / "alberto" / "extensions.json"
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.extensions: Dict[str, Extension] = {}
        self._load()
        # Project-local skills dir
        self.local_skills = Path(__file__).parent.parent.parent / "skills"

    def _load(self) -> None:
        if self.config.exists():
            try:
                data = json.loads(self.config.read_text())
                for name, d in data.items():
                    self.extensions[name] = Extension(**d)
            except Exception:
                pass
        else:
            self.config.write_text("{}")

    def _save(self) -> None:
        data = {name: ext.__dict__ for name, ext in self.extensions.items()}
        self.config.write_text(json.dumps(data, indent=2, default=str))

    def list(self, ext_type: Optional[str] = None) -> List[Extension]:
        exts = list(self.extensions.values())
        if ext_type:
            exts = [e for e in exts if e.ext_type == ext_type]
        return exts

    def install(self, name: str, *, source: str, ext_type: str = "skill",
                version: str = "0.0.0", description: str = "") -> Extension:
        """Install an extension from a source.

        source can be:
        - a local path (starts with / or .)
        - a git url
        - a registry name (skill:<name> for built-in skills)
        """
        import time
        ext = Extension(
            name=name, ext_type=ext_type, version=version,
            source=source, description=description, installed_at=time.time(),
        )
        target = self.home / f"{ext_type}s" / name
        target.parent.mkdir(parents=True, exist_ok=True)

        if source.startswith("/") or source.startswith("."):
            # Local path
            src = Path(source).expanduser().resolve()
            if src.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(src, target)
            else:
                shutil.copy(src, target)
        elif source.startswith(("http://", "https://", "git@")):
            # Git clone
            if target.exists():
                shutil.rmtree(target)
            subprocess.run(["git", "clone", "--depth=1", source, str(target)],
                           check=True, capture_output=True)
        elif source.startswith("skill:"):
            # Built-in skill
            skill_name = source[len("skill:"):]
            src = self.local_skills / skill_name
            if not src.exists():
                raise FileNotFoundError(f"built-in skill {skill_name} not found")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        else:
            raise ValueError(f"unknown source format: {source}")

        # Try to load manifest
        manifest_path = target / "SKILL.md" if ext_type == "skill" else target / "manifest.json"
        if manifest_path.exists():
            ext.manifest = {"_manifest_file": str(manifest_path.relative_to(self.home))}
        self.extensions[name] = ext
        self._save()
        return ext

    def uninstall(self, name: str) -> bool:
        ext = self.extensions.get(name)
        if not ext:
            return False
        target = self.home / f"{ext.ext_type}s" / name
        if target.exists():
            shutil.rmtree(target)
        del self.extensions[name]
        self._save()
        return True

    def enable(self, name: str) -> bool:
        ext = self.extensions.get(name)
        if not ext:
            return False
        ext.enabled = True
        self._save()
        return True

    def disable(self, name: str) -> bool:
        ext = self.extensions.get(name)
        if not ext:
            return False
        ext.enabled = False
        self._save()
        return True

    # Skill creation (uses self-learning skill)
    def create_skill(self, name: str, *, description: str, content: str,
                     category: str = "user") -> Path:
        """Create a new skill from scratch and install it locally."""
        target = self.local_skills / category / name
        target.mkdir(parents=True, exist_ok=True)
        skill_md = target / "SKILL.md"
        skill_md.write_text(f"""---
name: {name}
description: >
  {description}
version: 0.1.0
author: user
license: Apache-2.0
metadata:
  alberto:
    category: {category}
    tags: [user-created]
---

# {name}

{content}
""")
        return skill_md


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto install")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_in = sub.add_parser("install")
    p_in.add_argument("name")
    p_in.add_argument("--source", required=True)
    p_in.add_argument("--type", default="skill", choices=EXT_TYPES)
    p_un = sub.add_parser("uninstall")
    p_un.add_argument("name")
    p_ls = sub.add_parser("list")
    p_ls.add_argument("--type", default=None, choices=EXT_TYPES)
    p_en = sub.add_parser("enable")
    p_en.add_argument("name")
    p_dis = sub.add_parser("disable")
    p_dis.add_argument("name")
    p_cs = sub.add_parser("create-skill")
    p_cs.add_argument("name")
    p_cs.add_argument("--description", required=True)
    p_cs.add_argument("--content", required=True)
    p_cs.add_argument("--category", default="user")
    args = p.parse_args(argv)
    inst = ExtensionInstaller()
    if args.cmd == "install":
        ext = inst.install(args.name, source=args.source, ext_type=args.type)
        print(f"installed {ext.ext_type} {ext.name} from {ext.source}")
    elif args.cmd == "uninstall":
        ok = inst.uninstall(args.name)
        print(f"uninstalled {args.name}: {ok}")
    elif args.cmd == "list":
        for ext in inst.list(args.type):
            mark = "🟢" if ext.enabled else "⚪"
            print(f"  {mark} {ext.ext_type:8s} {ext.name:30s} v{ext.version} — {ext.description[:50]}")
    elif args.cmd == "enable":
        inst.enable(args.name)
    elif args.cmd == "disable":
        inst.disable(args.name)
    elif args.cmd == "create-skill":
        p = inst.create_skill(args.name, description=args.description,
                              content=args.content, category=args.category)
        print(f"created skill at {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
