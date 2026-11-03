"""
Orchestrator — decides per task whether to use MiMo solo, speculative, or squad.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Strategy:
    mode: str            # "solo" | "speculative" | "squad"
    reason: str
    engine: str          # "mimo" | "hermes" | "both"
    squad: Optional[str] = None
    task_routing: str = "chat"


class Orchestrator:
    """Picks a strategy based on task content + squad state."""

    def __init__(self, *, default_task: str = "chat"):
        self.default_task = default_task

    def decide(self, text: str, *, active_squad: Optional[str] = None,
               hermes_command: Optional[str] = None) -> Strategy:
        t = text.lower().strip()

        # Hermes-specific commands
        if hermes_command in ("browser", "code-exec", "computer-use", "cron"):
            return Strategy(
                mode="solo",
                reason=f"hermes command '{hermes_command}' detected",
                engine="hermes",
                task_routing="chat",
            )

        # Squad active -> squad-pipeline mode
        if active_squad:
            return Strategy(
                mode="squad",
                reason=f"active squad '{active_squad}'",
                engine="both",
                squad=active_squad,
                task_routing=self.default_task,
            )

        # Explicit software-engineering requests use the code task. Ordinary
        # conversation remains on the chat task; never infer "code" by default.
        if re.search(
            r"\b("
            r"program(?:a|ar|e)|codific(?:a|ar|e)|implement(?:a|ar|e)|"
            r"corrig(?:e|ir|a)|consert(?:a|ar|e)|depur(?:a|ar|e)|debug(?:ue|ar)?|"
            r"refator(?:a|ar|e)|edit(?:a|e|ar)\s+(?:o\\s+)?c[oó]digo|"
            r"crie?\s+(?:uma?\s+)?(?:fun[cç][aã]o|classe|m[oó]dulo|script)|"
            r"write\s+code|implement|debug|refactor|fix\s+(?:the\s+)?code|"
            r"modify\s+(?:the\s+)?code|run\s+tests?|"
            r"execut(?:e|ar)\s+(?:os?\s+)?testes?"
            r")\b",
            t,
        ):
            return Strategy(
                mode="solo",
                reason="explicit software-engineering request",
                engine="mimo",
                task_routing="code",
            )

        # Speculative: "best", "compare", "tradeoff"
        if re.search(r"\b(best|compare|trade-?off|alternative|pros and cons)\b", t):
            return Strategy(
                mode="speculative",
                reason="task asks for comparison/best-of",
                engine="mimo",
                task_routing="reasoning",
            )

        # Speculative: explicit "max mode"
        if "max mode" in t or "max-mode" in t:
            return Strategy(
                mode="speculative",
                reason="user invoked max-mode",
                engine="mimo",
                task_routing="reasoning",
            )

        # Solo: default
        return Strategy(
            mode="solo",
            reason="default single-engine",
            engine="mimo",
            task_routing=self.default_task,
        )