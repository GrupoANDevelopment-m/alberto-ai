"""Stub: toolsets for delegate_tool."""

TOOLSETS = {
    "default": [],
    "code": ["code_execution_tool", "terminal_tool", "file_tools"],
    "web": ["browser_tool", "web_tools"],
    "image": ["image_generation_tool"],
    "voice": ["voice_mode", "tts_tool", "transcription_tools"],
}

def resolve_toolset(name, registry=None):
    if name in TOOLSETS:
        return TOOLSETS[name]
    return {"name": name, "tools": []}

def validate_toolsets(names):
    return [n for n in names if n]

def validate_toolset(name, required=None):
    return name in TOOLSETS

def get_all_toolsets():
    return TOOLSETS

def profile_role_toolsets(role=None, profile=None): return TOOLSETS.get(role, [])

def profile_role_toolsets(profile=None, role=None):
    """Returns (role, toolsets) - but ensure indexable."""
    if role is None:
        role = "default"
    return [role, list(TOOLSETS.keys())]
