"""Engine protocol — minimum contract."""
from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass
class EngineInfo:
    name: str
    version: str
    running: bool
    pid: int | None


@runtime_checkable
class EngineProtocol(Protocol):
    @property
    def info(self) -> EngineInfo: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def invoke(self, prompt: str, **kwargs) -> str: ...