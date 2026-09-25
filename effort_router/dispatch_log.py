"""Local JSONL log of routing decisions — input for later recalibration of the policy."""

import json
import os
import time
from pathlib import Path


def log_path():
    state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state_home) / "effort-router" / "dispatch.jsonl"


def record(host, action, **fields):
    """Never raises: logging must not break a spawn."""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": round(time.time(), 3), "host": host, "action": action, **fields}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
