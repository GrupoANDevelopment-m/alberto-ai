"""Squad + persona system (AIoX-flavoured, opt-in)."""
from .catalog import SquadCatalog, Persona, WorkflowStep, load_catalog
from .registry import PersonaRegistry

__all__ = ["SquadCatalog", "Persona", "WorkflowStep", "load_catalog", "PersonaRegistry"]