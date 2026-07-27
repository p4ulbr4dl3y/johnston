import io
import unittest
from contextlib import redirect_stdout

from app import get_version, print_mcp, print_models, print_rules, print_skills


class TestCLI(unittest.TestCase):
    def test_get_version(self):
        ver = get_version()
        self.assertIsInstance(ver, str)
        self.assertTrue(len(ver) > 0)

    def test_print_models(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_models()
        output = f.getvalue()
        self.assertIn("Available Johnston Providers & Models:", output)

    def test_print_skills(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_skills()
        output = f.getvalue()
        self.assertIn("Available Johnston Skills:", output)

    def test_print_mcp(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_mcp()
        output = f.getvalue()
        self.assertIn("Configured MCP Servers:", output)

    def test_print_rules(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_rules()
        output = f.getvalue()
        self.assertIn("Active Rules & Project Instructions:", output)


if __name__ == "__main__":
    unittest.main()
