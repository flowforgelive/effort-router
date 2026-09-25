import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install  # noqa: E402


class BlockTest(unittest.TestCase):
    def test_upsert_is_idempotent_and_replaces_in_place(self):
        base = "# Mine\n\nkeep me\n"
        once = install.upsert_block(base, "v1")
        self.assertEqual(install.upsert_block(once, "v1"), once)
        twice = install.upsert_block(once, "v2")
        self.assertIn("v2", twice)
        self.assertNotIn("v1", twice)
        self.assertTrue(twice.startswith("# Mine\n\nkeep me\n"))

    def test_remove_restores_original(self):
        base = "# Mine\n\nkeep me\n"
        self.assertEqual(install.remove_block(install.upsert_block(base, "x")), base)

    def test_upsert_into_empty_file(self):
        self.assertTrue(install.upsert_block("", "x").startswith(install.BLOCK_BEGIN))


class TomlTest(unittest.TestCase):
    CONFIG = 'model = "m"\nmodel_reasoning_effort = "max"\n\n[profiles.x]\nmodel_reasoning_effort = "low"\n'

    def test_drops_only_top_level_key(self):
        out = install.drop_toml_key(self.CONFIG, None, "model_reasoning_effort")
        self.assertEqual(out, 'model = "m"\n\n[profiles.x]\nmodel_reasoning_effort = "low"\n')

    def test_drops_key_inside_named_table(self):
        grok = '[models]\ndefault = "g"\ndefault_reasoning_effort = "xhigh"\n\n[ui]\ndefault_reasoning_effort = "keep"\n'
        out = install.drop_toml_key(grok, "models", "default_reasoning_effort")
        self.assertEqual(out, '[models]\ndefault = "g"\n\n[ui]\ndefault_reasoning_effort = "keep"\n')


class ClaudeSettingsTest(unittest.TestCase):
    def test_drops_global_and_per_model_effort_only(self):
        settings = {
            "language": "Russian",
            "effortLevel": "xhigh",
            "modelSettings": {"a": {"effortLevel": "xhigh", "other": 1}, "b": {}},
        }
        out = json.loads(install.drop_claude_effort(json.dumps(settings, indent=2)))
        self.assertEqual(out, {"language": "Russian", "modelSettings": {"a": {"other": 1}, "b": {}}})


class InstallTreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.installer = install.Installer(dry_run=False, home=self.home, env={})

    def quiet(self, fn, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            fn(*args)
        return out.getvalue()

    def test_codex_install_is_idempotent_and_uninstall_is_clean(self):
        agents = self.home / ".codex" / "AGENTS.md"
        agents.parent.mkdir(parents=True)
        agents.write_text("# mine\n", encoding="utf-8")

        self.quiet(self.installer.codex_install)
        skill = self.home / ".codex" / "skills" / "effort-routing"
        self.assertTrue((skill / "SKILL.md").is_file())
        self.assertIn(install.BLOCK_BEGIN, agents.read_text(encoding="utf-8"))
        self.assertEqual(self.quiet(self.installer.codex_install), "")

        self.quiet(self.installer.codex_uninstall)
        self.assertFalse(skill.exists())
        self.assertEqual(agents.read_text(encoding="utf-8"), "# mine\n")

    def test_foreign_directory_is_not_overwritten(self):
        foreign = self.home / ".gemini" / "config" / "plugins" / "effort-router"
        foreign.mkdir(parents=True)
        (foreign / "theirs.txt").write_text("keep", encoding="utf-8")
        out = self.quiet(self.installer.agy_install)
        self.assertIn("SKIP", out)
        self.assertEqual(sorted(p.name for p in foreign.iterdir()), ["theirs.txt"])
        self.quiet(self.installer.agy_uninstall)
        self.assertTrue((foreign / "theirs.txt").exists())

    def test_agy_plugin_is_complete_and_replaces_old_symlink(self):
        plugin = self.home / ".gemini" / "config" / "plugins" / "effort-router"
        plugin.parent.mkdir(parents=True)
        try:
            plugin.symlink_to(install.ROOT / "hosts" / "agy", target_is_directory=True)
        except OSError:
            pass  # no symlink privilege (Windows): the plain install path is still covered
        self.quiet(self.installer.agy_install)
        self.assertFalse(plugin.is_symlink())
        hooks = json.loads((plugin / "hooks.json").read_text(encoding="utf-8"))
        handler = hooks["effort-router"]["PreToolUse"][0]
        self.assertEqual(handler["matcher"], "invoke_subagent")
        for rel in ("plugin.json", "rules/AGENTS.md", "skills/effort-routing/SKILL.md"):
            self.assertTrue((plugin / rel).is_file(), rel)
        self.assertEqual(self.quiet(self.installer.agy_install), "")

    def test_agy_launchers_use_absolute_interpreter(self):
        unix = install.agy_plugin_files(python="/opt/py/bin/python3", windows=False)
        self.assertIn('PY="/opt/py/bin/python3"', unix["hook.sh"])
        self.assertIn("sh ./hook.sh", unix["hooks.json"])
        win = install.agy_plugin_files(python=r"C:\Program Files\Python\python.exe", windows=True)
        self.assertTrue(win["hook.cmd"].startswith(r'@"C:\Program Files\Python\python.exe" "'))
        self.assertIn('"command": "hook.cmd"', win["hooks.json"])

    def test_reset_defaults_uses_backups(self):
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{\n  "effortLevel": "xhigh"\n}\n', encoding="utf-8")
        self.quiet(self.installer.reset_effort_defaults, ["claude"])
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), {})
        backups = list(self.installer.backup_dir.rglob("settings.json"))
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()
