"""Per-host spawn rewriting. Pure functions: tool input in, rewritten input (or None = leave as is) out."""

from .classify import classify


def _task_text(*parts):
    return "\n".join(p for p in parts if isinstance(p, str))


def claude_agent(tool_input, policy):
    """Rewrite a Claude Code Agent call onto an effort-pinned agent.

    Claude Code has no per-spawn effort parameter; effort comes only from an
    agent's frontmatter. So a generic spawn (general-purpose, Explore, none) is
    redirected to the agent pinned at the level its task class needs. An agent
    the orchestrator named itself — ours or anyone's — is left untouched.
    Returns (updated_input, decision) or (None, decision).
    """
    host = policy["hosts"]["claude"]
    requested = tool_input.get("subagent_type") or ""
    if requested not in host["routable_types"]:
        return None, None

    decision = classify(_task_text(tool_input.get("description"), tool_input.get("prompt")), policy)
    if requested == "Explore":
        # Explore is read-only by contract, so it may only become the
        # read-only scout. A search with no class signal is still a search;
        # a search that reads as hard (or hit the floor) keeps Explore.
        if not (decision.read_only or (decision.klass == "default" and not decision.floored)):
            return None, decision
        agent = host["read_only_agent"]
    else:
        agent = host["agents"][decision.level]

    updated = dict(tool_input)
    updated["subagent_type"] = host["agent_prefix"] + agent
    return updated, decision


def agy_invoke(args, policy):
    """Rewrite an agy invoke_subagent call.

    agy exposes only a model tier per subagent: an explicit tier always runs
    at its -low variant, `inherit` runs at the parent's model and effort. So
    low-level work is sent to the configured cheap tier, and everything else
    keeps inheriting. An explicit tier chosen by the caller is kept.
    """
    tiers = policy["hosts"]["agy"]["tiers"]
    subagents = args.get("Subagents")
    if not isinstance(subagents, list):
        return None, []

    changed, decisions = False, []
    rewritten = []
    for sub in subagents:
        sub = dict(sub) if isinstance(sub, dict) else sub
        if isinstance(sub, dict) and sub.get("Model", "inherit") == "inherit":
            decision = classify(_task_text(sub.get("Role"), sub.get("Prompt")), policy)
            decisions.append(decision)
            tier = tiers.get(decision.level)
            if tier:
                sub["Model"] = tier
                changed = True
        rewritten.append(sub)
    return ({"Subagents": rewritten} if changed else None), decisions
