"""Alberto AI HTTP server (FastAPI). Serves the frontend + REST/SSE API."""
from alberto.server.app import create_app, run_server

__all__ = ["create_app", "run_server"]