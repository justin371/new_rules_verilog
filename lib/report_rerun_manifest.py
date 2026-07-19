import json
import os
from pathlib import Path
import re

from lib.regression_report import _is_safe_report_component

MANIFEST_SCHEMA_VERSION = 1


def _require_string(mapping, key, section):
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("Report rerun manifest {} requires a non-empty {} string".format(section, key))


def load_report_rerun_manifest(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as filep:
        manifest = json.load(filep)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported report rerun manifest: {}".format(manifest_path))
    for key in ("webroot_dir", "project_dir", "regression_dir"):
        _require_string(manifest, key, "root")

    header = manifest.get("header")
    if not isinstance(header, dict):
        raise ValueError("Report rerun manifest requires a header object")
    for key in ("branch", "project_name", "revision", "simulator", "time", "username"):
        _require_string(header, key, "header")
    for key in ("commit", "tag"):
        if not isinstance(header.get(key), str):
            raise ValueError("Report rerun manifest header requires a {} string".format(key))
    if header.get("simulator") != "VCS" or header.get("coverage_enabled") is not True:
        raise ValueError("Report rerun manifests require VCS coverage")
    for key in ("project_name", "time"):
        if not _is_safe_report_component(header[key]):
            raise ValueError("Report rerun manifest header contains an unsafe {} path component".format(key))
    revision_of = header.get("revision_of")
    if revision_of is not None and not isinstance(revision_of, str):
        raise ValueError("Report rerun manifest header requires a revision_of string")
    rerun_attempt = header.get("rerun_attempt", 0)
    if isinstance(rerun_attempt, bool) or not isinstance(rerun_attempt, int) or rerun_attempt < 0:
        raise ValueError("Report rerun manifest header requires a non-negative rerun_attempt integer")

    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("Report rerun manifest requires a coverage object")
    _require_string(coverage, "baseline_db", "coverage")
    for key in ("urg_parallel", "urg_show_tests"):
        if key in coverage and not isinstance(coverage[key], bool):
            raise ValueError("Report rerun manifest coverage requires a boolean {}".format(key))

    trd = manifest.get("trd")
    if not isinstance(trd, list) or not trd:
        raise ValueError("Report rerun manifest requires non-empty report rows")
    if any(not isinstance(row, list) or len(row) < 9 or not all(isinstance(value, str) for value in row[:9])
           for row in trd):
        raise ValueError("Report rerun manifest contains invalid report rows")
    if any(row[1] and row[1] != "vcomp" and (len(row) < 10 or not isinstance(row[9], str) or not row[9])
           for row in trd):
        raise ValueError("Report rerun manifest test rows require Bazel targets")
    if any(value and re.fullmatch(r"[0-9]+", value) is None for row in trd for value in row[3:7]):
        raise ValueError("Report rerun manifest report row counts must be non-negative integers")
    category_stats = manifest.get("category_stats", {})
    if not isinstance(category_stats, dict):
        raise ValueError("Report rerun manifest category_stats must be an object")
    for category, stats in category_stats.items():
        if (not isinstance(category, str) or not isinstance(stats, dict) or any(
                isinstance(stats.get(key), bool) or not isinstance(stats.get(key), int)
                for key in ("total", "executed", "passed"))):
            raise ValueError("Report rerun manifest contains invalid category statistics")
    failed_tests = manifest.get("failed_tests")
    if not isinstance(failed_tests, list) or not failed_tests or not all(
            isinstance(item, dict) for item in failed_tests):
        raise ValueError("Report rerun manifest has no failed tests")
    bench = failed_tests[0].get("bench")
    for failed_test in failed_tests:
        for key in ("bench", "test", "target", "rerun_script"):
            _require_string(failed_test, key, "failed test")
        seed = failed_test.get("seed")
        iteration = failed_test.get("iteration", 1)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("Report rerun manifest failed test requires an integer seed")
        if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 1:
            raise ValueError("Report rerun manifest failed test requires a positive iteration")
        if failed_test["bench"] != bench:
            raise ValueError("Report rerun manifest must contain one bench")
        if not _is_safe_report_component(failed_test["bench"]):
            raise ValueError("Report rerun manifest contains an unsafe bench path component")
    return manifest


def _resolved_child(path, root, label, must_exist=True):
    root_path = Path(root).resolve()
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(root_path):
        raise ValueError("{} must remain under {}: {}".format(label, root_path, candidate))
    if must_exist and not candidate.exists():
        raise FileNotFoundError("{} does not exist: {}".format(label, candidate))
    return candidate


def validate_report_rerun_paths(manifest):
    regression_dir = Path(manifest["regression_dir"]).resolve()
    project_dir = Path(manifest["project_dir"]).resolve()
    webroot_dir = Path(manifest["webroot_dir"]).resolve()
    if not regression_dir.is_dir():
        raise FileNotFoundError("Regression directory does not exist: {}".format(regression_dir))
    if not project_dir.is_dir():
        raise FileNotFoundError("Project directory does not exist: {}".format(project_dir))

    coverage = manifest["coverage"]
    coverage_root = regression_dir / "report_coverage"
    baseline_db = _resolved_child(coverage["baseline_db"], coverage_root, "Coverage baseline")
    if baseline_db == coverage_root:
        raise ValueError("Coverage baseline must be below the report coverage directory")
    urg_argv = coverage.get("urg_argv", [])
    if not urg_argv or any(not isinstance(value, str) or "\n" in value or "\r" in value for value in urg_argv):
        raise ValueError("Coverage URG command is invalid")

    failed_tests = []
    for failed_test in manifest["failed_tests"]:
        rerun_script = _resolved_child(failed_test["rerun_script"], regression_dir, "Rerun script")
        if rerun_script.name != "rerun.sh" or not os.access(rerun_script, os.X_OK):
            raise ValueError("Rerun script is not executable: {}".format(rerun_script))
        failed_tests.append(dict(failed_test, rerun_script=str(rerun_script)))
    return regression_dir, project_dir, webroot_dir, baseline_db, urg_argv, failed_tests
