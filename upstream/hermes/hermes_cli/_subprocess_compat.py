"""Stub: subprocess compatibility shim."""
import subprocess
def safe_run(*args, **kwargs):
    return subprocess.run(*args, **kwargs)

def windows_hide_flags():
    return 0
