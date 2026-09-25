import json
import sys
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


if __name__ == "__main__":
    unittest.main()
