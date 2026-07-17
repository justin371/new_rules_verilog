import os
from pathlib import Path
import re
import unittest


def _repo_root():
    test_srcdir = os.environ.get("TEST_SRCDIR")
    if test_srcdir:
        return Path(test_srcdir) / os.environ.get("TEST_WORKSPACE", "rules_verilog")
    return Path(__file__).resolve().parents[1]


REPO_ROOT = _repo_root()


class DocsTest(unittest.TestCase):

    def test_public_rules_are_listed_in_api_docs(self):
        public_defs = (REPO_ROOT / "verilog" / "defs.bzl").read_text(encoding="utf-8")
        api_docs = (REPO_ROOT / "docs" / "defs.md").read_text(encoding="utf-8")
        public_rules = re.findall(r"^(verilog_[a-z0-9_]+) = _", public_defs, flags=re.MULTILINE)

        self.assertTrue(public_rules)
        for rule_name in public_rules:
            self.assertIn('<a id="{}"></a>'.format(rule_name), api_docs)

    def test_local_markdown_links_resolve(self):
        link_pattern = re.compile(r"\[[^\]]+\]\((?![a-z]+:|#)([^)#]+)(?:#[^)]+)?\)")
        for markdown in [REPO_ROOT / "README.md"] + sorted((REPO_ROOT / "docs").glob("*.md")):
            contents = markdown.read_text(encoding="utf-8")
            for target in link_pattern.findall(contents):
                with self.subTest(markdown=markdown.name, target=target):
                    self.assertTrue((markdown.parent / target).resolve().exists())

    def test_setup_docs_do_not_reference_retired_repository(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertNotIn("Lightelligence/rules_verilog", readme)
        self.assertNotIn("LM_LICENESE_FILE", readme)


if __name__ == "__main__":
    unittest.main()
