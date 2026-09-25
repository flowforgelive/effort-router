#!/usr/bin/env python3
"""Claude Code PreToolUse hook on Agent: make every generic spawn run at a chosen effort.

Mode (policy hosts.claude.mode):
  ask   — bounce a generic spawn (general-purpose, Explore, none) once with the
          class guide, so the model picks the effort agent itself; a repeat of
          the same spawn is routed heuristically instead of bounced again
  route — silently rewrite a generic spawn onto the heuristic's effort agent
  off   — do nothing
An agent the model named itself is never touched. Fail-open: any error leaves
the spawn unchanged. EFFORT_ROUTER=off disables the hook.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    if os.environ.get("EFFORT_ROUTER") == "off":
        return
    from effort_router import dispatch_log, guide, hookio, policy, route

    event = hookio.read_event()
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    pol = policy.load()
    mode = route.claude_mode(pol)
    if mode == "off" or not route.claude_is_generic(tool_input, pol):
        return

    session = event.get("session_id") or "unknown"
    key = hookio.spawn_key(tool_input)
    requested = tool_input.get("subagent_type") or ""
    if mode == "ask" and not hookio.was_asked(session, key):
        hookio.mark_asked(session, key)
        dispatch_log.record("claude", "ask", requested=requested, cwd=event.get("cwd"))
        hookio.emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Спавн \"{requested or 'default'}\" не выбрал уровень effort и унаследовал бы effort сессии. "
                        "Повтори этот же вызов Agent с subagent_type (и model, если указана) по классу задачи.\n"
                        + guide.claude_guide(pol)
                    ),
                }
            }
        )
        return

    updated, decision = route.claude_agent(tool_input, pol)
    dispatch_log.record(
        "claude",
        "rewrite" if updated else "keep",
        requested=requested,
        routed=(updated or {}).get("subagent_type"),
        klass=decision.klass if decision else None,
        level=decision.level if decision else None,
        floored=decision.floored if decision else None,
        cwd=event.get("cwd"),
    )
    if updated:
        hookio.emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": updated,
                }
            }
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
