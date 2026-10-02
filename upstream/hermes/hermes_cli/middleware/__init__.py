"""Hermes middleware (Alberto: pass-through)."""
def run_tool_execution_middleware(function_name, function_args, dispatch_fn, **kwargs):
    """Pass-through to dispatch."""
    return dispatch_fn(function_args)
