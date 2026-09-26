"""Alberto AI — package entry."""
from .agent import Alberto
from .identity import NAME, VERSION, get_banner

__version__ = VERSION
__all__ = ["Alberto", "NAME", "VERSION", "get_banner"]