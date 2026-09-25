#!/usr/bin/env python3
"""agy PreToolUse hook on invoke_subagent: send low-level subtasks to the cheap model tier.

Fail-open: any error leaves the call unchanged. EFFORT_ROUTER=off disables it.
"""

import os
import sys
from pathlib import Path

# The installer points the hook at this file inside the repo; resolve the package from there.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

ALLOW = {"decision": "allow"}


def main():
    if os.environ.get("EFFORT_ROUTER") == "off":
        return ALLOW
    from effort_router import dispatch_log, hookio, policy, route

    event = hookio.read_event()
    call = event.get("toolCall") or {}
    if call.get("name") != "invoke_subagent" or not isinstance(call.get("args"), dict):
        return ALLOW
    overwrite, decisions = route.agy_invoke(call["args"], policy.load())
    for decision in decisions:
        dispatch_log.record(
            "agy",
            "rewrite" if overwrite else "keep",
            klass=decision.klass,
            level=decision.level,
            floored=decision.floored,
            conversation=event.get("conversationId"),
        )
    return {**ALLOW, "overwrite": overwrite} if overwrite else ALLOW


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        result = ALLOW
    try:
        from effort_router import hookio

        hookio.emit(result)
    except Exception:
        sys.stdout.write('{"decision": "allow"}')
    sys.exit(0)
