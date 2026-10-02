"""Stub auxiliary client."""
class AuxiliaryClient:
    def __init__(self, *args, **kwargs): pass
    def post(self, *args, **kwargs): return {}
    def get(self, *args, **kwargs): return {}

async def call_llm(*args, **kwargs):
    return {"content": ""}

async def async_call_llm(*args, **kwargs):
    return {"content": ""}

def extract_content_or_reasoning(*args, **kwargs):
    return ""

def get_async_text_auxiliary_client(*args, **kwargs): return None
