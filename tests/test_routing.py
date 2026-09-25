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
        self.assertEqual(updated["model"], "sonnet")
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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        self.override = Path(self.tmp.name) / "policy.json"

    def run_hook(self, script, payload, **env):
        result = subprocess.run(
            [sys.executable, str(ROOT / script)],
            input=(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)).encode("utf-8"),
            capture_output=True,
            env={**os.environ, "XDG_STATE_HOME": str(self.state), "EFFORT_ROUTER_POLICY": str(self.override), **env},
            timeout=30,
        )
        result.stdout = result.stdout.decode("utf-8")
        log = self.state / "effort-router" / "dispatch.jsonl"
        return result, (log.read_text(encoding="utf-8") if log.exists() else "")

    def spawn(self, prompt, session="s1", subagent_type="general-purpose"):
        return {"session_id": session, "tool_input": {"subagent_type": subagent_type, "prompt": prompt}}

    def test_ask_mode_bounces_once_with_guide_then_routes(self):
        first, log = self.run_hook("hooks/claude_pre_agent.py", self.spawn("Найди все использования foo"))
        out = json.loads(first.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("effort-router:effort-scout", out["permissionDecisionReason"])
        self.assertIn('"action": "ask"', log)

        # The model repeats the very same generic spawn: route it, never loop.
        second, log = self.run_hook("hooks/claude_pre_agent.py", self.spawn("Найди все использования foo"))
        out = json.loads(second.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertEqual(out["updatedInput"]["subagent_type"], "effort-router:effort-low")
        self.assertIn('"action": "rewrite"', log)

    def test_ask_mode_is_per_session(self):
        self.run_hook("hooks/claude_pre_agent.py", self.spawn("rename x", session="a"))
        other, _ = self.run_hook("hooks/claude_pre_agent.py", self.spawn("rename x", session="b"))
        self.assertEqual(json.loads(other.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_chosen_agent_passes_untouched(self):
        result, _ = self.run_hook(
            "hooks/claude_pre_agent.py", self.spawn("rename x", subagent_type="effort-router:effort-low")
        )
        self.assertEqual(result.stdout, "")

    def test_route_mode_rewrites_silently(self):
        self.override.write_text(json.dumps({"hosts": {"claude": {"mode": "route"}}}), encoding="utf-8")
        result, _ = self.run_hook("hooks/claude_pre_agent.py", self.spawn("Переименуй foo в bar"))
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["updatedInput"]["subagent_type"], "effort-router:effort-low")
        self.assertEqual(out["updatedInput"]["model"], "sonnet")

    def test_session_start_injects_guide(self):
        result, _ = self.run_hook("hooks/claude_session_start.py", {"session_id": "s1"})
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("effort-router:effort-xhigh", out["additionalContext"])

    def test_off_mode_disables_both_hooks(self):
        self.override.write_text(json.dumps({"hosts": {"claude": {"mode": "off"}}}), encoding="utf-8")
        for script, payload in (
            ("hooks/claude_pre_agent.py", self.spawn("rename x")),
            ("hooks/claude_session_start.py", {"session_id": "s1"}),
        ):
            result, _ = self.run_hook(script, payload)
            self.assertEqual(result.stdout, "", script)

    def test_claude_hook_fails_open(self):
        result, _ = self.run_hook("hooks/claude_pre_agent.py", "not json")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_claude_hook_can_be_disabled(self):
        result, _ = self.run_hook(
            "hooks/claude_pre_agent.py",
            self.spawn("rename x"),
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
