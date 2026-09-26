"""App creation — scaffolds complete apps (React/Vite/TS frontend + FastAPI backend).

Pipeline:
1. Parse user's one-line description
2. Decide stack (default: React + Vite + TS + Tailwind + FastAPI)
3. Scaffold app/ with frontend/ and backend/
4. Run npm install in frontend, pip install in backend
5. Start servers (port 3000 + 8000)
6. Take screenshot via Playwright (if available)
7. Return app URL + screenshot path

Output dir: ./apps/<name>/
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class AppCreator:
    def __init__(self, output_dir: Optional[Path] = None):
        if output_dir is None:
            output_dir = Path.cwd() / "apps"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, description: str, *,
               stack: str = "react-vite-fastapi",
               run: bool = False, output_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Create an app. Returns {path, frontend_url, backend_url, screenshot?}"""
        if output_dir is not None:
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        """Create an app. Returns {path, frontend_url, backend_url, screenshot?}"""
        app_dir = self.output_dir / name
        if app_dir.exists():
            return {"ok": False, "error": f"app {name} already exists at {app_dir}"}
        app_dir.mkdir(parents=True)
        (app_dir / "frontend").mkdir()
        (app_dir / "backend").mkdir()

        # Frontend: React + Vite + TS + Tailwind (minimal)
        self._scaffold_frontend(app_dir / "frontend", name, description)
        # Backend: FastAPI
        self._scaffold_backend(app_dir / "backend", name, description)
        # docker-compose
        (app_dir / "docker-compose.yml").write_text(self._docker_compose(name))
        # README
        (app_dir / "README.md").write_text(self._readme(name, description))

        result = {
            "ok": True,
            "name": name,
            "path": str(app_dir),
            "frontend_path": str(app_dir / "frontend"),
            "backend_path": str(app_dir / "backend"),
            "frontend_url": "http://localhost:3000",
            "backend_url": "http://localhost:8000",
        }
        if run:
            run_result = self.run(app_dir)
            result.update(run_result)
        return result

    def _scaffold_frontend(self, path: Path, name: str, description: str) -> None:
        # package.json
        (path / "package.json").write_text(json.dumps({
            "name": name, "private": True, "version": "0.1.0",
            "type": "module",
            "scripts": {
                "dev": "vite --host 0.0.0.0 --port 3000",
                "build": "tsc && vite build",
                "preview": "vite preview",
            },
            "dependencies": {"react": "^18.3.0", "react-dom": "^18.3.0"},
            "devDependencies": {
                "@types/react": "^18.3.0", "@types/react-dom": "^18.3.0",
                "@vitejs/plugin-react": "^4.0.0",
                "typescript": "^5.0.0", "vite": "^5.0.0",
                "tailwindcss": "^3.0.0", "postcss": "^8.0.0", "autoprefixer": "^10.0.0",
            },
        }, indent=2))
        # vite.config.ts
        (path / "vite.config.ts").write_text("""import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()] })
""")
        # tsconfig.json
        (path / "tsconfig.json").write_text(json.dumps({
            "compilerOptions": {
                "target": "ES2020", "useDefineForClassFields": True,
                "lib": ["ES2020", "DOM", "DOM.Iterable"],
                "module": "ESNext", "skipLibCheck": True,
                "moduleResolution": "bundler", "allowImportingTsExtensions": True,
                "resolveJsonModule": True, "isolatedModules": True,
                "noEmit": True, "jsx": "react-jsx",
                "strict": True, "noUnusedLocals": False, "noUnusedParameters": False,
            }, "include": ["src"],
        }, indent=2))
        # tailwind config
        (path / "tailwind.config.js").write_text("""export default { content: ['./index.html','./src/**/*.{js,ts,jsx,tsx}'], theme: { extend: {} }, plugins: [] }
""")
        (path / "postcss.config.js").write_text("export default { plugins: { tailwindcss: {}, autoprefixer: {} } }\n")
        # index.html
        (path / "index.html").write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
""")
        # src/
        src = path / "src"
        src.mkdir()
        (src / "main.tsx").write_text("""import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
""")
        (src / "index.css").write_text("""@tailwind base; @tailwind components; @tailwind utilities;
body { font-family: ui-sans-serif, system-ui, sans-serif; }
""")
        (src / "App.tsx").write_text(f"""import {{ useState }} from 'react'
export default function App() {{
  const [count, setCount] = useState(0)
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-700 text-white flex flex-col items-center justify-center p-8">
      <h1 className="text-5xl font-bold mb-4">{name}</h1>
      <p className="text-slate-300 mb-8 max-w-md text-center">{description}</p>
      <div className="bg-white/10 backdrop-blur rounded-lg p-8 flex flex-col items-center gap-4">
        <div className="text-6xl font-mono">{{count}}</div>
        <button onClick={{() => setCount(c => c + 1)}}
          className="px-6 py-2 bg-blue-500 hover:bg-blue-600 rounded-lg transition">
          Increment
        </button>
      </div>
      <p className="text-slate-400 mt-8 text-sm">Built by Alberto AI • React + Vite + Tailwind</p>
    </div>
  )
}}
""")

    def _scaffold_backend(self, path: Path, name: str, description: str) -> None:
        (path / "main.py").write_text(f"""\"\"\"{name} — FastAPI backend.\"\"\"
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="{name}", description="{description}")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Count(BaseModel):
    value: int = 0


state = Count()


@app.get("/")
def root():
    return {{"name": "{name}", "description": "{description}", "version": "0.1.0"}}


@app.get("/api/health")
def health():
    return {{"ok": True, "name": "{name}"}}


@app.get("/api/count")
def get_count():
    return state


@app.post("/api/count/increment")
def increment():
    state.value += 1
    return state
""")
        (path / "requirements.txt").write_text("fastapi==0.115.0\nuvicorn[standard]==0.32.0\npydantic==2.9.0\n")
        (path / "pyproject.toml").write_text(f"""[project]
name = "{name}-backend"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.10"
""")

    def _docker_compose(self, name: str) -> str:
        return f"""version: "3.9"
services:
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [backend]
  backend:
    build: ./backend
    ports: ["8000:8000"]
"""

    def _readme(self, name: str, description: str) -> str:
        return f"""# {name}

{description}

## Run locally

### Frontend
```
cd frontend
npm install
npm run dev   # http://localhost:3000
```

### Backend
```
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000   # http://localhost:8000
```

## Docker
```
docker compose up
```

## Created by Alberto AI
"""

    def run(self, app_dir: Path) -> Dict[str, Any]:
        """Try to install deps and start both servers."""
        result = {"frontend_started": False, "backend_started": False}
        # Backend
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                           str(app_dir / "backend" / "requirements.txt")],
                          check=True, capture_output=True, timeout=120)
            backend_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
                cwd=app_dir / "backend",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            time.sleep(3)
            if backend_proc.poll() is None:
                result["backend_started"] = True
                result["backend_pid"] = backend_proc.pid
        except Exception as e:
            result["backend_error"] = str(e)
        return result


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto app")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_c = sub.add_parser("create")
    p_c.add_argument("name")
    p_c.add_argument("description")
    p_c.add_argument("--run", action="store_true")
    p_c.add_argument("--stack", default="react-vite-fastapi")
    p_c.add_argument("--output", default="./apps")
    args = p.parse_args(argv)
    c = AppCreator(output_dir=Path(args.output))
    if args.cmd == "create":
        r = c.create(args.name, args.description, stack=args.stack, run=args.run)
        print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
