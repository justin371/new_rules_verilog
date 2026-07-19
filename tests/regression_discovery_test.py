import os
import json
import multiprocessing
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lib.regression import RegressionConfig


class _Log:

    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def summary(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def critical(self, message, *args):
        if args:
            message = message % args
        raise AssertionError(message)


class _Timer:

    def __init__(self, _log):
        pass

    def reset(self):
        pass

    def stop_and_print(self):
        pass


def _cache_config_for_process(project_dir):
    config = RegressionConfig.__new__(RegressionConfig)
    config.proj_dir = project_dir
    config.log = _Log()
    return config


def _write_partial_cache_generation(project_dir, ready, release):
    config = _cache_config_for_process(project_dir)
    payload = {"generation": "new"}
    with config._discovery_cache_lock(exclusive=True):
        config.dict_to_json(payload, "all_vcomp.json")
        ready.set()
        release.wait(5.0)
        for filename in ("tests_to_tags.json", "tests_to_simulator.json", "discovery_manifest.json"):
            config.dict_to_json(payload, filename)


def _read_cache_generation(project_dir, result_queue):
    config = _cache_config_for_process(project_dir)
    generation = config._load_discovery_cache_generation()
    result_queue.put([payload["generation"] for payload in generation])


class RegressionDiscoveryTest(unittest.TestCase):

    def _options(self, proj_dir):
        return SimpleNamespace(
            proj_dir=str(proj_dir),
            tests=[SimpleNamespace(btiglob="soc_tb:dma_single_transfer", tag=set(), ntag=set())],
            no_bazel=False,
            no_compile=False,
            allow_no_run=False,
            waves=None,
            nt=False,
            category_cfg=None,
            global_tag=set(),
            global_ntag=set(),
            discovery_only=False,
            report=None,
        )

    def _config(self, proj_dir):
        config = RegressionConfig.__new__(RegressionConfig)
        config.options = self._options(proj_dir)
        config.log = _Log()
        config.proj_dir = str(proj_dir)
        config.max_bench_name_length = 20
        config.max_test_name_length = 20
        return config

    def test_cache_manifest_tracks_content_changes_and_deleted_files(self):
        proj_dir = Path(tempfile.mkdtemp())
        build_file = proj_dir / "benches" / "soc_tb" / "BUILD"
        build_file.parent.mkdir(parents=True)
        build_file.write_text("filegroup(name='x')\n", encoding="utf-8")
        bazel_version = proj_dir / ".bazelversion"
        bazel_version.write_text("7.7.1\n", encoding="utf-8")
        bazel_ignore = proj_dir / ".bazelignore"
        bazel_ignore.write_text("bazel-out\n", encoding="utf-8")

        config = self._config(proj_dir)
        cache_dir = proj_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            path = cache_dir / filename
            path.write_text("{}", encoding="utf-8")
        config._write_discovery_manifest()

        self.assertTrue(config._discovery_cache_is_fresh())

        original_mtime = bazel_version.stat().st_mtime
        bazel_version.write_text("8.0.0\n", encoding="utf-8")
        os.utime(bazel_version, (original_mtime, original_mtime))
        self.assertFalse(config._discovery_cache_is_fresh())

        config._write_discovery_manifest()
        build_file.unlink()
        self.assertFalse(config._discovery_cache_is_fresh())

        config._write_discovery_manifest()
        original_mtime = bazel_ignore.stat().st_mtime
        bazel_ignore.write_text("bazel-out\nbazel-testlogs\n", encoding="utf-8")
        os.utime(bazel_ignore, (original_mtime, original_mtime))
        self.assertFalse(config._discovery_cache_is_fresh())

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_cache_reader_cannot_observe_a_partial_generation(self):
        project_dir = tempfile.mkdtemp()
        config = self._config(Path(project_dir))
        old_payload = {"generation": "old"}
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json", "discovery_manifest.json"):
            config.dict_to_json(old_payload, filename)

        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        result_queue = context.Queue()
        writer = context.Process(target=_write_partial_cache_generation, args=(project_dir, ready, release))
        reader = context.Process(target=_read_cache_generation, args=(project_dir, result_queue))

        writer.start()
        self.assertTrue(ready.wait(2.0))
        reader.start()
        time.sleep(0.1)
        self.assertTrue(reader.is_alive(), "reader did not wait for the generation lock")
        release.set()
        writer.join(5.0)
        reader.join(5.0)

        self.assertEqual(0, writer.exitcode)
        self.assertEqual(0, reader.exitcode)
        self.assertEqual(["new"] * 4, result_queue.get(timeout=1.0))

    @mock.patch("lib.regression.os.walk", side_effect=AssertionError("walk should not run"))
    @mock.patch("lib.regression.subprocess.run")
    def test_cache_uses_git_file_index_when_available(self, run, _walk):
        proj_dir = Path(tempfile.mkdtemp())
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(
                returncode=0,
                stdout="pkg/BUILD\npkg/file.py\nrules/tool.bzl\n.bazelversion\nMODULE.bazel.lock\n",
            ),
            SimpleNamespace(returncode=0, stdout=""),
        ]
        config = self._config(proj_dir)

        dependencies = list(config._iter_discovery_dependency_paths())
        for expected in (
                proj_dir / "pkg/BUILD",
                proj_dir / "rules/tool.bzl",
                proj_dir / ".bazelversion",
                proj_dir / "MODULE.bazel.lock",
                proj_dir / ".bazelrc",
        ):
            self.assertIn(str(expected), dependencies)
        self.assertEqual(3, run.call_count)

    def test_cache_manifest_tracks_imported_bazelrc(self):
        proj_dir = Path(tempfile.mkdtemp())
        imported_rc = proj_dir / "tools" / "settings.rc"
        imported_rc.parent.mkdir()
        imported_rc.write_text("build --define=MODE=first\n", encoding="utf-8")
        (proj_dir / ".bazelrc").write_text("import %workspace%/tools/settings.rc\n", encoding="utf-8")
        config = self._config(proj_dir)
        cache_dir = proj_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            (cache_dir / filename).write_text("{}", encoding="utf-8")

        config._write_discovery_manifest()
        self.assertTrue(config._discovery_cache_is_fresh())
        imported_rc.write_text("build --define=MODE=second\n", encoding="utf-8")

        self.assertFalse(config._discovery_cache_is_fresh())

    def test_cache_manifest_tracks_ignored_bazel_metadata(self):
        proj_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=proj_dir, check=True)
        (proj_dir / ".gitignore").write_text("generated/\n", encoding="utf-8")
        ignored_build = proj_dir / "generated" / "BUILD"
        ignored_build.parent.mkdir()
        ignored_build.write_text("filegroup(name='first')\n", encoding="utf-8")
        config = self._config(proj_dir)
        cache_dir = proj_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            (cache_dir / filename).write_text("{}", encoding="utf-8")

        config._write_discovery_manifest()
        self.assertTrue(config._discovery_cache_is_fresh())
        ignored_build.write_text("filegroup(name='second')\n", encoding="utf-8")

        self.assertFalse(config._discovery_cache_is_fresh())

    def test_cache_manifest_tracks_local_repository_bazel_metadata_only(self):
        project_dir = Path(tempfile.mkdtemp())
        repository_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
        (project_dir / "WORKSPACE").write_text(
            "local_repository(name = 'mutable_ip', path = {!r})\n".format(str(repository_dir)),
            encoding="utf-8",
        )
        build_file = repository_dir / "rtl" / "BUILD"
        build_file.parent.mkdir()
        build_file.write_text("filegroup(name = 'first')\n", encoding="utf-8")
        source_file = repository_dir / "rtl" / "large_source.sv"
        source_file.write_text("module first; endmodule\n", encoding="utf-8")
        config = self._config(project_dir)
        cache_dir = project_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            (cache_dir / filename).write_text("{}", encoding="utf-8")

        config._write_discovery_manifest()
        manifest = json.loads((cache_dir / "discovery_manifest.json").read_text(encoding="utf-8"))
        manifest_paths = {entry["path"] for entry in manifest["files"]}
        canonical_project_dir = os.path.realpath(project_dir)
        build_relative_path = os.path.relpath(os.path.realpath(build_file), canonical_project_dir).replace(os.sep, "/")
        source_relative_path = os.path.relpath(os.path.realpath(source_file),
                                               canonical_project_dir).replace(os.sep, "/")
        self.assertIn(build_relative_path, manifest_paths)
        self.assertNotIn(source_relative_path, manifest_paths)
        self.assertTrue(config._discovery_cache_is_fresh())

        build_file.write_text("filegroup(name = 'second')\n", encoding="utf-8")

        self.assertFalse(config._discovery_cache_is_fresh())

    def test_cache_manifest_tracks_wrapped_new_local_repository_declared_in_bzl(self):
        project_dir = Path(tempfile.mkdtemp())
        repository_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
        (project_dir / "WORKSPACE").write_text("load('//tools:repos.bzl', 'declare_repositories')\n", encoding="utf-8")
        repos_bzl = project_dir / "tools" / "repos.bzl"
        repos_bzl.parent.mkdir()
        repos_bzl.write_text(
            "def declare_repositories():\n"
            "    maybe(native.new_local_repository, name = 'mutable_ip', path = {!r}, build_file = '//:BUILD')\n".
            format(str(repository_dir)),
            encoding="utf-8",
        )
        repository_bzl = repository_dir / "defs.bzl"
        repository_bzl.write_text("VALUE = 'first'\n", encoding="utf-8")
        config = self._config(project_dir)
        cache_dir = project_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            (cache_dir / filename).write_text("{}", encoding="utf-8")

        config._write_discovery_manifest()
        self.assertTrue(config._discovery_cache_is_fresh())
        repository_bzl.write_text("VALUE = 'second'\n", encoding="utf-8")

        self.assertFalse(config._discovery_cache_is_fresh())

    def test_local_repository_scan_follows_safe_metadata_symlink(self):
        project_dir = Path(tempfile.mkdtemp())
        repository_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
        (project_dir / "WORKSPACE").write_text(
            "local_repository(name = 'mutable_ip', path = {!r})\n".format(str(repository_dir)),
            encoding="utf-8",
        )
        real_build = Path(tempfile.mkdtemp()) / "real.BUILD"
        real_build.write_text("filegroup(name = 'first')\n", encoding="utf-8")
        linked_build = repository_dir / "BUILD"
        try:
            linked_build.symlink_to(real_build)
        except OSError as exc:
            self.skipTest("file symlinks are unavailable: {}".format(exc))
        config = self._config(project_dir)
        cache_dir = project_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            (cache_dir / filename).write_text("{}", encoding="utf-8")

        metadata_paths = config._iter_local_repository_metadata(repository_dir)
        config._write_discovery_manifest()
        real_build.write_text("filegroup(name = 'second')\n", encoding="utf-8")

        self.assertIn(os.path.realpath(linked_build), [os.path.realpath(path) for path in metadata_paths])
        self.assertFalse(config._discovery_cache_is_fresh())

    def test_local_repository_scan_limit_disables_cache_reuse_without_warning(self):
        project_dir = Path(tempfile.mkdtemp())
        repository_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
        (project_dir / "WORKSPACE").write_text(
            "local_repository(name = 'mutable_ip', path = {!r})\n".format(str(repository_dir)),
            encoding="utf-8",
        )
        (repository_dir / "BUILD").write_text("filegroup(name = 'first')\n", encoding="utf-8")
        (repository_dir / "source.sv").write_text("module first; endmodule\n", encoding="utf-8")
        config = self._config(project_dir)
        config.log = mock.Mock(wraps=config.log)
        cache_dir = project_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            (cache_dir / filename).write_text("{}", encoding="utf-8")

        with mock.patch("lib.regression.DISCOVERY_LOCAL_REPOSITORY_MAX_ENTRIES", 1):
            config._write_discovery_manifest()
            manifest = json.loads((cache_dir / "discovery_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["cacheable"])
            self.assertFalse(config._discovery_cache_is_fresh())

        config.log.warning.assert_not_called()

    def test_oversized_local_repository_declaration_disables_cache_reuse(self):
        project_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
        (project_dir / "WORKSPACE").write_text(
            "local_repository(name = 'mutable_ip', path = '/tmp/ip')\n",
            encoding="utf-8",
        )
        config = self._config(project_dir)

        with mock.patch("lib.regression.DISCOVERY_LOCAL_REPOSITORY_MAX_DECLARATION_BYTES", 8):
            manifest = config._discovery_dependency_manifest()

        self.assertFalse(manifest["cacheable"])

    def test_nonliteral_direct_local_repository_path_disables_cache_reuse(self):
        project_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
        (project_dir / "WORKSPACE").write_text(
            "mutable_ip_path = '/tmp/ip'\n"
            "local_repository(name = 'mutable_ip', path = mutable_ip_path)\n",
            encoding="utf-8",
        )
        config = self._config(project_dir)

        manifest = config._discovery_dependency_manifest()

        self.assertFalse(manifest["cacheable"])

    def test_no_bazel_rejects_stale_cache(self):
        config = self._config(Path(tempfile.mkdtemp()))
        config.options.no_bazel = True
        config._discovery_cache_is_fresh = lambda: False

        self.assertFalse(config._should_use_cached_discovery())

    def test_requested_bench_query_is_scoped(self):
        config = self._config(Path(tempfile.mkdtemp()))

        query = config._build_vcomp_discovery_query()

        self.assertIn('filter(":soc_tb$", kind(dv_tb, //benches/...))', query)

    def test_cache_manifest_tracks_requested_bench_query(self):
        config = self._config(Path(tempfile.mkdtemp()))
        initial = config._discovery_dependency_manifest()

        config.options.tests[0].btiglob = "other_tb:*"

        self.assertNotEqual(initial, config._discovery_dependency_manifest())

    def test_cache_manifest_tracks_allow_no_run(self):
        config = self._config(Path(tempfile.mkdtemp()))
        initial = config._discovery_dependency_manifest()

        config.options.allow_no_run = True

        self.assertNotEqual(initial, config._discovery_dependency_manifest())

    def test_test_cfg_query_uses_the_public_macro_identity(self):
        config = self._config(Path(tempfile.mkdtemp()))

        query = config._build_test_cfg_query("//benches/soc_tb:soc_tb")

        self.assertIn("attr(generator_function, verilog_dv_test_cfg,", query)
        self.assertNotIn("dv_test_cfg_rule", query)
        self.assertNotIn("base_cfg", query)

    def test_discovery_batches_cquery_and_build(self):
        proj_dir = Path(tempfile.mkdtemp())
        config = self._config(proj_dir)
        config.tests_to_tags = {}
        config.tests_to_simulator = {}

        commands = []

        def fake_run_command(cmd):
            commands.append(cmd)
            if cmd[:2] == ["bazel", "query"]:
                return 0, "//benches/soc_tb:soc_tb\n", ""
            if cmd[:2] == ["bazel", "cquery"]:
                return 0, "//benches/soc_tb/tests:dma_single_transfer (abc1234)\n", ""
            if cmd[:2] == ["bazel", "build"]:
                return 0, "", ("verilog_dv_test_cfg_info(@//benches/soc_tb/tests:dma_single_transfer, "
                               "@//benches/soc_tb:soc_tb, ['smoke'], VCS)\n")
            raise AssertionError("Unexpected command: {!r}".format(cmd))

        config._run_command = fake_run_command
        config.dict_to_json = lambda *_args, **_kwargs: None

        from lib import regression as regression_module

        original_timer = regression_module.rv_utils.DatetimePrinter
        regression_module.rv_utils.DatetimePrinter = _Timer
        try:
            config.test_discovery_all()
        finally:
            regression_module.rv_utils.DatetimePrinter = original_timer

        self.assertEqual(3, len(commands))
        self.assertEqual(["bazel", "query"], commands[0][:2])
        self.assertEqual(["bazel", "cquery"], commands[1][:2])
        self.assertEqual(["bazel", "build"], commands[2][:2])
        self.assertEqual(
            {"//benches/soc_tb/tests:dma_single_transfer": ["smoke"]},
            config.tests_to_tags,
        )
        self.assertEqual(
            {"//benches/soc_tb/tests:dma_single_transfer": "VCS"},
            config.tests_to_simulator,
        )
        self.assertEqual(
            {"//benches/soc_tb:soc_tb": {
                "//benches/soc_tb/tests:dma_single_transfer": 0
            }},
            config.all_vcomp,
        )

    def test_discovery_argument_chunks_stay_under_configured_budget(self):
        self.assertEqual(
            [["aaaa"], ["bbbb"], ["cc"]],
            RegressionConfig._chunk_arguments(["aaaa", "bbbb", "cc"], max_chars=7),
        )

    def test_discovery_retries_when_source_manifest_changes(self):
        config = self._config(Path(tempfile.mkdtemp()))
        first = {"files": ["first"]}
        second = {"files": ["second"]}
        config._discovery_dependency_manifest = mock.Mock(side_effect=[first, second, second, second])
        config._discover_test_metadata = mock.Mock()
        config._publish_discovery_cache = mock.Mock()

        config.test_discovery_all()

        self.assertEqual(2, config._discover_test_metadata.call_count)
        config._publish_discovery_cache.assert_called_once_with(second)

    @mock.patch("lib.regression.subprocess.run")
    def test_profiled_bazel_command_records_repositories_and_cleans_trace(self, run):
        proj_dir = Path(tempfile.mkdtemp())
        config = self._config(proj_dir)
        config.options.simmer_profile = True
        config.regression_dir = str(proj_dir)
        config.profile_events = []
        config._bazel_profile_index = 0

        def create_profile(command, **_kwargs):
            profile_arg = next(argument for argument in command if argument.startswith("--profile="))
            profile_path = profile_arg.split("=", 1)[1]
            Path(profile_path).write_text(json.dumps({
                "traceEvents": [{
                    "ph": "X",
                    "cat": "repository",
                    "name": "Repository rule @third_party_ip",
                    "dur": 1_250_000,
                }],
            }),
                                          encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        run.side_effect = create_profile

        self.assertEqual((0, "ok", ""), config._run_command(["bazel", "query", "//..."]))

        command = run.call_args.args[0]
        self.assertEqual("query", command[1])
        self.assertTrue(command[2].startswith("--profile="))
        self.assertFalse(Path(command[2].split("=", 1)[1]).exists())
        self.assertTrue(any(name == "bazel_query" for _, name, _ in config.profile_events))
        self.assertIn(
            (1.25, "external_repo: third_party_ip", "query; 1 repository event(s)"),
            config.profile_events,
        )

    def test_missing_discovery_cache_fails(self):
        config = self._config(Path(tempfile.mkdtemp()))
        config.log.critical = lambda *_args, **_kwargs: None

        with self.assertRaises(FileNotFoundError):
            config.json_to_dict("all_vcomp.json")

    def test_init_creates_deferred_messages_with_cached_discovery(self):
        proj_dir = Path(tempfile.mkdtemp())
        results_dir = proj_dir / "results"
        cache_dir = proj_dir / ".simmer" / "cache"
        cache_dir.mkdir(parents=True)
        for filename, payload in {
                "all_vcomp.json": {
                    "//benches/soc_tb:soc_tb": {
                        "//benches/soc_tb/tests:dma_single_transfer": 1
                    }
                },
                "tests_to_tags.json": {
                    "//benches/soc_tb/tests:dma_single_transfer": []
                },
                "tests_to_simulator.json": {
                    "//benches/soc_tb/tests:dma_single_transfer": "VCS"
                },
        }.items():
            (cache_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
        self._config(proj_dir)._write_discovery_manifest()

        options = self._options(proj_dir)
        options.no_bazel = True

        from lib import regression as regression_module

        original_calc = regression_module.rv_utils.calc_simresults_location
        regression_module.rv_utils.calc_simresults_location = lambda _proj_dir: str(results_dir)
        with mock.patch.object(regression_module.rv_utils, "load_category_total_cases") as load_category:
            try:
                config = RegressionConfig(options, _Log())
            finally:
                regression_module.rv_utils.calc_simresults_location = original_calc

        load_category.assert_not_called()
        self.assertEqual({}, config.category_total_cases)
        self.assertEqual([], config.deferred_messages)
        self.assertEqual(0, config.current_time)


if __name__ == "__main__":
    unittest.main()
