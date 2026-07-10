#!/usr/bin/env python
"""Utility class definitions for regression testing."""

import datetime
import getpass
import os
import re
import json
import shlex
import jinja2
import shutil
import subprocess
from typing import Dict, Optional, List
from bs4 import BeautifulSoup
from tempfile import TemporaryFile

LOGGER_INDENT = 8
SIMRESULTS = os.environ.get('SIMRESULTS', '')


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
        self.target = target  # Total number of iterations to spawn
        self.spawn_count = 1  # Current count of spawned iterations
        self.jobs = []  # List of jobs associated with this iteration config
        self.vso_assignments = []  # Optional VSO ask-all planned runs for this test template

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

    current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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
    total_tests = sum([icfg.target for _, (icfgs, _) in rcfg.all_vcomp.items() for icfg in icfgs])
    if total_tests > 1:
        if not rcfg.options.no_run:
            REGRESSION_LOG_PATH = create_regression_log_file(rcfg)
    else:
        if rcfg.options.report:
            current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            rcfg.current_time = current_time

    table_data = [("bench", "test", "max_job_time", "passed", "skipped", "failed", "total", "logs")]
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
            '1' if vcomp.jobstatus == vcomp.jobstatus.SKIPPED else '', '1' if not vcomp.jobstatus.successful else '', '1',
            '' if vcomp.jobstatus.successful else str(vcomp.log_path))
        table_data.append(tb_set)
        trd.append(tb_set)
        total += 1

        if vcomp.jobstatus == vcomp.jobstatus.PASSED:
            total_passed += 1
        elif vcomp.jobstatus == vcomp.jobstatus.FAILED:
            total_failed += 1
        else:
            total_skipped += 1

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

            test_set = ("", icfg.jobs[0].name, str(max_job_time), str(len(passed)) if passed else "", str(len(skipped)) if skipped else "",
                str(len(failed)) if failed else "", str(len(icfg.jobs)), "")
            table_data.append(test_set)
            trd.append(test_set)

            for j in failed:
                table_data.append(("", "", "", "", "", "", "", j.log_path if j.log_path else ''))
                trd.append(("", "", "", "", "", "", "", j.log_path if j.log_path else ''))
            if rcfg.options.nt:
                for j in passed:
                    table_data.append(("", "", "", "", "", "", "", j.log_path if j.log_path else ''))
                    trd.append(("", "", "", "", "", "", "", j.log_path if j.log_path else ''))
        
        if i != last:
            table_data.append(separator)

    trdl = [list(entry) for entry in trd]
    for i, entry in enumerate(trdl):
        if i != 0:
            current_test = entry[1]
            matched = False
            for key in rcfg.tests_to_tags:
                if ":" in key:
                    test_name = key.split(":", 1)[1]
                    if test_name == current_test:
                        if any(tag.lower() == "q1" for tag in rcfg.tests_to_tags[key]):
                            entry.append("Q1")
                        else:
                            entry.append("")
                        matched = True
                        break
            if not matched:
                entry.append("")
        else:
            entry.append("")
    trd.clear()
    trd.extend([tuple(entry) for entry in trdl])

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
        with open(REGRESSION_LOG_PATH, 'a') as file:
            formatted_string = "Job Results\n" + "\n".join(map(str, table_data_formatted))
            file.write(formatted_string)

    table_data = [("", "", "", "passed", "skipped", "failed", "total", "")]
    table_data.append(['-' * len(i) for i in table_data[0]])
    table_data.append(("", "", "", str(total_passed), str(total_skipped), str(total_failed), str(total), ""))
    table_data_formatted = [formatter.format(*i) for i in table_data]
    rcfg.log.summary("Simulation Summary\n%s", "\n".join(table_data_formatted))
    
    if total_tests > 1 and not rcfg.options.no_run:
        with open(REGRESSION_LOG_PATH, 'a') as file:
            formatted_string = "\n" + "Simulation Summary\n" + "\n".join(map(str, table_data_formatted))
            file.write(formatted_string)


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

    sim_results_home = os.path.join(SIMRESULTS, username)
    if not os.path.exists(sim_results_home):
        os.mkdir(sim_results_home)

    try:
        checkout_path = re.search(r'{}/(.*)'.format(username), checkout_path).group(1)
    except AttributeError:
        pass
    checkout_path = checkout_path.replace('/', '_')
    regression_directory = checkout_path
    regression_directory = os.path.join(sim_results_home, regression_directory)
    return regression_directory


