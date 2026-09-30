"""Stub: plugin registry."""
PLUGINS = {}
def register_plugin(name, fn=None):
    if fn:
        PLUGINS[name] = fn
    return lambda f: PLUGINS.setdefault(name, f)
