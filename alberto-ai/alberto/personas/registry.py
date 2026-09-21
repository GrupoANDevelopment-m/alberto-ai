"""Persona registry — loads .md files from a personas directory."""
from __future__ import annotations
from pathlib import Path
from typing import Dict
from .catalog import Persona


class PersonaRegistry:
    def __init__(self):
        self._personas: Dict[str, Persona] = {}

    def load_dir(self, personas_dir: Path) -> None:
        if not personas_dir.exists():
            return
        for md in sorted(personas_dir.glob("*.md")):
            name = md.stem
            content = md.read_text(encoding="utf-8")
            # Optional YAML frontmatter
            system_prompt = content
            role = ""
            tags = []
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    import yaml
                    fm = yaml.safe_load(content[3:end])
                    if isinstance(fm, dict):
                        role = fm.get("role", "")
                        tags = fm.get("tags", []) or []
                    system_prompt = content[end + 3:].strip()
            self._personas[name] = Persona(
                name=name,
                system_prompt=system_prompt,
                role=role,
                tags=tags,
            )

    def get(self, name: str) -> Persona | None:
        return self._personas.get(name)

    def list(self) -> list[str]:
        return sorted(self._personas.keys())

    def register(self, persona: Persona) -> None:
        self._personas[persona.name] = persona