"""Loads the routing policy: the repo's policy.json merged with an optional user override."""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / "policy.json"


def user_override_path():
    explicit = os.environ.get("EFFORT_ROUTER_POLICY")
    if explicit:
        return Path(explicit).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "effort-router" / "policy.json"


def _merge(base, override):
    """Dicts merge recursively; every other value (lists included) is replaced."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        merged[key] = _merge(base.get(key), value) if key in base else value
    return merged


def load(policy_path=None):
    with open(policy_path or DEFAULT_POLICY, encoding="utf-8") as fh:
        policy = json.load(fh)
    override = user_override_path()
    if policy_path is None and override.is_file():
        with open(override, encoding="utf-8") as fh:
            policy = _merge(policy, json.load(fh))
    return policy


def clamp(level, policy):
    """A level the policy allows; anything above the top level (e.g. max) is capped."""
    levels = policy["levels"]
    if level in levels:
        return level
    return levels[-1] if level in ("max", "ultra") else policy["default_level"]


def raise_to(level, floor, policy):
    levels = policy["levels"]
    return floor if levels.index(level) < levels.index(floor) else level