def get_report_header(rcfg):
    """
    Get header information for regression report
    :param rcfg: Regression configuration object
    :return: Dictionary containing report header information
    """
    header = {}

    header['username'] = getpass.getuser()
    header['simulator'] = getattr(rcfg, 'simulator', rcfg.options.simulator)
    header['time'] = rcfg.current_time
    try:
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], text=True).strip()
        tag_info = subprocess.check_output(['git', 'describe', '--tags'], text=True).strip()
        commit_id = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        short_revision = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], text=True).strip()
        repo_url = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip().replace(":", "/").replace("git@", "https://")
        match = re.search(r"/([^/]+)\.git$", repo_url)
        if match:
            header['project_name'] = match.group(1)
        else:
            print("Error: Invalid Git URL format or .git suffix missing.")                
        header["branch"] = branch
        header['tag'] = tag_info
        header["revision"] = short_revision
        header["commit"] = repo_url.rstrip(".git") + "/commit/" + commit_id
    except subprocess.CalledProcessError as e:
        print("Error: Not a Git repository or Git command failed.")
        return None
    return header


def process_value(value):
    """
    Process coverage values to remove extra percentage symbols
    :param value: Coverage value string
    :return: Processed value string
    """
    if '%' in value:
        return value.split('%')[0] + '%'
    return value


def get_coverage_data(rcfg, vcomp_jobs):
    """
    Collect coverage data from regression results
    :param rcfg: Regression configuration object
    :param vcomp_jobs: Dictionary of vcomponent jobs
    :return: Dictionary containing coverage data
    """
    cov = {}

    include = 'summ'
    dut_pattern = 'hdl_top</A>.dut'
    env_pattern = 'uvm_pkg</A>.uvm_test_top'

    for vcomp, job in vcomp_jobs.items():
        vcomp_name = vcomp.split(":")[-1]
        cov[vcomp_name] = {}
        if rcfg.options.coverage:
            report_dir = os.path.join(job.cov_work_dir, "imc_report")
            cmd = 'runmod xrun -- imc -exec {} -verbose'.format(os.path.join(job.cov_work_dir, "imc_report.tcl"))
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            p.wait()
            if p.returncode != 0:
                stderr = p.stderr.read().decode('utf-8', errors='ignore')
                rcfg.log.error("IMC report generation failed:\n%s", stderr)
                continue

            result = subprocess.run(['grep', '-rl', dut_pattern, report_dir], capture_output=True, text=True)
            grep_files = result.stdout.splitlines()
            dut_file = [f for f in grep_files if include in f]
            if len(dut_file) != 1:
                rcfg.log.error("Error: Dut coverage file not found")
            else:
                dut_file = dut_file[0]
                with open(dut_file, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                    table = soup.find('table', id='totalTable')
                    if table:
                        rows = table.find_all('tr')
                        if len(rows) >= 2:
                            header = [th.get_text(strip=True).replace('\u00a0', '') for th in rows[0].find_all('th')]
                            for row in rows[1:]:
                                cells = [td.get_text(strip=True).replace('\u00a0', '') for td in row.find_all('td')]
                                if 'Cumulative' in cells:
                                    cov[vcomp_name]['cc'] =  dict(zip(header, cells))
        
            result = subprocess.run(['grep', '-rl', env_pattern, report_dir], capture_output=True, text=True)
            grep_files = result.stdout.splitlines()
            env_file = [f for f in grep_files if include in f]
            if len(env_file) != 1:
                rcfg.log.error("Error: Function coverage file not found")
            else:
                env_file = env_file[0]
                with open(env_file, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                    table = soup.find('table', id='totalTable')
                    if table:
                        rows = table.find_all('tr')
                        if len(rows) >= 2:
                            header = [th.get_text(strip=True).replace('\u00a0', '') for th in rows[0].find_all('th')]
                            for row in rows[1:]:
                                cells = [td.get_text(strip=True).replace('\u00a0', '') for td in row.find_all('td')]
                                if 'Cumulative' in cells:
                                    cov[vcomp_name]['cf'] =  dict(zip(header, cells))

            cc_filtered = {
                k.split(' ')[0]: process_value(v)
                for k, v in cov[vcomp_name].get('cc', {}).items()
                if 'Average' in k and 'CoverGroup' not in k
            }
            cf_filtered = {
                k.split(' ')[0]: process_value(v)
                for k, v in cov[vcomp_name].get('cf', {}).items()
                if k in ['Overall Average', 'Assertion Average', 'CoverGroup Average']
            }
            cov[vcomp_name]['cc'] = cc_filtered
            cov[vcomp_name]['cf'] = cf_filtered

            shutil.rmtree(report_dir, ignore_errors=True)

    return cov


def load_category_total_cases(cfg_path: Optional[str] = None) -> Dict[str, Dict]:
    """
    Load subsystem configuration including total cases and associated tags
    Format: {subsystem_name: {"total": int, "tags": [tag1, tag2, ...]}}
    :param cfg_path: Path to JSON config file (optional)
    :return: Subsystem configuration dictionary
    """
    default_cfg = {
        "ci_gate": {
            "total": 50,
            "tags": ["ci_gate", "ci"]
        },
        "nightly": {
            "total": 200,
            "tags": ["nightly", "nl"]
        },
        "weekly": {
            "total": 20,
            "tags": ["weekly", "wl"]
        }
    }

    if cfg_path and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: Invalid JSON in subsystem config {cfg_path}, using default")
            return default_cfg
    return default_cfg


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
            "test_records": set()  # Track unique tests to avoid duplicate counting
        } for category, config in rcfg.category_total_cases.items()
    }

    if rcfg.options.no_run:
        # Remove internal tracking field before returning
        for stats in category_stats.values():
            del stats["test_records"]
        return category_stats

    # Process all test iterations and aggregate results
    for _, (icfgs, _) in rcfg.all_vcomp.items():
        for icfg in icfgs:
            # Map: test base name → {tags, all_iteration_statuses}
            test_aggregator = {}

            # Step 1: Collect all iterations for each test
            for job in icfg.jobs:
                # Extract base test name (remove iteration suffix like "_1", "_2")
                test_full_name = job.name
                test_base_name = re.sub(r'_\d+$', '', test_full_name)

                # Get tags associated with this test —— FIXED: EXACT MATCH
                test_tags = set()
                for test_key, tags in rcfg.tests_to_tags.items():
                    if ':' in test_key:
                        key_test_name = test_key.split(':', 1)[1]  # Only split on first ':'
                        if key_test_name == test_base_name:
                            test_tags = set(tags)
                            break  # Exact match found

                if not test_tags:
                    continue  # Skip tests with no tags

                # Initialize entry if not exists
                if test_base_name not in test_aggregator:
                    test_aggregator[test_base_name] = {
                        "tags": test_tags,
                        "iterations_successful": []  # Track success status of each iteration
                    }

                # Record success status of current iteration
                is_successful = job.jobstatus.successful if job.jobstatus else False
                test_aggregator[test_base_name]["iterations_successful"].append(is_successful)

            # Step 2: Deduplicate and calculate stats (strict mode)
            for test_name, test_data in test_aggregator.items():
                test_tags = test_data["tags"]
                all_iterations = test_data["iterations_successful"]

                # Check each category for tag matches
                for category, stats in category_stats.items():
                    category_tags = set(rcfg.category_total_cases[category]["tags"])
                    if not (test_tags & category_tags):
                        continue  # No tag overlap, skip

                    # Count as executed only once per unique test
                    if test_name not in stats["test_records"]:
                        stats["test_records"].add(test_name)
                        stats["executed"] += 1  # 1 execution regardless of iteration count

                        # Strict mode: Passed only if ALL iterations are successful
                        if all(all_iterations):
                            stats["passed"] += 1

    # Clean up internal tracking field
    for stats in category_stats.values():
        del stats["test_records"]

    return category_stats


