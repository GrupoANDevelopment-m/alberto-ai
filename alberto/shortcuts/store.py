"""Persistent JSON-backed shortcut registry.

Path: /sandbox/.mimo/shortcuts.json (auto-created on first add)

Format: {
  "ms": {
    "expansion": "/nemomimo memory search {{args}}",
    "use_count": 3,
    "created_at": "2026-07-04T10:00:00Z"
  },
  ...
}

`{{args}}` placeholder is replaced at invocation time.
"""
from __future__ import annotations
import json
import os
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional


@dataclass
class Shortcut:
    expansion: str
    use_count: int = 0
    created_at: str = ""


class ShortcutStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Shortcut] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict):
                    self._data[k] = Shortcut(
                        expansion=v.get("expansion", ""),
                        use_count=v.get("use_count", 0),
                        created_at=v.get("created_at", ""),
                    )

    def _save(self) -> None:
        payload = {k: asdict(v) for k, v in self._data.items()}
        # atomic write via tmp + rename
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def add(self, key: str, expansion: str) -> Shortcut:
        sc = Shortcut(
            expansion=expansion,
            use_count=0,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._data[key] = sc
        self._save()
        return sc

    def remove(self, key: str) -> bool:
        if key in self._data:
            self._data.pop(key)
            self._save()
            return True
        return False

    def get(self, key: str) -> Optional[Shortcut]:
        return self._data.get(key)

    def list(self) -> Dict[str, Shortcut]:
        return dict(self._data)

    def expand(self, key: str, args: str = "") -> Optional[str]:
        sc = self._data.get(key)
        if sc is None:
            return None
        expansion = sc.expansion
        # Substitute {{args}} once if present
        if "{{args}}" in expansion:
            expansion = expansion.replace("{{args}}", args)
        sc.use_count += 1
        self._save()
        return expansion