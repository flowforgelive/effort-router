"""Texts rendered from the policy: the full class table for docs and the compact guide for the model."""

from . import policy as policy_mod


def _rows(policy):
    claude = policy["hosts"]["claude"]
    models = claude.get("models", {})
    agy_tiers = policy["hosts"]["agy"]["tiers"]
    for klass, spec in policy["classes"].items():
        level = policy_mod.clamp(spec["level"], policy)
        agent = claude["read_only_agent"] if spec.get("read_only") else claude["agents"][level]
        yield klass, spec, level, claude["agent_prefix"] + agent, models.get(klass), agy_tiers.get(level, "inherit")


def _footer(policy):
    floor = policy.get("floor") or {}
    return (
        f"Класс не ясен — уровень `{policy['default_level']}`. "
        + (f"Минимум `{floor['level']}` — {floor['why'][0].lower()}{floor['why'][1:]} " if floor else "")
        + f"Потолок для субагентов — `{policy['levels'][-1]}` (`max` не используется)."
    )


def table(policy):
    """Markdown table for SKILL.md and the host rule files."""
    rows = [
        "| Класс | Уровень | Когда | Claude Code | Codex `spawn_agent` | agy `invoke_subagent` |",
        "|---|---|---|---|---|---|",
    ]
    for klass, spec, level, agent, model, tier in _rows(policy):
        claude_cell = f"`{agent}`" + (f" + `model: \"{model}\"`" if model else "")
        rows.append(
            f"| `{klass}` | `{level}` | {spec['summary']} | {claude_cell} "
            f"| `reasoning_effort: \"{level}\"` | `Model: \"{tier}\"` |"
        )
    return "\n".join(rows + ["", _footer(policy)])


def claude_guide(policy):
    """Compact guide the model gets at session start and when a spawn is bounced."""
    lines = []
    for klass, spec, level, agent, model, _ in _rows(policy):
        model_part = f", model: \"{model}\"" if model else ""
        lines.append(f"- {klass} ({level}): subagent_type: \"{agent}\"{model_part} — {spec['summary']}")
    default_agent = policy["hosts"]["claude"]["agent_prefix"] + policy["hosts"]["claude"]["agents"][policy["default_level"]]
    return "\n".join(
        [
            "effort-router: у инструмента Agent нет параметра effort — уровень reasoning effort субагента "
            "задаёт выбранный агент. Перед каждым спавном определи класс подзадачи и выбери агента "
            "(и модель, если указана) по таблице:",
            *lines,
            f"Класс не ясен — \"{default_agent}\". {_footer(policy)}",
            "При сомнении между соседними классами бери более трудный. Результат дешёвого уровня проверяй "
            "(тест, сборка, grep); при провале или ответе ESCALATE: повтори на одну ступень выше, не больше двух раз. "
            "Свой агент (не general-purpose/Explore) и явное указание пользователя важнее таблицы.",
        ]
    )
