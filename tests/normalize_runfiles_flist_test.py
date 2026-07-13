from pathlib import Path
import tempfile
import unittest

from bin.normalize_runfiles_flist import find_runfiles_root, normalize_flist


class NormalizeRunfilesFlistTest(unittest.TestCase):

    def test_finds_runfiles_root_before_resolving_symlink(self):
        temp_dir = Path(tempfile.mkdtemp())
        actual_root = temp_dir / "actual_runfiles"
        flist_dir = actual_root / "external" / "vendor"
        flist_dir.mkdir(parents=True)
        (actual_root / "external" / "include").mkdir()
        flist = flist_dir / "sources.f"
        flist.write_text("../include/example.sv\n", encoding="utf-8")

        runfiles_link = temp_dir / "bazel_runfiles_main"
        runfiles_link.symlink_to(actual_root, target_is_directory=True)
        linked_flist = runfiles_link / "external" / "vendor" / "sources.f"

        self.assertEqual(actual_root.resolve(), find_runfiles_root(linked_flist))
        self.assertTrue(normalize_flist(linked_flist))
        self.assertEqual("external/include/example.sv\n", flist.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
