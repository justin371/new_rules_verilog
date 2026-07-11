#!/usr/bin/env python
"""Utility class definitions for regression testing."""

import datetime
import getpass
import os
import re
import json
import subprocess
from typing import Dict, Optional
from urllib.parse import urlparse

LOGGER_INDENT = 8
class DatetimePrinter():
    """Utility class for tracking and printing time intervals"""

    def __init__(self, log):
        self.ts = datetime.datetime.now()
        self.log = log

    def reset(self):
        """Reset the start time to current time"""
        self.ts = datetime.datetime.now()

    def stop_and_print(self):
        """Calculate elapsed time since last reset and log it"""
        stop = datetime.datetime.now()
        delta = stop - self.ts
        self.log.debug("Last time check: %d", delta.total_seconds())


class IterationCfg():
    """Configuration class for test iterations"""

    def __init__(self, target):
        self.target = target # Total number of iterations to spawn
        self.spawn_count = 1 # Current count of spawned iterations
        self.jobs = [] # List of jobs associated with this iteration config
        self.vso_assignments = [] # Optional VSO ask-all planned runs for this test template

    def inc(self, job):
        """Increment spawn count and add a job to the iteration"""
        self.spawn_count += 1
        self.jobs.append(job)

    def __lt__(self, other):
        """Comparison method for sorting iterations by job name"""
        return self.jobs[0].name < other.jobs[0].name


def create_regression_log_file(rcfg):
    """
    Create a log file for regression results
    :param rcfg: Regression configuration object
    :return: Path to the created log file
    """
    target_folder = os.path.join(rcfg.regression_dir, 'regression_results')

    if not os.path.exists(target_folder):
        os.makedirs(target_folder)
        print(f"Folder created at: {target_folder}")

    current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    rcfg.current_time = current_time

    if len(rcfg.all_vcomp) > 1:
        log_file_name = f"regression_{current_time}.log"
    else:
        bench_name = next(iter(rcfg.all_vcomp.keys())).split(':')[1]
        log_file_name = f"{bench_name}_regression_{current_time}.log"

    log_file_path = os.path.join(target_folder, log_file_name)

    with open(log_file_path, 'w') as file:
        file.write("Regression log created at " + current_time)

    print(f"Regression log created at: {log_file_path}")
    return log_file_path


