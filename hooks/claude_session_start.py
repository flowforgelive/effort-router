#!/usr/bin/env python3
"""Claude Code SessionStart hook: give the model the effort guide before it delegates anything.

Fail-open: any error adds nothing. EFFORT_ROUTER=off disables the hook.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    if os.environ.get("EFFORT_ROUTER") == "off":
        return
    from effort_router import guide, hookio, policy, route

    pol = policy.load()
    if route.claude_mode(pol) == "off":
        return
    hookio.emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": guide.claude_guide(pol),
            }
        }
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
