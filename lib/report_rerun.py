from collections import Counter
import copy
import datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from lib.regression_report import RegressionReport, _slug, coverage_artifact_lock
from lib.report_rerun_manifest import load_report_rerun_manifest, validate_report_rerun_paths
from lib.simulators.base import run_bounded_process
from lib.simulators.vcs import merge_report_rerun_coverage


def _run_failed_test(failed_test, artifact_dir, revision_time, project_dir, log):
    # rerun.sh selects one exact test and seed, so the nested simmer invocation
    # always numbers that new run i1. The original iteration remains in the
    # supplement artifact name and report counts below.
    target_digest = hashlib.sha256(failed_test["target"].encode("utf-8")).hexdigest()
    target_name = "{}_{}".format(_slug(failed_test["test"])[:64], target_digest[:32])
    directory_suffix = "_i1_report_rerun_{}_{}".format(revision_time, target_digest[:16])
    supplement_dir = artifact_dir / "supplements"
    destination = supplement_dir / "{}_{}_i{}.vdb".format(
        target_name,
        failed_test["seed"],
        failed_test.get("iteration", 1),
    )
    if destination.exists():
        shutil.rmtree(destination)
    command = [
        failed_test["rerun_script"],
        "--no-report",
    ]
    environment = dict(os.environ)
    simmer_launcher = shutil.which(sys.argv[0]) or sys.argv[0]
    environment.setdefault("SIMMER_BIN", os.path.abspath(simmer_launcher))
    environment["SIMMER_REPORT_RERUN_COVERAGE_DIR"] = str(destination)
    environment["SIMMER_REPORT_RERUN_DIR_SUFFIX"] = directory_suffix
    result = run_bounded_process(
        command,
        cwd=project_dir,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("Failed report rerun for %s seed %s:\n%s\n%s", failed_test["target"], failed_test["seed"],
                  result.stdout, result.stderr)
        shutil.rmtree(destination, ignore_errors=True)
        return None
    if not destination.is_dir():
        log.error("Successful report rerun did not export VCS coverage: %s", destination)
        return None
    return destination


def _discard_revision_artifacts(artifact_dir):
    shutil.rmtree(artifact_dir, ignore_errors=True)
    try:
        artifact_dir.parent.rmdir()
    except OSError:
        pass


def _updated_results(trd, successful_tests, category_stats):
    successful_counts = Counter((item["bench"], item["target"]) for item in successful_tests)
    updated_trd = [list(row) for row in trd]
    updated_categories = copy.deepcopy(category_stats)
    current_bench = None
    for row in updated_trd:
        if row[0]:
            current_bench = row[0]
        test_target = row[9] if len(row) > 9 else ""
        key = (current_bench, test_target)
        completed = successful_counts.get(key, 0)
        if not completed or row[1] == "vcomp":
            continue
        previous_failed = int(row[5] or 0)
        completed = min(completed, previous_failed)
        row[3] = str(int(row[3] or 0) + completed)
        row[5] = str(previous_failed - completed) if previous_failed > completed else ""
        if previous_failed == completed and not row[4] and int(row[3] or 0) == int(row[6] or 0):
            for category in filter(None, row[8].split(",")):
                if category in updated_categories:
                    updated_categories[category]["passed"] += 1
    return updated_trd, updated_categories


def run_report_rerun(manifest_path, template_env, log):
    """Execute failed tests from one manifest and publish a revision report."""
    manifest = load_report_rerun_manifest(manifest_path)
    regression_dir, project_dir, webroot_dir, baseline_db, urg_argv, failed_tests = validate_report_rerun_paths(
        manifest)
    revision_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bench_name = failed_tests[0]["bench"]
    artifact_dir = regression_dir / "report_coverage" / revision_time / _slug(bench_name)

    successful_tests = []
    remaining_tests = []
    supplements = []
    coverage_root = regression_dir / "report_coverage"
    baseline_timestamp = baseline_db.relative_to(coverage_root).parts[0]
    with coverage_artifact_lock(regression_dir, baseline_timestamp, shared=True):
        if not baseline_db.is_dir():
            raise FileNotFoundError("Coverage baseline does not exist: {}".format(baseline_db))
        artifact_dir.mkdir(parents=True)
        try:
            for failed_test in failed_tests:
                supplement = _run_failed_test(failed_test, artifact_dir, revision_time, project_dir, log)
                if supplement is None:
                    remaining_tests.append(failed_test)
                else:
                    successful_tests.append(failed_test)
                    supplements.append(supplement)

            if not successful_tests:
                _discard_revision_artifacts(artifact_dir)
                log.error("No failed test passed; the original report and coverage baseline were left unchanged")
                return 1

            coverage = manifest["coverage"]
            revised_baseline, coverage_metrics = merge_report_rerun_coverage(coverage, urg_argv, baseline_db,
                                                                             supplements, artifact_dir, log)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit):
            _discard_revision_artifacts(artifact_dir)
            raise
    updated_trd, updated_categories = _updated_results(manifest["trd"], successful_tests,
                                                       manifest.get("category_stats", {}))
    header = dict(manifest["header"])
    header["revision_of"] = header.get("revision_of", header["time"])
    header["rerun_attempt"] = int(header.get("rerun_attempt", 0)) + 1
    header["time"] = revision_time

    rerun_context = {
        bench_name: {
            "project_dir": str(project_dir),
            "regression_dir": str(regression_dir),
            "coverage": dict(
                coverage,
                artifact_dir=str(artifact_dir),
                baseline_db=str(revised_baseline),
            ),
            "failed_tests": remaining_tests,
        },
    }

    report = RegressionReport(SimpleNamespace(log=log, regression_dir=str(regression_dir)), template_env,
                              str(webroot_dir))
    try:
        report.run(
            header,
            updated_trd,
            {bench_name: coverage_metrics},
            updated_categories,
            rerun_context=rerun_context,
        )
    except (Exception, KeyboardInterrupt,
            SystemExit): # noqa: BROAD_EXCEPT_OK - rollback publication, then preserve the failure.
        if not getattr(report, "publication_committed", False):
            _discard_revision_artifacts(artifact_dir)
        raise
    log.info("Revised report created for %s at %s", bench_name, revision_time)
    return 1 if remaining_tests else 0
