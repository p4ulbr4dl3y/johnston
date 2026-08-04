import os
import tempfile
import unittest

from core.mode_manager import ModeManager


class TestModeManager(unittest.TestCase):
    def test_builtin_modes(self):
        mm = ModeManager.get_instance()
        modes = mm.load_modes(include_global=False)
        self.assertIn("action", modes)
        self.assertIn("explore", modes)
        self.assertFalse(modes["action"].read_only)
        self.assertTrue(modes["explore"].read_only)

    def test_custom_md_mode_with_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            modes_dir = os.path.join(tmpdir, ".johnston", "modes")
            os.makedirs(modes_dir, exist_ok=True)
            md_path = os.path.join(modes_dir, "architect.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write('''---
name: Architect
description: High-level design mode
read_only: true
disallowed_tools: [create, edit]
---
Architect prompt content''')

            mm = ModeManager()
            modes = mm.load_modes(project_dir=tmpdir, include_global=False)
            self.assertIn("architect", modes)
            arch = modes["architect"]
            self.assertEqual(arch.name, "Architect")
            self.assertTrue(arch.read_only)
            self.assertEqual(arch.prompt, "Architect prompt content")
            self.assertIn("create", arch.disallowed_tools)

    def test_custom_md_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            modes_dir = os.path.join(tmpdir, ".johnston", "modes")
            os.makedirs(modes_dir, exist_ok=True)
            md_path = os.path.join(modes_dir, "reviewer.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write('''---
name: Reviewer
description: Code review mode
read_only: true
disallowed_tools: [create, edit]
---
You are a Code Reviewer in Johnston...''')

            mm = ModeManager()
            modes = mm.load_modes(project_dir=tmpdir, include_global=False)
            self.assertIn("reviewer", modes)
            rev = modes["reviewer"]
            self.assertEqual(rev.name, "Reviewer")
            self.assertTrue(rev.read_only)
            self.assertIn("You are a Code Reviewer", rev.prompt)

    def test_deduplicate_when_global_and_project_paths_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            modes_dir = os.path.join(tmpdir, "modes")
            os.makedirs(modes_dir, exist_ok=True)
            md_path = os.path.join(modes_dir, "custom.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write('''---
name: Custom
---
Custom prompt''')

            mm = ModeManager()
            with patch("core.mode_manager.CONFIG_DIR", tmpdir):
                proj_modes_dir = os.path.join(tmpdir, ".johnston", "modes")
                os.makedirs(os.path.dirname(proj_modes_dir), exist_ok=True)
                os.symlink(modes_dir, proj_modes_dir)

                modes = mm.load_modes(project_dir=tmpdir, include_global=True)
                self.assertIn("custom", modes)
                self.assertEqual(modes["custom"].source, "global")


if __name__ == "__main__":
    unittest.main()
