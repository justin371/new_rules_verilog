import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.compile_cache import compile_fingerprint, validate_compile_fingerprint, write_compile_fingerprint


class CompileCacheTest(unittest.TestCase):

    def _project(self):
        path = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
        source = path / "top.sv"
        source.write_text("module top; endmodule\n", encoding="utf-8")
        subprocess.run(["git", "add", "top.sv"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
        compile_args = path / "compile.f"
        compile_args.write_text("top.sv\n", encoding="utf-8")
        return path, source, compile_args

    def test_fingerprint_changes_with_source_or_compile_mode(self):
        project, source, compile_args = self._project()
        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args)

        source.write_text("module top; logic changed; endmodule\n", encoding="utf-8")
        source_changed = compile_fingerprint(project, "vcs -f compile.f", compile_args)
        mode_changed = compile_fingerprint(project, "vcs -debug_access -f compile.f", compile_args)

        self.assertNotEqual(initial, source_changed)
        self.assertNotEqual(source_changed, mode_changed)

    def test_manifest_rejects_incompatible_reuse(self):
        project, _, compile_args = self._project()
        job_dir = project / "vcomp"
        job_dir.mkdir()
        fingerprint = compile_fingerprint(project, "vcs -f compile.f", compile_args)
        write_compile_fingerprint(job_dir, fingerprint)

        validate_compile_fingerprint(job_dir, fingerprint)
        with self.assertRaises(RuntimeError):
            validate_compile_fingerprint(job_dir, dict(fingerprint, compile_script="changed"))


if __name__ == "__main__":
    unittest.main()