def print_summary(rcfg, vcomp_jobs, jm, trd):
    """
    Print a summary of regression results
    :param rcfg: Regression configuration object
    :param vcomp_jobs: Dictionary of vcomponent jobs
    :param jm: Job manager instance
    :param trd: List to store test results data
    """
    trd.clear()
    regression_log_path = None
    total_tests = sum([icfg.target for _, (icfgs, _) in rcfg.all_vcomp.items() for icfg in icfgs])
    if total_tests > 1:
        if not rcfg.options.no_run:
            regression_log_path = create_regression_log_file(rcfg)
    else:
        if rcfg.options.report:
            current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            rcfg.current_time = current_time

    table_data = [("bench", "test", "max_job_time", "passed", "skipped", "failed", "total", "logs", "category")]
    separator = [""] * len(table_data[0])
    table_data.append(separator)

    total_passed = 0
    total_skipped = 0
    total_failed = 0
    total = 0

    last = len(rcfg.all_vcomp) - 1
    for i, (vcomp_name, (icfgs, test_list)) in enumerate(rcfg.all_vcomp.items()):
        vcomp = vcomp_jobs[vcomp_name]
        tb_set = (vcomp.name, "vcomp", '', '1' if vcomp.jobstatus.successful else '',
                  '1' if vcomp.jobstatus == vcomp.jobstatus.SKIPPED else '',
                  '1' if not vcomp.jobstatus.successful else '', '1',
                  '' if vcomp.jobstatus.successful else str(vcomp.log_path), '')
        table_data.append(tb_set)
        trd.append(tb_set)

        if rcfg.options.no_run:
            continue

        icfgs.sort()
        for icfg in icfgs:
            if not icfg.jobs[0].vcomper is vcomp:
                continue
            timed_jobs = [job for job in icfg.jobs if job.jobstatus in [job.jobstatus.PASSED, job.jobstatus.FAILED]]
            max_job_time = max(timed_jobs, key=lambda x: x.job_time)._get_total_time_str() if timed_jobs else ""
            passed = [j for j in icfg.jobs if j.jobstatus.completed and j.jobstatus.successful]
            failed = [j for j in icfg.jobs if j.jobstatus == j.jobstatus.FAILED]
            skipped = [j for j in icfg.jobs if j.jobstatus not in [j.jobstatus.FAILED, j.jobstatus.PASSED]]

            total_passed += len(passed)
            total_failed += len(failed)
            total_skipped += len(skipped)
            total += len(icfg.jobs)

            try:
                assert len(passed) + len(failed) + len(skipped) == len(icfg.jobs), print(
                    len(passed), len(failed), len(skipped), len(icfg.jobs))
            except AssertionError as exc:
                if not jm.exited_prematurely:
                    raise exc

            test_target = getattr(icfg.jobs[0], "target", "")
            test_tags = set(rcfg.tests_to_tags.get(test_target, []))
            test_category = ",".join(
                category for category, config in getattr(rcfg, "category_total_cases", {}).items()
                if test_tags & set(config.get("tags", [])))
            test_set = ("", icfg.jobs[0].name,
                        str(max_job_time), str(len(passed)) if passed else "", str(len(skipped)) if skipped else "",
                        str(len(failed)) if failed else "", str(len(icfg.jobs)), "", test_category)
            table_data.append(test_set)
            trd.append(test_set)

            for j in failed:
                table_data.append(("", "", "", "", "", "", "", j.log_path if j.log_path else '', ""))
                trd.append(("", "", "", "", "", "", "", j.log_path if j.log_path else '', ""))
            if rcfg.options.nt:
                for j in passed:
                    table_data.append(("", "", "", "", "", "", "", j.log_path if j.log_path else '', ""))
                    trd.append(("", "", "", "", "", "", "", j.log_path if j.log_path else '', ""))

        if i != last:
            table_data.append(separator)

    assert all(len(i) == len(table_data[0]) for i in table_data)
    columns = list(zip(*table_data))
    column_widths = [max([len(cell) for cell in col]) for col in columns]
    formatter = " " * LOGGER_INDENT + "  ".join(
        ["{{:{}{}s}}".format('>' if i in [2, 3, 4, 5, 6] else '', c) for i, c in enumerate(column_widths)])
    for i, entry in enumerate(table_data):
        if entry == separator:
            table_data[i] = ['-' * cw for cw in column_widths]
    table_data_formatted = [formatter.format(*i) for i in table_data]
    rcfg.log.summary("Job Results\n%s", "\n".join(table_data_formatted))

    if total_tests > 1 and not rcfg.options.no_run:
        with open(regression_log_path, 'a') as file:
            formatted_string = "Job Results\n" + "\n".join(map(str, table_data_formatted))
            file.write(formatted_string)

    table_data = [("", "", "", "passed", "skipped", "failed", "total", "", "")]
    table_data.append(['-' * len(i) for i in table_data[0]])
    table_data.append(("", "", "", str(total_passed), str(total_skipped), str(total_failed), str(total), "", ""))
    table_data_formatted = [formatter.format(*i) for i in table_data]
    rcfg.log.summary("Simulation Summary\n%s", "\n".join(table_data_formatted))

    if total_tests > 1 and not rcfg.options.no_run:
        with open(regression_log_path, 'a') as file:
            formatted_string = "\n" + "Simulation Summary\n" + "\n".join(map(str, table_data_formatted))
            file.write(formatted_string)
    return regression_log_path


