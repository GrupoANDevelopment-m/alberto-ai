"""Squad catalog — YAML-based, opt-in."""
from __future__ import annotations
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Persona:
    name: str
    system_prompt: str
    role: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class WorkflowStep:
    persona: str           # persona name
    task: str              # what this step does
    output_to: str = ""    # key to save output under
    depends_on: List[str] = field(default_factory=list)


@dataclass
class Squad:
    name: str
    description: str
    personas: Dict[str, Persona] = field(default_factory=dict)
    workflow: List[WorkflowStep] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)


@dataclass
class SquadCatalog:
    squads: Dict[str, Squad] = field(default_factory=dict)
    active_squad: Optional[str] = None

    def list(self) -> List[str]:
        return sorted(self.squads.keys())

    def get(self, name: str) -> Optional[Squad]:
        return self.squads.get(name)

    def activate(self, name: str) -> Squad:
        if name not in self.squads:
            raise KeyError(f"unknown squad: {name}")
        self.active_squad = name
        return self.squads[name]

    def hibernate(self) -> None:
        self.active_squad = None

    def active(self) -> Optional[Squad]:
        if self.active_squad is None:
            return None
        return self.squads.get(self.active_squad)


def load_catalog(catalog_dir: Path) -> SquadCatalog:
    """Load all *.yaml files and squad subdirs from catalog_dir into a SquadCatalog.

    Supports two formats:
      1. Flat YAML: name/description/personas/workflow at top level (Alberto format)
      2. AIOX format: nested under `squad:` key with subdirs containing agents/, workflows/, tasks/
    """
    catalog = SquadCatalog()
    if not catalog_dir.exists():
        return catalog

    def _try_load_squad_dir(squad_dir: Path) -> Squad:
        """Load a real AIOX squad directory."""
        cfg = squad_dir / "config.yaml"
        if not cfg.exists():
            return None
        try:
            data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        # AIOX format: {squad: {name, display_name, description, ...}, agents: [...], workflows: [...]}
        s = data.get("squad", data)
        name = s.get("name") or squad_dir.name
        description = s.get("description", "")
        # Personas: load from agents/*.md in the squad dir
        personas: Dict[str, Persona] = {}
        agents_dir = squad_dir / "agents"
        if agents_dir.exists():
            for md in sorted(agents_dir.glob("*.md")):
                pname = md.stem
                content = md.read_text(encoding="utf-8", errors="replace")
                sys_prompt = content
                role = ""
                tags = []
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        try:
                            fm = yaml.safe_load(content[3:end])
                            if isinstance(fm, dict):
                                role = fm.get("name", "") or fm.get("role", "")
                                tags = fm.get("keywords", []) or fm.get("tags", []) or []
                        except Exception:
                            pass
                        sys_prompt = content[end + 3:].strip()
                personas[pname] = Persona(name=pname, system_prompt=sys_prompt, role=role, tags=tags)
        # Workflow: load from workflows/*.yaml in the squad dir
        workflow: List[WorkflowStep] = []
        wf_dir = squad_dir / "workflows"
        if wf_dir.exists():
            for wfy in sorted(wf_dir.glob("*.yaml")):
                try:
                    wd = yaml.safe_load(wfy.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(wd, dict):
                    continue
                # AIOX workflow format: {workflow: {name, description, agent: ..., steps: [...]}}
                w = wd.get("workflow", wd)
                wfname = w.get("name") or wfy.stem
                wpersona = w.get("agent", "")
                # Steps: each step is a dict with action/description
                for step in w.get("steps", []) or []:
                    if isinstance(step, dict):
                        workflow.append(WorkflowStep(
                            persona=step.get("agent", wpersona),
                            task=step.get("action", "") or step.get("description", ""),
                            output_to=step.get("output_to", ""),
                        ))
                # If no steps, just one workflow entry
                if not w.get("steps"):
                    workflow.append(WorkflowStep(
                        persona=wpersona, task=w.get("description", wfname),
                        output_to="",
                    ))
        return Squad(
            name=name, description=description,
            personas=personas, workflow=workflow,
            triggers=s.get("keywords", []) or [],
        )

    # Load flat YAMLs
    for yml in sorted(catalog_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name") or yml.stem
        description = data.get("description", "")
        personas = {}
        for p in data.get("personas", []) or []:
            pname = p.get("name")
            if not pname:
                continue
            personas[pname] = Persona(
                name=pname,
                system_prompt=p.get("system_prompt", ""),
                role=p.get("role", ""),
                tags=p.get("tags", []) or [],
            )
        workflow = []
        for w in data.get("workflow", []) or []:
            workflow.append(WorkflowStep(
                persona=w.get("persona", ""),
                task=w.get("task", ""),
                output_to=w.get("output_to", ""),
                depends_on=w.get("depends_on", []) or [],
            ))
        catalog.squads[name] = Squad(
            name=name, description=description,
            personas=personas, workflow=workflow,
            triggers=data.get("triggers", []) or [],
        )

    # Load AIOX squad directories
    for entry in sorted(catalog_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            s = _try_load_squad_dir(entry)
            if s is not None and s.name not in catalog.squads:
                catalog.squads[s.name] = s

    return catalog