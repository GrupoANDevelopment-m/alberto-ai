"""
Alberto tools registry — thin wrapper that re-exports the canonical
registry from engines/hermes_tools.py (which has all 77 tools).
Kept for backwards compatibility with code that imports from this path.
"""
from alberto.engines.hermes_tools import (
    HERMES_TOOL_REGISTRY,
    list_hermes_tools_full as list_tools,
    invoke_hermes_tool as invoke_tool,
    list_upstream_hermes_tools,
    list_upstream_hermes_skills,
)

__all__ = ["HERMES_TOOL_REGISTRY", "list_tools", "invoke_tool",
           "list_upstream_hermes_tools", "list_upstream_hermes_skills"]
