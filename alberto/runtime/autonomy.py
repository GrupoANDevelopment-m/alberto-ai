"""24/7 autonomy loop — Alberto runs as a background process.

The loop:
1. wakes up every `tick_seconds` (default 60s)
2. checks inbox (cron, watchers, channels)
3. runs pending tasks
4. emits heartbeat to log
5. sleeps until next tick

Exit conditions:
- SIGINT/SIGTERM (graceful)
- max_iterations reached (test mode)
- fatal error in last 5 iterations
"""
from __future__ import annotations
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger("alberto.autonomy")


class AutonomyLoop:
    """Long-running 24/7 loop. User explicitly enables with `alberto loop`."""

    def __init__(self, alberto, *, tick_seconds: float = 60.0,
                 max_iterations: Optional[int] = None,
                 on_tick: Optional[Callable] = None):
        self.alberto = alberto
        self.tick_seconds = tick_seconds
        self.max_iterations = max_iterations
        self.on_tick = on_tick or self._default_tick
        self.iteration = 0
        self.errors_in_a_row = 0
        self._running = False
        self._stop_flag = False

    def _default_tick(self) -> None:
        """Default tick handler — runs pending cron jobs + watchers."""
        # Run any pending cron jobs (only if implemented)
        if hasattr(self.alberto, "cron_run_pending"):
            try:
                self.alberto.cron_run_pending()
            except Exception as e:
                log.debug("cron tick error: %s", e)
        # Check active watchers
        if hasattr(self.alberto, "watchers_check"):
            try:
                self.alberto.watchers_check()
            except Exception as e:
                log.debug("watchers tick error: %s", e)

    def start(self) -> None:
        """Run the loop. Blocks until stop() called or max_iterations reached."""
        self._running = True
        self._stop_flag = False
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)
        log.info("autonomy loop started (tick=%.1fs)", self.tick_seconds)
        print(f"🟢 Alberto autonomy loop started (tick={self.tick_seconds}s). Ctrl+C to stop.")
        while not self._stop_flag:
            self.iteration += 1
            try:
                self.on_tick()
                self.errors_in_a_row = 0
            except Exception as e:
                self.errors_in_a_row += 1
                log.error("tick %d error: %s", self.iteration, e)
                if self.errors_in_a_row >= 5:
                    log.critical("5 errors in a row, stopping")
                    break
            if self.max_iterations and self.iteration >= self.max_iterations:
                log.info("max_iterations (%d) reached", self.max_iterations)
                break
            # Sleep in small chunks so signals are caught quickly
            for _ in range(int(self.tick_seconds * 10)):
                if self._stop_flag:
                    break
                time.sleep(0.1)
        self._running = False
        print("🔴 Alberto autonomy loop stopped.")

    def stop(self) -> None:
        self._stop_flag = True

    def _on_signal(self, signum, frame) -> None:
        log.info("received signal %d, stopping", signum)
        self._stop_flag = True


def main(argv: List[str]) -> int:
    """CLI entry: `alberto loop [--tick 60] [--max 10]`"""
    import argparse
    p = argparse.ArgumentParser(prog="alberto loop")
    p.add_argument("--tick", type=float, default=60.0, help="seconds between ticks")
    p.add_argument("--max", type=int, default=None, help="stop after N iterations (test mode)")
    args = p.parse_args(argv)
    from alberto import Alberto
    a = Alberto()
    loop = AutonomyLoop(a, tick_seconds=args.tick, max_iterations=args.max)
    loop.start()
    a.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
