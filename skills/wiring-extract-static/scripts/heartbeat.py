#!/usr/bin/env python3
"""heartbeat.py — background claim heartbeat for wiring-extract-static.

Per design 2026-04-14 §5.1 + S014 claim protocol. Invokes
``~/.claude/skills/_meta/claims.py heartbeat <claim_uuid>`` every 60s.
On any non-ok response (``stale``, ``expired``, ``revoked``, subprocess
failure) the heartbeat sets a shared-stop ``threading.Event`` so the
main extractor loop exits cleanly.

Single-writer invariant preserved: this module never touches the
claim file directly; it only invokes ``claims.py`` which is the
bob-owned writer.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

DEFAULT_INTERVAL_SECONDS = 60

_CLAIMS_SCRIPT = Path.home() / ".claude" / "skills" / "_meta" / "claims.py"


class HeartbeatThread(threading.Thread):
    """Background daemon that heartbeats a claim until told to stop.

    Usage:
        stop_event = threading.Event()
        hb = HeartbeatThread(claim_uuid, project_root, stop_event)
        hb.start()
        ...
        stop_event.set()
        hb.join()
        if hb.last_state != "ok":
            # bob has revoked; propagate to main loop
            sys.exit(1)
    """

    def __init__(
        self,
        claim_uuid: str,
        project_root: Path,
        stop_event: threading.Event,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        claims_script: Path = _CLAIMS_SCRIPT,
    ) -> None:
        super().__init__(daemon=True, name=f"heartbeat-{claim_uuid[:8]}")
        self.claim_uuid = claim_uuid
        self.project_root = project_root.resolve()
        self.stop_event = stop_event
        self.interval_seconds = max(1, interval_seconds)
        self.claims_script = claims_script
        self.last_state: str = "ok"
        self.last_error: Optional[str] = None

    def _one_beat(self) -> str:
        """Invoke claims.py heartbeat <uuid>. Returns raw state string."""
        try:
            cp = subprocess.run(
                [
                    sys.executable,
                    str(self.claims_script),
                    "heartbeat",
                    self.claim_uuid,
                    "--project-root",
                    str(self.project_root),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            self.last_error = "heartbeat subprocess timeout"
            return "expired"
        except Exception as e:  # noqa: BLE001
            self.last_error = f"heartbeat subprocess error: {e}"
            return "expired"
        out = (cp.stdout or "").strip().splitlines()
        return out[-1] if out else ("ok" if cp.returncode == 0 else "expired")

    def run(self) -> None:
        # First beat immediately so caller can detect revoked claim at startup
        self.last_state = self._one_beat()
        if self.last_state != "ok":
            self.stop_event.set()
            return
        while not self.stop_event.wait(timeout=self.interval_seconds):
            state = self._one_beat()
            self.last_state = state
            if state != "ok":
                # Signal main loop to stop; do not raise
                self.stop_event.set()
                return