def print_simmer_profile(rcfg, jm):
    if not getattr(rcfg.options, "simmer_profile", False):
        return

    def job_name(job):
        name = str(job)
        if name.startswith("<") and name.endswith(">"):
            return str(getattr(job, "name", name))
        return name

    rows = []
    for duration, name, detail in getattr(rcfg, "profile_events", []):
        rows.append((duration, "PHASE", name, "DONE", "", detail))
    for job in getattr(jm, "_done", []):
        rows.append((
            job.duration_s,
            job.__class__.__name__,
            job_name(job),
            str(job.jobstatus),
            getattr(job, "job_dir", "") or "",
            getattr(job, "main_cmdline", "") or "",
        ))
    for job in getattr(jm, "_skipped", []):
        rows.append((
            0,
            job.__class__.__name__,
            job_name(job),
            str(job.jobstatus),
            getattr(job, "job_dir", "") or "",
            getattr(job, "main_cmdline", "") or "",
        ))

    rows.sort(key=lambda row: row[0], reverse=True)
    lines = ["{:<9} {:<18} {:<8} {}".format("seconds", "kind", "status", "item")]
    lines.append("{:<9} {:<18} {:<8} {}".format("-------", "----", "------", "----"))
    for duration, kind, name, status, job_dir, detail in rows:
        lines.append("{:<9.2f} {:<18} {:<8} {}".format(duration, kind, status, name))
        if job_dir:
            lines.append("{}dir: {}".format(" " * LOGGER_INDENT, job_dir))
        if detail:
            lines.append("{}cmd: {}".format(" " * LOGGER_INDENT, detail))

    rcfg.log.summary("Simmer Profile\n%s", "\n".join(" " * LOGGER_INDENT + line for line in lines))


def calc_simresults_location(checkout_path):
    """
    Calculate the path for storing regression results
    :param checkout_path: Path to the code checkout directory
    :return: Calculated results directory path
    """
    username = getpass.getuser()

    state_home = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    sim_results_root = os.path.expanduser(os.environ.get("SIMRESULTS") or os.path.join(state_home, "simmer"))
    sim_results_home = os.path.join(sim_results_root, username)
    os.makedirs(sim_results_home, exist_ok=True)

    try:
        checkout_path = re.search(r'{}/(.*)'.format(username), checkout_path).group(1)
    except AttributeError:
        pass
    checkout_path = checkout_path.replace('/', '_')
    regression_directory = checkout_path
    regression_directory = os.path.join(sim_results_home, regression_directory)
    return regression_directory


