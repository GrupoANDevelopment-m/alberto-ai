"""Stub: connectors module for Hermes tool backends."""
class LLMConnector:
    def __init__(self, *args, **kwargs): pass
    async def call(self, *args, **kwargs): return {"content": ""}

class ToolConnector:
    def __init__(self, *args, **kwargs): pass

def is_connector_name(name): return False
def get_connector(name, **kwargs): return None
def list_connectors(): return []

def dispatch_connector_call(*args, **kwargs):
    raise NotImplementedError("Alberto: connectors disabled")
