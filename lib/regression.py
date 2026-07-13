#!/usr/bin/env python

################################################################################
# standard lib imports
import ast
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import json
import time

################################################################################
# rules_verilog lib imports
from lib import bazel_profile, rv_utils

# I'd rather create a "plain" message in the logger
# that doesn't format, but more work than its worth
LOGGER_INDENT = 8
BENCHES_REL_DIR = os.environ.get('BENCHES_REL_DIR', 'benches')
DISCOVERY_CACHE_FILES = (
    "all_vcomp.json",
    "tests_to_tags.json",
    "tests_to_simulator.json",
    "discovery_manifest.json",
)
DISCOVERY_ROOT_FILES = {
    ".bazelrc",
    ".bazelversion",
    "MODULE.bazel",
    "MODULE.bazel.lock",
    "WORKSPACE",
    "WORKSPACE.bazel",
}


class RegressionConfig():
    """Configuration class for managing regression tests"""

    def __init__(self, options, log):
        self.options = options
        self.log = log

        self.tests_to_tags = {} # Mapping of tests to their tags
        self.tests_to_simulator = {} # Mapping of tests to their simulator
        self.max_bench_name_length = 20 # Max length for bench name formatting
        self.max_test_name_length = 20 # Max length for test name formatting

        self.suppress_output = False # Flag to suppress test output

        self.proj_dir = self.options.proj_dir
        self.regression_dir = rv_utils.calc_simresults_location(self.proj_dir)

        # Create regression directory if it doesn't exist
        os.makedirs(self.regression_dir, exist_ok=True)

        self.invocation_dir = os.getcwd() # Directory where regression was started
        self.profile_events = []
        self._bazel_profile_index = 0
        self.deferred_messages = [] # Messages to be printed at completion
        self.current_time = 0 # Timestamp for regression

        # Subsystem configuration (with tag associations)
        self.category_total_cases = {}
        if options.category_cfg is not None:
            self.load_category_config(options.category_cfg)

        self.use_cached_discovery = self._profile_step(
            "discovery_cache_check",
            "check discovery json freshness",
            self._should_use_cached_discovery,
        )
        if not self.use_cached_discovery:
            if self.options.no_bazel:
                self.log.critical("Discovery cache missing or stale. Please rerun without --no-bazel.")
            self._profile_step(
                "test_discovery_all",
                "bazel query/cquery/build test cfg metadata",
                self.test_discovery_all,
            )
        self._profile_step(
            "test_discovery_match",
            "filter requested bench:test globs",
            self.test_discovery_match,
        )

        # Verify tests were found
        total_tests = sum([iterations for vcomp in self.all_vcomp.values() for test, iterations in vcomp.items()])
        if total_tests == 0:
            self.log.critical("Test globbing resulted in no tests to run")

        # Determine if passing tests should be cleaned up
        self.tidy = True
        if total_tests == 1:
            self.tidy = False
        if self.options.waves is not None:
            self.tidy = False
        if self.options.nt:
            self.tidy = False
        if self.tidy:
            self.log.info(
                "tidy=%s passing tests will automatically be cleaned up. Use --nt to prevent automatic cleanup.",
                self.tidy)

    def _profile_step(self, name, detail, func):
        start = time.perf_counter()
        try:
            return func()
        finally:
            if getattr(self.options, "simmer_profile", False):
                self.profile_events.append((time.perf_counter() - start, name, detail))

    def load_category_config(self, cfg_path: str = None):
        """
        Load subsystem configuration with tag associations
        Use the specified path, or the project default when the flag has no value.
        """
        if not cfg_path:
            cfg_path = os.path.join(self.proj_dir, "category_config.json")

        self.category_total_cases = rv_utils.load_category_total_cases(cfg_path)
        self.log.info(f"Loaded subsystem config with tags: {self.category_total_cases}")

    def table_format(self, b, t, c, indent=' ' * rv_utils.LOGGER_INDENT):
        """
        Format table entries for consistent output
        :param b: Bench name
        :param t: Test name
        :param c: Count value
        :param indent: Indentation for formatting
        :return: Formatted string
        """
        return "{}{:{}s}  {:{}s}  {:{}s}".format(indent, b, self.max_bench_name_length, t, self.max_test_name_length, c,
                                                 6)

    def table_format_summary_line(self, bench, test, passed, skipped, failed, indent=' ' * rv_utils.LOGGER_INDENT):
        """
        Format summary line for test results table
        :param bench: Bench name
        :param test: Test name
        :param passed: Number of passed tests
        :param skipped: Number of skipped tests
        :param failed: Number of failed tests
        :param indent: Indentation for formatting
        :return: Formatted string
        """
        return f"{indent}{bench:{self.max_bench_name_length}s}  {test:{self.max_test_name_length}s}  {passed:{6}s}  {skipped:{6}s}  {failed:{6}s}"

    def format_test_name(self, b, t, i, sim='???'):
        """
        Format test name with simulator information
        :param b: Bench name
        :param t: Test name
        :param i: Iteration number
        :param sim: Simulator name
        :return: Formatted test name string
        """
        max_sim_len = 5 # Max length for simulator abbreviation
        sim_short = sim[:max_sim_len]
        return "{:{}s}  {:{}s}  {:-4d}  {:{}s}".format(b, self.max_bench_name_length, t, self.max_test_name_length, i,
                                                       sim_short, max_sim_len)

    def dict_to_json(self, d, j):
        """
        Save dictionary to JSON file
        :param d: Dictionary to save
        :param j: Filename to save to
        """
        path = self._cache_path(j)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary_path = "{}.{}.tmp".format(path, os.getpid())
        try:
            with open(temporary_path, "w") as f:
                json.dump(d, f, indent=4)
            os.replace(temporary_path, path)
        except Exception as e:
            self.log.critical("Failed to create '%s' file: %s", j, e)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

    def json_to_dict(self, j):
        """
        Load dictionary from JSON file
        :param j: Filename to load from
        :return: Loaded dictionary
        """
        path = self._cache_path(j)
        if not os.path.exists(path):
            self.log.critical("'%s' not found. Please compile first!", j)
            raise FileNotFoundError(path)
        try:
            with open(path, "r") as filep:
                return json.load(filep)
        except (OSError, json.JSONDecodeError) as exc:
            self.log.critical("Failed to load '%s' file: %s", j, exc)
            raise

    def _cache_path(self, filename):
        return os.path.join(self.proj_dir, ".simmer", "cache", filename)

    def _have_discovery_cache(self):
        return all(os.path.exists(self._cache_path(filename)) for filename in DISCOVERY_CACHE_FILES)

    def _discovery_dependency_manifest(self):
        files = []
        for path in sorted(set(self._iter_discovery_dependency_paths())):
            relative_path = os.path.relpath(path, self.proj_dir).replace(os.sep, "/")
            try:
                with open(path, "rb") as filep:
                    digest = hashlib.sha256(filep.read()).hexdigest()
            except OSError:
                digest = "missing"
            files.append({"path": relative_path, "sha256": digest})
        return {
            "schema_version": 1,
            "allow_no_run": bool(self.options.allow_no_run),
            "discovery_query": self._build_vcomp_discovery_query(),
            "files": files,
        }

    def _write_discovery_manifest(self):
        self.dict_to_json(self._discovery_dependency_manifest(), "discovery_manifest.json")

    def _iter_discovery_dependency_paths(self):
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=self.proj_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for relative_path in result.stdout.splitlines():
                filename = os.path.basename(relative_path)
                if filename in ("BUILD",
                                "BUILD.bazel") or filename.endswith(".bzl") or relative_path in DISCOVERY_ROOT_FILES:
                    yield os.path.join(self.proj_dir, os.path.normpath(relative_path))
            return

        for root, dirs, files in os.walk(self.proj_dir):
            dirs[:] = [
                directory for directory in dirs
                if directory not in (".git", ".simmer") and not directory.startswith("bazel-")
            ]
            for filename in files:
                relative_path = os.path.relpath(os.path.join(root, filename), self.proj_dir)
                if filename in ("BUILD",
                                "BUILD.bazel") or filename.endswith(".bzl") or relative_path in DISCOVERY_ROOT_FILES:
                    yield os.path.join(root, filename)

    def _discovery_cache_is_fresh(self):
        if not self._have_discovery_cache():
            return False
        try:
            with open(self._cache_path("discovery_manifest.json"), "r", encoding="utf-8") as filep:
                cached_manifest = json.load(filep)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        current_manifest = self._discovery_dependency_manifest()
        if cached_manifest != current_manifest:
            self.log.debug("Discovery cache dependency manifest changed")
            return False
        return True

    def _should_use_cached_discovery(self):
        if self._discovery_cache_is_fresh():
            self.log.info("Using cached test discovery")
            return True
        return False

    def _split_btglob(self, btiglob):
        try:
            btglob, iterations = btiglob.split("@")
            try:
                iterations = int(iterations)
            except ValueError:
                self.log.critical("Iterations (value after @) must be an integer: '%s'", btiglob)
        except ValueError:
            btglob = btiglob
            iterations = 1

        try:
            bglob, tglob = btglob.split(":")
        except ValueError:
            pwd = os.getcwd()
            benches_dir = os.path.join(self.proj_dir, BENCHES_REL_DIR)
            if not (benches_dir in pwd and len(benches_dir) < len(pwd)):
                self.log.critical("Not in a benches/ directory. Must provide bench:test style glob.")
            bglob = pwd[len(benches_dir) + 1:]
            tglob = btglob
        return bglob, tglob, iterations

    def _bench_glob_to_regex(self, bench_glob):
        return re.escape(bench_glob).replace(r"\*", ".*").replace(r"\?", ".")

    def _build_vcomp_discovery_query(self):
        bench_globs = sorted({self._split_btglob(ta.btiglob)[0] for ta in self.options.tests})
        if not bench_globs or bench_globs == ["*"]:
            return "kind(dv_tb, //{}/...)".format(BENCHES_REL_DIR)

        queries = [
            'filter(":{regex}$", kind(dv_tb, //{benches}/...))'.format(
                regex=self._bench_glob_to_regex(bench_glob),
                benches=BENCHES_REL_DIR,
            ) for bench_glob in bench_globs
        ]
        return " union ".join("({})".format(query) for query in queries)

    def _build_test_cfg_query(self, vcomp):
        vcomp_path, _ = vcomp.split(':')
        test_wildcard = os.path.join(vcomp_path, "tests", "...")
        generated_test_cfgs = 'attr(generator_function, verilog_dv_test_cfg, {test_wildcard} intersect allpaths({test_wildcard}, {vcomp}))'.format(
            test_wildcard=test_wildcard,
            vcomp=vcomp,
        )
        if self.options.allow_no_run:
            return 'attr(abstract, 0, {})'.format(generated_test_cfgs)
        return 'attr(no_run, 0, attr(abstract, 0, {}))'.format(generated_test_cfgs)

    def _run_command(self, cmd):
        command = list(cmd)
        profile_path = None
        profile_enabled = getattr(self.options, "simmer_profile", False) and command[:1] == ["bazel"]
        if profile_enabled:
            self._bazel_profile_index += 1
            command_name = command[1] if len(command) > 1 else "command"
            profile_path = os.path.join(
                self.regression_dir,
                "bazel_profile_{:02d}_{}.json".format(self._bazel_profile_index, command_name),
            )
            if os.path.exists(profile_path):
                os.remove(profile_path)
            command.insert(2, "--profile={}".format(profile_path))

        self.log.debug(" > %s", " ".join(command))
        start = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            duration_s = time.perf_counter() - start
            if profile_enabled:
                self.profile_events.append((duration_s, "bazel_{}".format(command_name), " ".join(cmd)))
                if profile_path and os.path.exists(profile_path):
                    try:
                        for repo_duration, repository, event_count in bazel_profile.repository_timings(profile_path):
                            detail = "{}; {} repository event(s)".format(command_name, event_count)
                            self.profile_events.append((repo_duration, "external_repo: {}".format(repository), detail))
                    except (OSError, ValueError, TypeError) as exc:
                        self.log.warning("Could not parse Bazel profile %s: %s", profile_path, exc)
                    finally:
                        os.remove(profile_path)
        return result.returncode, result.stdout, result.stderr

    def test_discovery_all(self):
        """
        Discover all available tests in the checkout
        Filters based on command line specifications
        """
        self.log.summary("Starting test discovery")
        dtp = rv_utils.DatetimePrinter(self.log)

        # Query only the benches requested by the current test globs.
        cmd = ["bazel", "query", self._build_vcomp_discovery_query()]
        dtp.reset()
        returncode, stdout, stderr = self._run_command(cmd)
        dtp.stop_and_print()
        if returncode:
            self.log.critical("bazel bench discovery failed: %s", stderr)
        self.all_vcomp = dict((label, {}) for label in stdout.splitlines() if label)

        if not self.all_vcomp:
            self.tests_to_tags = {}
            self.tests_to_simulator = {}
            return

        combined_test_query = " union ".join("({})".format(self._build_test_cfg_query(vcomp))
                                             for vcomp in sorted(self.all_vcomp))

        dtp.reset()
        returncode, stdout, stderr = self._run_command(["bazel", "cquery", combined_test_query], )
        dtp.stop_and_print()
        if returncode:
            self.log.critical("bazel test discovery failed:\n%s", stderr)

        query_results = re.sub(r"\([a-z0-9]{7,64}\) *", "", stdout.replace('\n', ' ')).split()

        text = []
        if query_results:
            dtp.reset()
            returncode, stdout, stderr = self._run_command([
                "bazel",
                "build",
                *query_results,
                "--aspects",
                "@rules_verilog//verilog/private:dv.bzl%verilog_dv_test_cfg_info_aspect",
            ])
            dtp.stop_and_print()
            if returncode:
                self.log.critical("bazel test discovery failed:\n%s", stderr)
            text = stdout.split('\n') + stderr.split('\n')

            # Parse test information from output
        ttv = [
            re.search(
                r'verilog_dv_test_cfg_info\(@(?:@)?(?P<test>[^,]+), @(?:@)?(?P<vcomp>[^,]+), (?P<tags>\[.*\]), (?P<simulator>[A-Z0-9_]+)\)',
                line,
            ) for line in text
        ]
        ttv = [match for match in ttv if match]

        matching_tests = [(mt.group('test'), mt.group('vcomp'), ast.literal_eval(mt.group('tags')),
                           mt.group('simulator')) for mt in ttv]
        self.tests_to_tags = {test_name: tags for test_name, _, tags, _ in matching_tests}
        self.tests_to_simulator = {test_name: simulator for test_name, _, _, simulator in matching_tests}
        for test_name, vcomp, _, _ in matching_tests:
            if vcomp in self.all_vcomp:
                self.all_vcomp[vcomp][test_name] = 0

        # Log discovered tests in table format
        table_output = []
        table_output.append(self.table_format("bench", "test", "count"))
        table_output.append(self.table_format("-----", "----", "-----"))
        for vcomp, tests in self.all_vcomp.items():
            bench = vcomp.split(':')[1]
            for i, (test_target, count) in enumerate(tests.items()):
                test = test_target.split(':')[1]
                if i == 0:
                    table_output.append(self.table_format(bench, test, str(count)))
                else:
                    table_output.append(self.table_format('', test, str(count)))

        self.log.debug("Tests available:\n%s", "\n".join(table_output))

        # Save test information to JSON files
        self.dict_to_json(self.all_vcomp, "all_vcomp.json")
        self.dict_to_json(self.tests_to_tags, "tests_to_tags.json")
        self.dict_to_json(self.tests_to_simulator, "tests_to_simulator.json")
        self._write_discovery_manifest()

    def test_discovery_match(self):
        """
        Match tests based on command line arguments and tags
        Filters the discovered tests to those that should be run
        """
        # Load test information from JSON files if using no_compile or no_bazel
        if self.use_cached_discovery:
            self.all_vcomp = self.json_to_dict("all_vcomp.json")
            self.tests_to_tags = self.json_to_dict("tests_to_tags.json")
            self.tests_to_simulator = self.json_to_dict("tests_to_simulator.json")

        # Process each test specification from command line
        for ta in self.options.tests:
            bglob, tglob, iterations = self._split_btglob(ta.btiglob)

            # Find matching vcomponents
            query = "*:{}".format(bglob)
            vcomp_match = fnmatch.filter(self.all_vcomp.keys(), query)

            self.log.debug("Looking for tests matching %s", ta)

            # Process each matching vcomponent
            for vcomp in vcomp_match:
                tests = self.all_vcomp[vcomp]
                query = "*:{}".format(tglob)
                test_match = fnmatch.filter(tests, query)
                for test in test_match:
                    # Filter tests based on tags
                    test_tags = set(self.tests_to_tags[test])
                    if ta.tag and not ((ta.tag & test_tags) == ta.tag):
                        self.log.debug("  Skipping %s because it did not match --tag=%s", test, ta.tag)
                        continue
                    if ta.ntag and (ta.ntag & test_tags):
                        self.log.debug("  Skipping %s because it matched --ntags=%s", test, ta.ntag)
                        continue
                    if self.options.global_tag and not (
                        (self.options.global_tag & test_tags) == self.options.global_tag):
                        self.log.debug("  Skipping %s because it did not match --global-tag=%s", test,
                                       self.options.global_tag)
                        continue
                    if self.options.global_ntag and (self.options.global_ntag & test_tags):
                        self.log.debug("  Skipping %s because it matched --global-ntags=%s", test,
                                       self.options.global_ntag)
                        continue
                    self.log.debug("  %s met tag requirements", test)
                    # Update iteration count if larger than current
                    try:
                        new_max = max(tests[test], iterations)
                    except KeyError:
                        new_max = iterations
                    tests[test] = new_max

        # Remove inactive tests and vcomponents
        for vcomp, tests in self.all_vcomp.items():
            self.all_vcomp[vcomp] = dict([(t, i) for t, i in tests.items() if i])
        self.all_vcomp = dict([(vcomp, tests) for vcomp, tests in self.all_vcomp.items() if len(tests)])

        # Log final list of tests to run
        table_output = []
        table_output.append(self.table_format("bench", "test", "count"))
        table_output.append(self.table_format("-----", "----", "-----"))
        vcomps = list(self.all_vcomp.keys())
        vcomps.sort()
        for vcomp in vcomps:
            bench = vcomp.split(':')[1]
            tests = self.all_vcomp[vcomp]
            test_targets = list(tests.keys())
            test_targets.sort()
            for i, test_target in enumerate(test_targets):
                test = test_target.split(':')[1]
                count = tests[test_target]
                if i == 0:
                    table_output.append(self.table_format(bench, test, str(count)))
                else:
                    table_output.append(self.table_format('', test, str(count)))

        self.log.info("Tests to run:\n%s", "\n".join(table_output))

        # Exit if only discovery was requested
        if self.options.discovery_only:
            self.log.info("Ran with --discovery-only option. Exiting.")
            sys.exit(0)