def _git_output(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def normalize_git_remote(remote):
    """Convert common SSH remotes to an HTTPS URL and remove one .git suffix."""
    if remote.startswith("git@") and ":" in remote:
        host, path = remote.split(":", 1)
        remote = "https://{}/{}".format(host.split("@", 1)[1], path)
    elif remote.startswith("ssh://"):
        parsed = urlparse(remote)
        remote = "https://{}{}".format(parsed.hostname, parsed.path)
    if remote.endswith(".git"):
        remote = remote[:-4]
    return remote.rstrip("/")


def get_report_header(rcfg):
    """
    Get header information for regression report
    :param rcfg: Regression configuration object
    :return: Dictionary containing report header information
    """
    project_dir = rcfg.proj_dir
    commit_id = _git_output(project_dir, "rev-parse", "HEAD")
    repo_url = normalize_git_remote(_git_output(project_dir, "remote", "get-url", "origin"))
    project_name = os.path.basename(urlparse(repo_url).path) if repo_url else ""
    if not project_name:
        project_name = os.path.basename(os.path.abspath(project_dir)) or "rules_verilog"
    commit_url = ""
    if repo_url.startswith(("https://", "http://")) and commit_id:
        commit_url = "{}/commit/{}".format(repo_url, commit_id)

    return {
        "username": getpass.getuser(),
        "simulator": getattr(rcfg, "simulator", getattr(rcfg.options, "simulator", "unknown")),
        "time": rcfg.current_time or datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        "project_name": project_name,
        "branch": _git_output(project_dir, "rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "tag": _git_output(project_dir, "describe", "--tags", "--exact-match"),
        "revision": _git_output(project_dir, "rev-parse", "--short", "HEAD") or "unknown",
        "commit": commit_url,
    }


def load_category_total_cases(cfg_path: Optional[str] = None) -> Dict[str, Dict]:
    """
    Load subsystem configuration including total cases and associated tags
    Format: {subsystem_name: {"total": int, "tags": [tag1, tag2, ...]}}
    :param cfg_path: Path to JSON config file (optional)
    :return: Subsystem configuration dictionary
    """
    if not cfg_path:
        raise ValueError("A category configuration path is required")
    if not os.path.isfile(cfg_path):
        raise FileNotFoundError(cfg_path)

    with open(cfg_path, "r", encoding="utf-8") as filep:
        config = json.load(filep)
    if not isinstance(config, dict):
        raise ValueError("Category configuration must be a JSON object: {}".format(cfg_path))
    for category, values in config.items():
        if not isinstance(values, dict):
            raise ValueError("Category '{}' must be an object".format(category))
        if not isinstance(values.get("total"), int) or values["total"] < 0:
            raise ValueError("Category '{}' requires a non-negative integer total".format(category))
        if not isinstance(values.get("tags"), list) or not all(isinstance(tag, str) for tag in values["tags"]):
            raise ValueError("Category '{}' requires a string-list tags field".format(category))
    return config


def calc_category_stats(rcfg) -> Dict[str, Dict[str, int]]:
    """
    Calculate category statistics with multi-iteration handling (strict mode)
    - 1 test = 1 execution regardless of iteration count
    - Test is counted as 'passed' ONLY if ALL iterations are successful
    :param rcfg: Regression configuration object
    :return: Statistics dictionary with executed/passed counts per category
    """
    category_stats = {
        category: {
            "total": config["total"],
            "executed": 0,
            "passed": 0,
            "test_records": set() # Track unique tests to avoid duplicate counting
        }
        for category, config in rcfg.category_total_cases.items()
    }

    if rcfg.options.no_run:
        # Remove internal tracking field before returning
        for stats in category_stats.values():
            del stats["test_records"]
        return category_stats

    # Process all test iterations and aggregate results by full Bazel target.
    for _, (icfgs, _) in rcfg.all_vcomp.items():
        for icfg in icfgs:
            if not icfg.jobs:
                continue
            test_target = getattr(icfg.jobs[0], "target", "")
            test_tags = set(rcfg.tests_to_tags.get(test_target, []))
            if not test_tags:
                continue
            completed_iterations = [
                job for job in icfg.jobs if job.jobstatus in [job.jobstatus.PASSED, job.jobstatus.FAILED]
            ]
            if not completed_iterations:
                continue

            for category, stats in category_stats.items():
                category_tags = set(rcfg.category_total_cases[category]["tags"])
                if not (test_tags & category_tags) or test_target in stats["test_records"]:
                    continue
                stats["test_records"].add(test_target)
                stats["executed"] += 1
                if len(completed_iterations) == len(icfg.jobs) and all(job.jobstatus.successful
                                                                       for job in completed_iterations):
                    stats["passed"] += 1

    # Clean up internal tracking field
    for stats in category_stats.values():
        del stats["test_records"]

    return category_stats


def print_category_summary(category_stats: Dict[str, Dict[str, int]], log, LOGGER_INDENT: int = 8):
    """
    Print summary statistics for subsystems
    :param subsys_stats: Statistics from calc_subsys_stats
    :param log: Logger object
    :param LOGGER_INDENT: Indentation for formatting
    """
    table_data = [("Category", "Total Cases", "Executed", "Completion", "Passed", "Pass Rate"),
                  ("-" * 10, "-" * 11, "-" * 8, "-" * 10, "-" * 6, "-" * 9)]

    for category, stats in category_stats.items():
        total = stats["total"]
        executed = stats["executed"]
        passed = stats["passed"]

        completion_rate = f"{(executed / total) * 100:.1f}%" if total > 0 else "N/A"
        pass_rate = f"{(passed / executed) * 100:.1f}%" if executed > 0 else "N/A"

        table_data.append((category, str(total), str(executed), completion_rate, str(passed), pass_rate))

    columns = list(zip(*table_data))
    column_widths = [max(len(cell) for cell in col) for col in columns]
    formatter = " " * LOGGER_INDENT + "  ".join([f"{{:{cw}s}}" for cw in column_widths])

    log.summary("\n===== Category Test Statistics =====")
    for row in table_data:
        log.summary(formatter.format(*row))
    log.summary("=====================================\n")
