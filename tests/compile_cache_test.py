import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import compile_cache
from lib.compile_cache import (CompileDirectoryLock, can_reuse_compile, compile_fingerprint, discover_filelist_inputs,
                               invalidate_compile_fingerprint, normalize_compile_script_paths,
                               validate_compile_fingerprint, write_compile_fingerprint)


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
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)

        source.write_text("module top; logic changed; endmodule\n", encoding="utf-8")
        source_changed = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)
        mode_changed = compile_fingerprint(project, "vcs -debug_access -f compile.f", compile_args, inventory, project)

        self.assertNotEqual(initial, source_changed)
        self.assertEqual(initial["compile_inputs_manifest_sha256"], source_changed["compile_inputs_manifest_sha256"])
        self.assertNotEqual(source_changed, mode_changed)

    @unittest.skipUnless(os.name == "posix", "fcntl locks require POSIX")
    def test_compile_directory_lock_serializes_independent_processes(self):
        lock_path = Path(tempfile.mkdtemp()) / "vcomp.compile.lock"
        first = CompileDirectoryLock(lock_path)
        probe = ("import fcntl, sys\n"
                 "with open(sys.argv[1], 'a+', encoding='utf-8') as filep:\n"
                 "    try:\n"
                 "        fcntl.flock(filep, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                 "    except BlockingIOError:\n"
                 "        sys.exit(1)\n")

        self.assertTrue(first.acquire(blocking=False))
        self.assertEqual(1, subprocess.run([sys.executable, "-c", probe, str(lock_path)], check=False).returncode)
        first.release()
        self.assertEqual(0, subprocess.run([sys.executable, "-c", probe, str(lock_path)], check=False).returncode)

    def test_fingerprint_ignores_unrelated_tracked_changes(self):
        project, _, compile_args = self._project()
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)

        (project / "README.md").write_text("documentation only\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-qm", "docs"], cwd=project, check=True)

        self.assertEqual(initial, compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project))

    def test_fingerprint_ignores_untracked_runtime_artifacts(self):
        project, _, compile_args = self._project()
        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args)

        (project / ".last_sim").write_text("sim/run\n", encoding="utf-8")
        (project / "simmer.log").write_text("runtime log\n", encoding="utf-8")

        self.assertEqual(initial, compile_fingerprint(project, "vcs -f compile.f", compile_args))

    def test_manifest_rejects_incompatible_reuse(self):
        project, _, compile_args = self._project()
        job_dir = project / "vcomp"
        job_dir.mkdir()
        fingerprint = compile_fingerprint(project, "vcs -f compile.f", compile_args)
        write_compile_fingerprint(job_dir, fingerprint)

        validate_compile_fingerprint(job_dir, fingerprint)
        with self.assertRaises(RuntimeError):
            validate_compile_fingerprint(job_dir, dict(fingerprint, compile_script="changed"))

    def test_fingerprint_normalizes_host_specific_runfiles_root(self):
        project, _, compile_args = self._project()
        first_root = project / "host-a" / "bazel-bin" / "tb.runfiles" / "__main__"
        second_root = project / "host-b" / "bazel-bin" / "tb.runfiles" / "__main__"
        first_script = "cd {}\nvcs -file {}/tb_compile_args.f\n".format(first_root, first_root)
        second_script = "cd {}\nvcs -file {}/tb_compile_args.f\n".format(second_root, second_root)

        first = normalize_compile_script_paths(first_script, {"BAZEL_RUNFILES_MAIN": first_root})
        second = normalize_compile_script_paths(second_script, {"BAZEL_RUNFILES_MAIN": second_root})

        self.assertEqual(first, second)
        self.assertEqual(
            compile_fingerprint(project, first, compile_args),
            compile_fingerprint(project, second, compile_args),
        )

    def test_fingerprint_mismatch_reports_changed_fields(self):
        project, _, compile_args = self._project()
        job_dir = project / "vcomp"
        job_dir.mkdir()
        fingerprint = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            environment={"PATH": "/tools/vcs/bin"},
        )
        write_compile_fingerprint(job_dir, fingerprint)
        changed = compile_fingerprint(
            project,
            "vcs -debug_access -f compile.f",
            compile_args,
            environment={"PATH": "/different/tools/vcs/bin"},
        )

        with self.assertRaisesRegex(RuntimeError, r"compile_script_sha256, environment\.PATH"):
            validate_compile_fingerprint(job_dir, changed)

    def test_automatic_reuse_turns_validation_failure_into_cache_miss(self):
        project, _, compile_args = self._project()
        job_dir = project / "vcomp"
        job_dir.mkdir()
        fingerprint = compile_fingerprint(project, "vcs -f compile.f", compile_args)
        write_compile_fingerprint(job_dir, fingerprint)

        self.assertEqual((True, None), can_reuse_compile(job_dir, fingerprint, lambda: None))
        hit, reason = can_reuse_compile(job_dir, fingerprint, lambda: (_ for _ in ()).throw(OSError("no simv")))
        self.assertFalse(hit)
        self.assertIn("no simv", reason)

        invalidate_compile_fingerprint(job_dir)
        hit, reason = can_reuse_compile(job_dir, fingerprint, lambda: None)
        self.assertFalse(hit)
        self.assertIn("requires", reason)

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

    def test_precomputed_compile_input_digest_matches_direct_hash(self):
        project, _, compile_args = self._project()
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        direct = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)
        digest = project / "compile_inputs.sha256"
        digest.write_text(direct["compile_inputs_sha256"] + "\n", encoding="ascii")

        precomputed = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            inventory,
            project,
            compile_inputs_digest_path=digest,
        )

        self.assertEqual(direct, precomputed)

    def test_precomputed_compile_input_digest_rejects_malformed_content(self):
        project, _, compile_args = self._project()
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        digest = project / "compile_inputs.sha256"
        digest.write_text("not-a-digest\n", encoding="ascii")

        with self.assertRaisesRegex(RuntimeError, "Malformed Bazel compile input digest"):
            compile_fingerprint(
                project,
                "vcs -f compile.f",
                compile_args,
                inventory,
                project,
                compile_inputs_digest_path=digest,
            )

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

        equivalent_config = Path(tempfile.mkdtemp()) / "coverage_hier.cfg"
        equivalent_config.write_text("+tree dut\n", encoding="utf-8")
        equivalent = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[equivalent_config],
            environment={"VCS_HOME": "/tools/vcs/Y-2026.03"},
        )
        self.assertEqual(config_changed["extra_inputs_content_sha256"], equivalent["extra_inputs_content_sha256"])

    def test_filelist_input_discovery_tracks_nested_sources_and_include_directories(self):
        runfiles = Path(tempfile.mkdtemp())
        external = Path(tempfile.mkdtemp())
        source = external / "external.sv"
        source.write_text("module external; endmodule\n", encoding="utf-8")
        include_dir = external / "include"
        include_dir.mkdir()
        header = include_dir / "external.svh"
        header.write_text("`define EXTERNAL 1\n", encoding="utf-8")
        nested = runfiles / "nested.f"
        nested.write_text("{}\n+incdir+{}\n".format(source, include_dir), encoding="utf-8")
        root = external / "compile.f"
        root.write_text("-f nested.f\n", encoding="utf-8")

        inputs = discover_filelist_inputs(root, runfiles)

        self.assertEqual(sorted(map(str, (root, nested, source, header))), inputs)

        with mock.patch("lib.compile_cache._file_bytes", wraps=compile_cache._file_bytes) as read_file:
            compile_fingerprint(
                external,
                "vcs -f {}".format(root),
                root,
                extra_input_paths=inputs,
            )

        read_paths = [os.path.abspath(os.fspath(call.args[0])) for call in read_file.call_args_list]
        self.assertEqual(2, read_paths.count(str(root))) # Compile args plus one external-input read.
        for path in (nested, source, header):
            self.assertEqual(1, read_paths.count(str(path)))


if __name__ == "__main__":
    unittest.main()
