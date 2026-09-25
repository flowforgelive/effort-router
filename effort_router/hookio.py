"""Hook plumbing shared by the entry points: encoding-safe stdin/stdout and per-session state."""

import hashlib
import json
import sys
import time

from . import dispatch_log

ASKED_TTL_SECONDS = 2 * 24 * 3600


def read_event():
    # Hooks get UTF-8 JSON; the console code page (cp1251/cp1252 on Windows)
    # must not decide how a Russian prompt is decoded.
    return json.loads(sys.stdin.buffer.read().decode("utf-8"))


def emit(payload):
    # ensure_ascii keeps stdout ASCII-only, so the console encoding cannot mangle it.
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def _asked_file(session_id):
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_") or "unknown"
    return dispatch_log.log_path().parent / "asked" / f"{safe}.txt"


def spawn_key(tool_input):
    raw = json.dumps([tool_input.get("subagent_type") or "", tool_input.get("prompt") or ""], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def was_asked(session_id, key):
    path = _asked_file(session_id)
    return path.exists() and key in path.read_text(encoding="utf-8").split()


def mark_asked(session_id, key):
    path = _asked_file(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(key + "\n")
    cutoff = time.time() - ASKED_TTL_SECONDS
    for stale in path.parent.glob("*.txt"):
        if stale.stat().st_mtime < cutoff:
            stale.unlink(missing_ok=True)
