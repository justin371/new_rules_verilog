#!/usr/bin/env python

################################################################################
# standard lib imports
import ast
from contextlib import contextmanager
import fnmatch
import hashlib
import os
import re
import shlex
import subprocess
import sys
import json
import tempfile
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
    ".bazelignore",
    ".bazelrc",
    ".bazelversion",
    ".gitmodules",
    "MODULE.bazel",
    "MODULE.bazel.lock",
    "WORKSPACE",
    "WORKSPACE.bazel",
}
DISCOVERY_MAX_ARG_CHARS = 100000
DISCOVERY_MAX_SOURCE_RETRIES = 2
DISCOVERY_LOCAL_REPOSITORY_MAX_DEPTH = 32
DISCOVERY_LOCAL_REPOSITORY_MAX_DIRS = 4096
DISCOVERY_LOCAL_REPOSITORY_MAX_ENTRIES = 50000
DISCOVERY_LOCAL_REPOSITORY_MAX_METADATA_FILES = 4096
DISCOVERY_LOCAL_REPOSITORY_MAX_DECLARATION_BYTES = 4 * 1024 * 1024


class _DiscoveryDependencyScanLimit(Exception):

    def __init__(self, project_paths):
        super().__init__("local repository metadata scan limit reached")
        self.project_paths = project_paths


class _UnresolvedLocalRepositoryDeclaration(Exception):
    pass


