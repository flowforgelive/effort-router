#!/usr/bin/env python3
"""Claude Code PreToolUse hook on Agent: route generic spawns to an effort-pinned agent.

Fail-open: any error leaves the spawn unchanged. EFFORT_ROUTER=off disables it.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    if os.environ.get("EFFORT_ROUTER") == "off":
        return
    from effort_router import dispatch_log, policy, route

    event = json.load(sys.stdin)
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    updated, decision = route.claude_agent(tool_input, policy.load())
    if decision is not None:
        dispatch_log.record(
            "claude",
            "rewrite" if updated else "keep",
            requested=tool_input.get("subagent_type") or "",
            routed=(updated or {}).get("subagent_type"),
            klass=decision.klass,
            level=decision.level,
            floored=decision.floored,
            cwd=event.get("cwd"),
        )
    if updated:
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": updated,
                }
            },
            sys.stdout,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
