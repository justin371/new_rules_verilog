import os
import json
import tempfile
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
        )

    def _config(self, proj_dir):
        config = RegressionConfig.__new__(RegressionConfig)
        config.options = self._options(proj_dir)
        config.log = _Log()
        config.proj_dir = str(proj_dir)
        config.max_bench_name_length = 20
        config.max_test_name_length = 20
        return config

    def test_cache_freshness_tracks_build_and_bzl_files(self):
        proj_dir = Path(tempfile.mkdtemp())
        build_file = proj_dir / "benches" / "soc_tb" / "BUILD"
        build_file.parent.mkdir(parents=True)
        build_file.write_text("filegroup(name='x')\n", encoding="utf-8")

        config = self._config(proj_dir)
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            path = proj_dir / filename
            path.write_text("{}", encoding="utf-8")
            path.touch()

        cache_time = build_file.stat().st_mtime + 10
        for filename in ("all_vcomp.json", "tests_to_tags.json", "tests_to_simulator.json"):
            path = proj_dir / filename
            path.touch()
            os.utime(path, (cache_time, cache_time))

        self.assertTrue(config._discovery_cache_is_fresh())

        newer_time = cache_time + 10
        os.utime(build_file, (newer_time, newer_time))
        self.assertFalse(config._discovery_cache_is_fresh())

    @mock.patch("lib.regression.os.walk", side_effect=AssertionError("walk should not run"))
    @mock.patch("lib.regression.subprocess.run")
    def test_cache_uses_git_file_index_when_available(self, run, _walk):
        proj_dir = Path(tempfile.mkdtemp())
        run.return_value = SimpleNamespace(returncode=0, stdout="pkg/BUILD\npkg/file.py\nrules/tool.bzl\n")
        config = self._config(proj_dir)

        self.assertEqual(
            [str(proj_dir / "pkg/BUILD"), str(proj_dir / "rules/tool.bzl")],
            list(config._iter_discovery_dependency_paths()),
        )

    def test_requested_bench_query_is_scoped(self):
        config = self._config(Path(tempfile.mkdtemp()))

        query = config._build_vcomp_discovery_query()

        self.assertIn('filter(":soc_tb$", kind(dv_tb, //benches/...))', query)

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
                return 0, "", (
                    "verilog_dv_test_cfg_info(@//benches/soc_tb/tests:dma_single_transfer, "
                    "@//benches/soc_tb:soc_tb, ['smoke'], VCS)\n"
                )
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
            {"//benches/soc_tb:soc_tb": {"//benches/soc_tb/tests:dma_single_transfer": 0}},
            config.all_vcomp,
        )

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
            }), encoding="utf-8")
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
        for filename, payload in {
            "all_vcomp.json": {"//benches/soc_tb:soc_tb": {"//benches/soc_tb/tests:dma_single_transfer": 1}},
            "tests_to_tags.json": {"//benches/soc_tb/tests:dma_single_transfer": []},
            "tests_to_simulator.json": {"//benches/soc_tb/tests:dma_single_transfer": "VCS"},
        }.items():
            (proj_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

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
