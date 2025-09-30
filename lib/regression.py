#!/usr/bin/env python

################################################################################
# standard lib imports
import fnmatch
import os
import re
import shlex
import subprocess
import sys
from tempfile import TemporaryFile
import datetime
import json

################################################################################
# rules_verilog lib imports
from lib import rv_utils

# I'd rather create a "plain" message in the logger
# that doesn't format, but more work than its worth
LOGGER_INDENT = 8
BENCHES_REL_DIR = os.environ.get('BENCHES_REL_DIR', 'benches')


class RegressionConfig():
    """Configuration class for managing regression tests"""

    def __init__(self, options, log):
        self.options = options
        self.log = log

        self.tests_to_tags = {}  # Mapping of tests to their tags
        self.max_bench_name_length = 20  # Max length for bench name formatting
        self.max_test_name_length = 20   # Max length for test name formatting

        self.suppress_output = False  # Flag to suppress test output

        self.proj_dir = self.options.proj_dir
        self.regression_dir = rv_utils.calc_simresults_location(self.proj_dir)

        # Create regression directory if it doesn't exist
        if not os.path.exists(self.regression_dir):
            os.mkdir(self.regression_dir)

        self.invocation_dir = os.getcwd()  # Directory where regression was started

        # Run test discovery if needed
        if not self.options.no_compile or not os.path.exists(
                self.proj_dir + "/" + "all_vcomp.json") or not os.path.exists(self.proj_dir + "/" +
                                                                              "tests_to_tags.json"):
            if not self.options.no_bazel:
                self.test_discovery_all()
        self.test_discovery_match()

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

        self.deferred_messages = []  # Messages to be printed at completion
        self.current_time = 0        # Timestamp for regression

        # Subsystem configuration (with tag associations)
        self.category_total_cases = {}
        self.load_category_config(options.category_cfg)

    def load_category_config(self, cfg_path: str = None):
        """
        Load subsystem configuration with tag associations
        Priority: specified path > project dir > default config
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
        max_sim_len = 5  # Max length for simulator abbreviation
        sim_short = sim[:max_sim_len]
        return "{:{}s}  {:{}s}  {:-4d}  {:{}s}".format(
            b,
            self.max_bench_name_length,
            t,
            self.max_test_name_length,
            i,
            sim_short,
            max_sim_len
        )

    def dict_to_json(self, d, j):
        """
        Save dictionary to JSON file
        :param d: Dictionary to save
        :param j: Filename to save to
        """
        try:
            with open(self.proj_dir + "/" + j, "w") as f:
                json.dump(d, f, indent=4)
        except Exception as e:
            self.log.critical("Failed to create '%s' file: %s", j, e)

    def json_to_dict(self, j):
        """
        Load dictionary from JSON file
        :param j: Filename to load from
        :return: Loaded dictionary
        """
        if os.path.exists(self.proj_dir + "/" + j):
            try:
                with open(self.proj_dir + "/" + j, "r") as f:
                    bazel_data = f.read()
            except Exception as e:
                self.log.critical("Failed to open '%s' file: %s", j, e)
            d = json.loads(bazel_data)
            return d
        else:
            self.log.critical("'%s' not found. Please compile first!", j)
            sys.exit(0)

    def test_discovery_all(self):
        """
        Discover all available tests in the checkout
        Filters based on command line specifications
        """
        self.log.summary("Starting test discovery")
        dtp = rv_utils.DatetimePrinter(self.log)

        # Query for all testbenches using bazel
        cmd = "bazel query \"kind(dv_tb, //{}/...)\"".format(BENCHES_REL_DIR)
        self.log.debug(" > %s", cmd)

        dtp.reset()
        with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
            p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=True)
            p.wait()
            stdout_fp.seek(0)
            stderr_fp.seek(0)
            stdout = stdout_fp.read()
            stderr = stderr_fp.read()
            if p.returncode:
                self.log.critical("bazel bench discovery failed: %s", stderr.decode('ascii'))

        dtp.stop_and_print()
        self.all_vcomp = stdout.decode('ascii').split('\n')
        self.all_vcomp = dict([(av, {}) for av in self.all_vcomp if av])

        all_tbs = []
        for ta in self.options.tests:
            tb_name = ta.btiglob.split(":")[0]
            query = "*:{}".format(tb_name)  # Match against bazel label
            tb_match = fnmatch.filter(self.all_vcomp.keys(), query)
            all_tbs = all_tbs + tb_match

        self.all_vcomp = stdout.decode('ascii').split('\n')
        self.all_vcomp = dict([(av, {}) for av in all_tbs if av])

        vcomp_to_query_results = {}

        # Discover tests for each vcomponent
        for vcomp, tests in self.all_vcomp.items():
            vcomp_path, _ = vcomp.split(':')
            test_wildcard = os.path.join(vcomp_path, "tests", "...")
            if self.options.allow_no_run:
                cmd = 'bazel cquery "attr(abstract, 0, kind(dv_test_base_cfg, {test_wildcard} intersect allpaths({test_wildcard}, {vcomp})))"'.format(
                    test_wildcard=test_wildcard, vcomp=vcomp)
            else:
                cmd = 'bazel cquery "attr(no_run, 0, attr(abstract, 0, kind(dv_test_base_cfg, {test_wildcard} intersect allpaths({test_wildcard}, {vcomp}))))"'.format(
                    test_wildcard=test_wildcard, vcomp=vcomp)

            self.log.debug(" > %s", cmd)

            dtp.reset()

            with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
                cmd = shlex.split(cmd)
                p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=False, bufsize=-1)
                p.wait()
                stdout_fp.seek(0)
                stderr_fp.seek(0)
                stdout = stdout_fp.read()
                stderr = stderr_fp.read()
                if p.returncode:
                    self.log.critical("bazel test discovery failed:\n%s", stderr.decode('ascii'))

            dtp.stop_and_print()
            query_results = stdout.decode('ascii').replace('\n', ' ')
            query_results = re.sub(r"\([a-z0-9]{7,64}\) *", "", query_results)
            vcomp_to_query_results[vcomp] = query_results

        # Build test configurations
        for vcomp, tests in self.all_vcomp.items():
            query_results = vcomp_to_query_results[vcomp]
            cmd = "bazel build {} --aspects @rules_verilog//verilog/private:dv.bzl%verilog_dv_test_cfg_info_aspect".format(
                query_results)
            self.log.debug(" > %s", cmd)

            dtp.reset()
            with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
                cmd = shlex.split(cmd)
                p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=False, bufsize=-1)
                p.wait()
                stdout_fp.seek(0)
                stderr_fp.seek(0)
                stdout = stdout_fp.read()
                stderr = stderr_fp.read()
                if p.returncode:
                    self.log.critical("bazel test discovery failed:\n%s", stderr.decode('ascii'))

            dtp.stop_and_print()
            text = stdout.decode('ascii').split('\n') + stderr.decode('ascii').split('\n')

            # Parse test information from output
            ttv = [
                re.search(r'verilog_dv_test_cfg_info\(@(?:@)?(?P<test>.*), @(?:@)?(?P<vcomp>.*), \[(?P<tags>.*)\]\)',
                          line) for line in text
            ]
            ttv = [match for match in ttv if match]

            # Extract matching tests and their tags
            matching_tests = [(mt.group('test'), eval("[%s]" % mt.group('tags'))) for mt in ttv
                              if mt.group('vcomp') == vcomp]
            self.tests_to_tags.update(matching_tests)
            tests.update(dict([(t[0], 0) for t in matching_tests]))

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

    def test_discovery_match(self):
        """
        Match tests based on command line arguments and tags
        Filters the discovered tests to those that should be run
        """
        # Load test information from JSON files if using no_compile or no_bazel
        if self.options.no_compile or self.options.no_bazel:
            self.all_vcomp = self.json_to_dict("all_vcomp.json")
            self.tests_to_tags = self.json_to_dict("tests_to_tags.json")

        # Process each test specification from command line
        for ta in self.options.tests:
            try:
                btglob, iterations = ta.btiglob.split("@")
                try:
                    iterations = int(iterations)
                except ValueError:
                    self.log.critical("Iterations (value after @) must be an integer: '%s'", ta.btiglob)
            except ValueError:
                btglob = ta.btiglob
                iterations = 1

            try:
                bglob, tglob = btglob.split(":")
            except ValueError:
                # Handle case where only test glob is provided (when in testbench directory)
                pwd = os.getcwd()
                benches_dir = os.path.join(self.proj_dir, BENCHES_REL_DIR)
                if not (benches_dir in pwd and len(benches_dir) < len(pwd)):
                    self.log.critical("Not in a benches/ directory. Must provide bench:test style glob.")
                bglob = pwd[len(benches_dir) + 1:]
                tglob = btglob

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
