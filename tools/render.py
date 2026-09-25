#!/usr/bin/env python3
"""Render the class table from policy.json into every document that shows it.

  python3 tools/render.py          rewrite the tables in place
  python3 tools/render.py --check  exit 1 if any table drifted from policy.json
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from effort_router import guide  # noqa: E402
from effort_router import policy as policy_mod  # noqa: E402

TARGETS = [
    ROOT / "skills" / "effort-routing" / "SKILL.md",
    ROOT / "hosts" / "codex" / "AGENTS.block.md",
    ROOT / "hosts" / "agy" / "rules" / "AGENTS.md",
]
BEGIN = "<!-- effort-router:classes:begin -->"
END = "<!-- effort-router:classes:end -->"


def render(text, block):
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"markers {BEGIN} … {END} not found")
    return pattern.sub(lambda _: f"{BEGIN}\n{block}\n{END}", text)


def main():
    check = "--check" in sys.argv[1:]
    block = guide.table(policy_mod.load(policy_mod.DEFAULT_POLICY))
    drifted = []
    for path in TARGETS:
        current = path.read_text(encoding="utf-8")
        wanted = render(current, block)
        if wanted != current:
            drifted.append(path.relative_to(ROOT))
            if not check:
                path.write_text(wanted, encoding="utf-8")
    if check and drifted:
        print("class table drifted from policy.json in: " + ", ".join(map(str, drifted)))
        print("run: python3 tools/render.py")
        return 1
    for path in drifted:
        print(f"rendered {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
