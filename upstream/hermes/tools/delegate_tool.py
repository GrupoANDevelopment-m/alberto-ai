"""Stub delegate_tool - original requires full Hermes runtime."""
def delegate(*args, **kwargs):
    return {"delegated": True, "args": args}

def register(): pass
