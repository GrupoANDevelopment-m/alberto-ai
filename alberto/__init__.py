"""Alberto AI v1.0 — sandboxed multi-agent coding assistant."""
from alberto.agent import Alberto
from alberto.identity import NAME, VERSION, get_banner

__version__ = VERSION
__all__ = ["Alberto", "NAME", "VERSION", "get_banner"]