def resolve_report_generation(report_option, total_simulations):
    if report_option is None:
        return total_simulations > 1
    return report_option


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
        self.options.report = resolve_report_generation(self.options.report, total_tests)

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
        descriptor, temporary_path = tempfile.mkstemp(prefix=".{}-".format(j),
                                                      suffix=".tmp",
                                                      dir=os.path.dirname(path),
                                                      text=True)
        try:
            with os.fdopen(descriptor, "w") as f:
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

    @contextmanager
    def _discovery_cache_lock(self, exclusive):
        """Lock complete discovery generations across supported POSIX processes."""
        cache_dir = os.path.dirname(self._cache_path(".discovery.lock"))
        os.makedirs(cache_dir, exist_ok=True)
        lock_path = self._cache_path(".discovery.lock")
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            try:
                import fcntl
            except ImportError:
                # Simmer's licensed runtime is POSIX-only. Keep unit-level
                # helpers usable on other hosts without claiming IPC safety.
                yield
                return

            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock_file, operation)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _read_discovery_cache_locked(self):
        generation = []
        for filename in DISCOVERY_CACHE_FILES:
            with open(self._cache_path(filename), "r", encoding="utf-8") as filep:
                generation.append(json.load(filep))
        return tuple(generation)

    def _load_discovery_cache_generation(self):
        with self._discovery_cache_lock(exclusive=False):
            return self._read_discovery_cache_locked()

    def _publish_discovery_cache(self, manifest=None):
        """Publish all discovery payloads as one advisory-locked generation."""
        if manifest is None:
            manifest = self._discovery_dependency_manifest()
        with self._discovery_cache_lock(exclusive=True):
            self.dict_to_json(self.all_vcomp, "all_vcomp.json")
            self.dict_to_json(self.tests_to_tags, "tests_to_tags.json")
            self.dict_to_json(self.tests_to_simulator, "tests_to_simulator.json")
            self.dict_to_json(manifest, "discovery_manifest.json")

    def _have_discovery_cache(self):
        return all(os.path.exists(self._cache_path(filename)) for filename in DISCOVERY_CACHE_FILES)

    def _discovery_dependency_manifest(self):
        submodule_state = self._git_submodule_state()
        cacheable = True
        try:
            dependency_paths = sorted(set(self._iter_discovery_dependency_paths(submodule_state)))
        except _DiscoveryDependencyScanLimit as exc:
            dependency_paths = sorted(set(exc.project_paths))
            cacheable = False
        files = []
        project_root = os.path.realpath(self.proj_dir)
        for path in dependency_paths:
            relative_path = os.path.relpath(os.path.realpath(path), project_root).replace(os.sep, "/")
            try:
                with open(path, "rb") as filep:
                    digest = hashlib.sha256(filep.read()).hexdigest()
            except OSError:
                digest = "missing"
            files.append({"path": relative_path, "sha256": digest})
        return {
            "schema_version": 3,
            "cacheable": cacheable,
            "allow_no_run": bool(self.options.allow_no_run),
            "discovery_query": self._build_vcomp_discovery_query(),
            "git_submodules": submodule_state,
            "files": files,
        }

    def _git_submodule_state(self):
        result = subprocess.run(
            ["git", "submodule", "status", "--recursive"],
            cwd=self.proj_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        return sorted(line.strip() for line in result.stdout.splitlines()) if result.returncode == 0 else []

    @staticmethod
    def _is_discovery_dependency(relative_path):
        filename = os.path.basename(relative_path)
        return (filename in ("BUILD", "BUILD.bazel") or filename.endswith(".bzl") or filename.startswith(".bazelrc")
                or filename.endswith(".bazelrc") or relative_path in DISCOVERY_ROOT_FILES)

    def _bazelrc_dependency_paths(self):
        pending = [
            "/etc/bazel.bazelrc",
            os.path.expanduser("~/.bazelrc"),
            os.path.join(self.proj_dir, ".bazelrc"),
        ]
        seen = set()
        while pending:
            path = os.path.abspath(pending.pop())
            if path in seen:
                continue
            seen.add(path)
            yield path
            try:
                with open(path, "r", encoding="utf-8", errors="surrogateescape") as filep:
                    lines = filep
                    for line in lines:
                        try:
                            fields = shlex.split(line, comments=True, posix=True)
                        except ValueError:
                            continue
                        if len(fields) != 2 or fields[0] not in ("import", "try-import"):
                            continue
                        imported_path = fields[1]
                        imported_path = imported_path.strip().replace("%workspace%", self.proj_dir)
                        imported_path = imported_path.replace("%home%", os.path.expanduser("~"))
                        if not os.path.isabs(imported_path):
                            imported_path = os.path.join(os.path.dirname(path), imported_path)
                        pending.append(imported_path)
            except OSError:
                continue

    def _write_discovery_manifest(self):
        with self._discovery_cache_lock(exclusive=True):
            self.dict_to_json(self._discovery_dependency_manifest(), "discovery_manifest.json")

    @staticmethod
    def _local_repository_paths(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8", errors="surrogateescape") as filep:
                source = filep.read(DISCOVERY_LOCAL_REPOSITORY_MAX_DECLARATION_BYTES + 1)
            if len(source) > DISCOVERY_LOCAL_REPOSITORY_MAX_DECLARATION_BYTES:
                raise _UnresolvedLocalRepositoryDeclaration(metadata_path)
            tree = ast.parse(source, filename=metadata_path)
        except OSError:
            return []
        except (SyntaxError, ValueError):
            if "local_repository" in source or "new_local_repository" in source:
                raise _UnresolvedLocalRepositoryDeclaration(metadata_path)
            return []

        paths = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = None
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            repository_function_names = {"local_repository", "new_local_repository"}
            wrapped_function_name = None
            if node.args:
                if isinstance(node.args[0], ast.Name):
                    wrapped_function_name = node.args[0].id
                elif isinstance(node.args[0], ast.Attribute):
                    wrapped_function_name = node.args[0].attr
            direct_declaration = function_name in repository_function_names
            wrapped_declaration = wrapped_function_name in repository_function_names
            if not direct_declaration and not wrapped_declaration:
                continue
            resolved_path = False
            for keyword in node.keywords:
                if keyword.arg != "path":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    paths.append(keyword.value.value)
                    resolved_path = True
                break
            if not resolved_path:
                raise _UnresolvedLocalRepositoryDeclaration(metadata_path)
        return paths

    def _iter_local_repository_metadata(self, repository_root):
        repository_root = os.path.realpath(repository_root)
        if not os.path.isdir(repository_root):
            return

        pending = [(repository_root, 0)]
        directories_seen = 0
        entries_seen = 0
        metadata_files_seen = 0
        metadata_paths = []
        while pending:
            directory, depth = pending.pop()
            directories_seen += 1
            if directories_seen > DISCOVERY_LOCAL_REPOSITORY_MAX_DIRS:
                return None
            try:
                entries = os.scandir(directory)
            except OSError:
                return None
            with entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            if entry.name not in ("BUILD", "BUILD.bazel") and not entry.name.endswith(".bzl"):
                                continue
                            entries_seen += 1
                            if entries_seen > DISCOVERY_LOCAL_REPOSITORY_MAX_ENTRIES:
                                return None
                            metadata_files_seen += 1
                            if metadata_files_seen > DISCOVERY_LOCAL_REPOSITORY_MAX_METADATA_FILES:
                                return None
                            metadata_paths.append(entry.path)
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in (".git", ".simmer") or entry.name.startswith("bazel-"):
                                continue
                            entries_seen += 1
                            if entries_seen > DISCOVERY_LOCAL_REPOSITORY_MAX_ENTRIES:
                                return None
                            if depth >= DISCOVERY_LOCAL_REPOSITORY_MAX_DEPTH:
                                return None
                            pending.append((entry.path, depth + 1))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        return None
                    entries_seen += 1
                    if entries_seen > DISCOVERY_LOCAL_REPOSITORY_MAX_ENTRIES:
                        return None
                    if entry.name not in ("BUILD", "BUILD.bazel") and not entry.name.endswith(".bzl"):
                        continue
                    metadata_files_seen += 1
                    if metadata_files_seen > DISCOVERY_LOCAL_REPOSITORY_MAX_METADATA_FILES:
                        return None
                    metadata_paths.append(entry.path)
        return metadata_paths

    def _iter_project_discovery_dependency_paths(self, submodule_state):
        indexed_result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=self.proj_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        ignored_result = subprocess.run(
            [
                "git",
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--",
                ":(glob)**/BUILD",
                ":(glob)**/BUILD.bazel",
                ":(glob)**/*.bzl",
                ":(glob)**/*.bazelrc",
                ":(glob)**/.bazelrc*",
                *sorted(DISCOVERY_ROOT_FILES),
            ],
            cwd=self.proj_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if indexed_result.returncode == 0 and ignored_result.returncode == 0:
            discovery_paths = []
            seen_paths = set()
            for relative_path in indexed_result.stdout.splitlines() + ignored_result.stdout.splitlines():
                if relative_path and relative_path not in seen_paths:
                    discovery_paths.append(relative_path)
                    seen_paths.add(relative_path)
            for relative_path in discovery_paths:
                if self._is_discovery_dependency(relative_path):
                    yield os.path.join(self.proj_dir, os.path.normpath(relative_path))
            for line in submodule_state:
                fields = line.lstrip("-+U ").split()
                if len(fields) < 2:
                    continue
                submodule_root = os.path.join(self.proj_dir, fields[1])
                for root, dirs, files in os.walk(submodule_root):
                    dirs[:] = [directory for directory in dirs if directory not in (".git", ".simmer")]
                    for filename in files:
                        relative_path = os.path.relpath(os.path.join(root, filename), self.proj_dir)
                        if self._is_discovery_dependency(relative_path):
                            yield os.path.join(root, filename)
            yield from self._bazelrc_dependency_paths()
            return

        for root, dirs, files in os.walk(self.proj_dir):
            dirs[:] = [
                directory for directory in dirs
                if directory not in (".git", ".simmer") and not directory.startswith("bazel-")
            ]
            for filename in files:
                relative_path = os.path.relpath(os.path.join(root, filename), self.proj_dir)
                if self._is_discovery_dependency(relative_path):
                    yield os.path.join(root, filename)
        yield from self._bazelrc_dependency_paths()

    def _iter_discovery_dependency_paths(self, submodule_state=None):
        if submodule_state is None:
            submodule_state = self._git_submodule_state()
        project_paths = list(self._iter_project_discovery_dependency_paths(submodule_state))
        yield from project_paths

        repository_roots = set()
        project_root = os.path.realpath(self.proj_dir)
        for metadata_path in project_paths:
            metadata_path = os.path.realpath(metadata_path)
            try:
                if os.path.commonpath((project_root, metadata_path)) != project_root:
                    continue
            except ValueError:
                continue
            if not self._is_discovery_dependency(os.path.relpath(metadata_path, project_root)):
                continue
            try:
                repository_paths = self._local_repository_paths(metadata_path)
            except _UnresolvedLocalRepositoryDeclaration:
                raise _DiscoveryDependencyScanLimit(project_paths)
            for repository_path in repository_paths:
                if not os.path.isabs(repository_path):
                    repository_path = os.path.join(project_root, repository_path)
                repository_root = os.path.realpath(repository_path)
                if repository_root != project_root:
                    repository_roots.add(repository_root)
        for repository_root in sorted(repository_roots):
            metadata_paths = self._iter_local_repository_metadata(repository_root)
            if metadata_paths is None:
                raise _DiscoveryDependencyScanLimit(project_paths)
            yield from metadata_paths

    def _discovery_cache_is_fresh(self):
        try:
            with self._discovery_cache_lock(exclusive=False):
                if not self._have_discovery_cache():
                    return False
                _, _, _, cached_manifest = self._read_discovery_cache_locked()
                if not cached_manifest.get("cacheable", True):
                    return False
                current_manifest = self._discovery_dependency_manifest()
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        if cached_manifest != current_manifest:
            self.log.debug("Discovery cache dependency manifest changed")
            return False
        return True

    def _should_use_cached_discovery(self):
        try:
            with self._discovery_cache_lock(exclusive=False):
                if not self._have_discovery_cache():
                    return False
                all_vcomp, tests_to_tags, tests_to_simulator, cached_manifest = self._read_discovery_cache_locked()
                if not cached_manifest.get("cacheable", True):
                    return False
                if cached_manifest != self._discovery_dependency_manifest():
                    self.log.debug("Discovery cache dependency manifest changed")
                    return False
        except (OSError, ValueError, json.JSONDecodeError):
            return False

        self._cached_discovery = (all_vcomp, tests_to_tags, tests_to_simulator)
        self.log.info("Using cached test discovery")
        return True

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

    @staticmethod
    def _chunk_arguments(arguments, max_chars=DISCOVERY_MAX_ARG_CHARS):
        chunks = []
        current = []
        current_chars = 0
        for argument in arguments:
            argument_chars = len(argument) + 1
            if current and current_chars + argument_chars > max_chars:
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(argument)
            current_chars += argument_chars
        if current:
            chunks.append(current)
        return chunks

    def test_discovery_all(self):
        for attempt in range(DISCOVERY_MAX_SOURCE_RETRIES + 1):
            manifest_before = self._discovery_dependency_manifest()
            self._discover_test_metadata()
            manifest_after = self._discovery_dependency_manifest()
            if manifest_before == manifest_after:
                self._publish_discovery_cache(manifest_after)
                return
            self.log.warning("Discovery inputs changed while Bazel metadata was being collected; retrying")
        self.log.critical("Discovery inputs kept changing; rerun simmer from a stable checkout")

    def _discover_test_metadata(self):
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

        test_queries = ["({})".format(self._build_test_cfg_query(vcomp)) for vcomp in sorted(self.all_vcomp)]
        query_results = []
        for query_chunk in self._chunk_arguments(test_queries):
            combined_test_query = " union ".join(query_chunk)
            dtp.reset()
            returncode, stdout, stderr = self._run_command(["bazel", "cquery", combined_test_query], )
            dtp.stop_and_print()
            if returncode:
                self.log.critical("bazel test discovery failed:\n%s", stderr)
            query_results.extend(re.sub(r"\([a-z0-9]{7,64}\) *", "", stdout.replace('\n', ' ')).split())
        query_results = list(dict.fromkeys(query_results))

        text = []
        for target_chunk in self._chunk_arguments(query_results):
            dtp.reset()
            returncode, stdout, stderr = self._run_command([
                "bazel",
                "build",
                *target_chunk,
                "--aspects",
                "@rules_verilog//verilog/private:dv.bzl%verilog_dv_test_cfg_info_aspect",
            ])
            dtp.stop_and_print()
            if returncode:
                self.log.critical("bazel test discovery failed:\n%s", stderr)
            text.extend(stdout.split('\n') + stderr.split('\n'))

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

    def test_discovery_match(self):
        """
        Match tests based on command line arguments and tags
        Filters the discovered tests to those that should be run
        """
        # Load test information from JSON files if using no_compile or no_bazel
        if self.use_cached_discovery:
            cached_discovery = getattr(self, "_cached_discovery", None)
            if cached_discovery is None:
                cached_discovery = self._load_discovery_cache_generation()[:3]
            self.all_vcomp, self.tests_to_tags, self.tests_to_simulator = cached_discovery

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