def print_category_summary(
    category_stats: Dict[str, Dict[str, int]],
    log,
    LOGGER_INDENT: int = 8
):
    """
    Print summary statistics for subsystems
    :param subsys_stats: Statistics from calc_subsys_stats
    :param log: Logger object
    :param LOGGER_INDENT: Indentation for formatting
    """
    table_data = [
        ("Category", "Total Cases", "Executed", "Completion", "Passed", "Pass Rate"),
        ("-" * 10, "-" * 11, "-" * 8, "-" * 10, "-" * 6, "-" * 9)
    ]

    for category, stats in category_stats.items():
        total = stats["total"]
        executed = stats["executed"]
        passed = stats["passed"]

        completion_rate = f"{(executed / total) * 100:.1f}%" if total > 0 else "N/A"
        pass_rate = f"{(passed / executed) * 100:.1f}%" if executed > 0 else "N/A"

        table_data.append((
            category,
            str(total),
            str(executed),
            completion_rate,
            str(passed),
            pass_rate
        ))

    columns = list(zip(*table_data))
    column_widths = [max(len(cell) for cell in col) for col in columns]
    formatter = " " * LOGGER_INDENT + "  ".join(
        [f"{{:{cw}s}}" for cw in column_widths]
    )

    log.summary("\n===== Category Test Statistics =====")
    for row in table_data:
        log.summary(formatter.format(*row))
    log.summary("=====================================\n")
