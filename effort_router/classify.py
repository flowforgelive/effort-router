"""Heuristic task classifier: the fallback when the orchestrator did not pick a level itself."""

import re
from dataclasses import dataclass

from . import policy as policy_mod


@dataclass(frozen=True)
class Decision:
    klass: str  # class id, or "default" when no signal matched
    level: str
    read_only: bool
    floored: bool


def _hits(patterns, text):
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))


def classify(text, policy):
    levels = policy["levels"]
    best, best_score = None, 0
    for klass, spec in policy["classes"].items():
        score = _hits(spec.get("signals", []), text)
        if score == 0:
            continue
        # On a tie the more demanding class wins: over-spending one tier is
        # cheaper than a wrong answer from an under-powered worker.
        if score > best_score or (
            score == best_score
            and levels.index(spec["level"]) > levels.index(policy["classes"][best]["level"])
        ):
            best, best_score = klass, score

    if best is None:
        klass, level, read_only = "default", policy["default_level"], False
    else:
        spec = policy["classes"][best]
        klass, level, read_only = best, policy_mod.clamp(spec["level"], policy), bool(spec.get("read_only"))

    floor = policy.get("floor") or {}
    floored = bool(floor) and _hits(floor.get("signals", []), text) > 0
    if floored:
        raised = policy_mod.raise_to(level, floor["level"], policy)
        floored = raised != level
        level = raised
    return Decision(klass, level, read_only and not floored, floored)
