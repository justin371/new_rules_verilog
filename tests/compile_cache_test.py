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

    def test_fingerprint_tracks_bazel_runfile_content(self):
        project, _, compile_args = self._project()
        runfiles = Path(tempfile.mkdtemp())
        external_source = runfiles / "external" / "generated.sv"
        external_source.parent.mkdir()
        external_source.write_text("module generated; endmodule\n", encoding="utf-8")
        inventory = runfiles / "compile_inputs.txt"
        inventory.write_text("source\texternal/generated.sv\n", encoding="utf-8")

        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, runfiles)
        external_source.write_text("module generated; logic changed; endmodule\n", encoding="utf-8")
        changed = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, runfiles)

        self.assertNotEqual(initial, changed)

    def test_fingerprint_rejects_missing_inventory_input(self):
        project, _, compile_args = self._project()
        runfiles = Path(tempfile.mkdtemp())
        inventory = runfiles / "compile_inputs.txt"
        inventory.write_text("source\texternal/missing.sv\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "missing file"):
            compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, runfiles)

    def test_fingerprint_tracks_external_config_content_and_tool_environment(self):
        project, _, compile_args = self._project()
        config = project.parent / "coverage_hier.cfg"
        config.write_text("+tree top\n", encoding="utf-8")
        initial = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[config],
            environment={"VCS_HOME": "/tools/vcs/Y-2026.03"},
        )

        config.write_text("+tree dut\n", encoding="utf-8")
        config_changed = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[config],
            environment={"VCS_HOME": "/tools/vcs/Y-2026.03"},
        )
        environment_changed = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[config],
            environment={"VCS_HOME": "/tools/vcs/Z-2027.03"},
        )

        self.assertNotEqual(initial, config_changed)
        self.assertNotEqual(config_changed, environment_changed)


if __name__ == "__main__":
    unittest.main()
