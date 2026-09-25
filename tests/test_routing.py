import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from effort_router import policy as policy_mod  # noqa: E402
from effort_router import route  # noqa: E402
from effort_router.classify import classify  # noqa: E402

POLICY = policy_mod.load(policy_mod.DEFAULT_POLICY)


class ClassifyTest(unittest.TestCase):
    def assertClass(self, text, klass, level):
        decision = classify(text, POLICY)
        self.assertEqual((decision.klass, decision.level), (klass, level), text)

    def test_russian_and_english_classes(self):
        self.assertClass("Найди все места, где вызывается parseConfig", "scout", "low")
        self.assertClass("Find all usages of parseConfig in src/", "scout", "low")
        self.assertClass("Переименуй UserDto в UserView во всём модуле", "mechanical", "low")
        self.assertClass("Реализуй функцию normalizePhone и напиши тест", "implement", "medium")
        self.assertClass("Почему падает тест LoginTest после мержа? Разбери стектрейс", "debug", "high")
        self.assertClass("Оцени архитектуру модуля и компромиссы двух подходов", "deep", "xhigh")

    def test_unclassified_gets_default_level(self):
        self.assertClass("Сделай что-нибудь полезное с этим", "default", "medium")

    def test_floor_raises_risky_work(self):
        decision = classify("Реализуй миграцию таблицы users", POLICY)
        self.assertEqual((decision.klass, decision.level, decision.floored), ("implement", "high", True))

    def test_floor_makes_search_writable_class_not_read_only(self):
        decision = classify("Найди все места с уязвимостью SQL-инъекции", POLICY)
        self.assertEqual(decision.level, "high")
        self.assertFalse(decision.read_only)

    def test_max_is_capped(self):
        self.assertEqual(policy_mod.clamp("max", POLICY), "xhigh")


class ClaudeRouteTest(unittest.TestCase):
    def test_general_purpose_is_routed_by_class(self):
        updated, _ = route.claude_agent(
            {"subagent_type": "general-purpose", "prompt": "Переименуй foo в bar", "description": "rename"},
            POLICY,
        )
        self.assertEqual(updated["subagent_type"], "effort-router:effort-low")
        self.assertEqual(updated["prompt"], "Переименуй foo в bar")

    def test_missing_type_is_routed(self):
        updated, _ = route.claude_agent({"prompt": "Implement a retry wrapper"}, POLICY)
        self.assertEqual(updated["subagent_type"], "effort-router:effort-medium")

    def test_explore_becomes_scout_only_for_search(self):
        updated, _ = route.claude_agent({"subagent_type": "Explore", "prompt": "Где определён AuthGate?"}, POLICY)
        self.assertEqual(updated["subagent_type"], "effort-router:effort-scout")
        kept, _ = route.claude_agent(
            {"subagent_type": "Explore", "prompt": "Разбери архитектуру и компромиссы слоя хранения"}, POLICY
        )
        self.assertIsNone(kept)

    def test_explicit_agents_are_respected(self):
        for requested in ("effort-router:effort-high", "deep-reasoner", "Plan", "codex-cli"):
            updated, _ = route.claude_agent({"subagent_type": requested, "prompt": "переименуй x"}, POLICY)
            self.assertIsNone(updated, requested)

    def test_explicit_model_is_kept(self):
        updated, _ = route.claude_agent(
            {"subagent_type": "general-purpose", "model": "sonnet", "prompt": "Implement a parser"}, POLICY
        )
        self.assertEqual(updated["model"], "sonnet")


class AgyRouteTest(unittest.TestCase):
    def test_low_work_goes_to_cheap_tier_and_hard_work_inherits(self):
        overwrite, _ = route.agy_invoke(
            {
                "Subagents": [
                    {"TypeName": "a", "Prompt": "Найди все файлы с TODO", "Model": "inherit"},
                    {"TypeName": "b", "Prompt": "Почему падает сборка? Найди корневую причину"},
                    {"TypeName": "c", "Prompt": "Переименуй foo", "Model": "pro"},
                ]
            },
            POLICY,
        )
        models = [s.get("Model") for s in overwrite["Subagents"]]
        self.assertEqual(models, ["flash", None, "pro"])

    def test_nothing_to_change_returns_none(self):
        overwrite, _ = route.agy_invoke({"Subagents": [{"Prompt": "Разбери архитектуру"}]}, POLICY)
        self.assertIsNone(overwrite)


class HookProcessTest(unittest.TestCase):
    def run_hook(self, script, payload, **env):
        with tempfile.TemporaryDirectory() as state:
            result = subprocess.run(
                [sys.executable, str(ROOT / script)],
                input=payload if isinstance(payload, str) else json.dumps(payload),
                capture_output=True,
                text=True,
                env={**os.environ, "XDG_STATE_HOME": state, "EFFORT_ROUTER_POLICY": "/nonexistent", **env},
                timeout=30,
            )
            log = Path(state) / "effort-router" / "dispatch.jsonl"
            return result, (log.read_text() if log.exists() else "")

    def test_claude_hook_emits_updated_input_and_logs(self):
        result, log = self.run_hook(
            "hooks/claude_pre_agent.py",
            {"tool_input": {"subagent_type": "general-purpose", "prompt": "Find all usages of foo"}},
        )
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertEqual(out["updatedInput"]["subagent_type"], "effort-router:effort-low")
        self.assertIn('"action": "rewrite"', log)

    def test_claude_hook_fails_open(self):
        result, _ = self.run_hook("hooks/claude_pre_agent.py", "not json")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_claude_hook_can_be_disabled(self):
        result, _ = self.run_hook(
            "hooks/claude_pre_agent.py",
            {"tool_input": {"subagent_type": "general-purpose", "prompt": "rename x"}},
            EFFORT_ROUTER="off",
        )
        self.assertEqual(result.stdout, "")

    def test_agy_hook_contract(self):
        result, _ = self.run_hook(
            "hosts/agy/hook.py",
            {"toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"Prompt": "Найди все TODO"}]}}},
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "allow")
        self.assertEqual(out["overwrite"]["Subagents"][0]["Model"], "flash")
        broken, _ = self.run_hook("hosts/agy/hook.py", "garbage")
        self.assertEqual(json.loads(broken.stdout), {"decision": "allow"})


class RenderTest(unittest.TestCase):
    def test_tables_match_policy(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "render.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
