#!/usr/bin/env python
"""Utility class definitions."""

import datetime
import getpass
import os
import re

# I'd rather create a "plain" message in the logger
# that doesn't format, but more work than its worth
LOGGER_INDENT = 8
SIMRESULTS = os.environ.get('SIMRESULTS', '')


class DatetimePrinter():

    def __init__(self, log):
        self.ts = datetime.datetime.now()
        self.log = log

    def reset(self):
        self.ts = datetime.datetime.now()

    def stop_and_print(self):
        stop = datetime.datetime.now()
        delta = stop - self.ts
        self.log.debug("Last time check: %d", delta.total_seconds())


class IterationCfg():

    def __init__(self, target):
        self.target = target
        self.spawn_count = 1
        self.jobs = []

    def inc(self, job):
        self.spawn_count += 1
        self.jobs.append(job)

    def __lt__(self, other):
        return self.jobs[0].name < other.jobs[0].name


def create_regression_log_file(rcfg):
    target_folder = os.path.join(rcfg.regression_dir, 'regression_results')

    if not os.path.exists(target_folder):
        os.makedirs(target_folder)
        print(f"Folder created at: {target_folder}")

    current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

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


def print_summary(rcfg, vcomp_jobs, icfgs, jm):
    total_tests = sum([icfg.target for _, (icfgs, _) in rcfg.all_vcomp.items() for icfg in icfgs])
    if total_tests > 1:
        if not rcfg.options.no_run:
            REGRESSION_LOG_PATH = create_regression_log_file(rcfg)

    table_data = [("bench", "test", "passed", "skipped", "failed", "logs")]
    separator = [""] * len(table_data[0])
    table_data.append(separator)

    total_passed = 0
    total_skipped = 0
    total_failed = 0

    last = len(rcfg.all_vcomp) - 1
    for i, (vcomp_name, (icfgs, test_list)) in enumerate(rcfg.all_vcomp.items()):
        vcomp = vcomp_jobs[vcomp_name]
        table_data.append(
            (vcomp.name, "vcomp", '1' if vcomp.jobstatus.successful else '',
             '1' if vcomp.jobstatus == vcomp.jobstatus.SKIPPED else '', '1' if not vcomp.jobstatus.successful else '',
             '' if vcomp.jobstatus.successful else str(vcomp.log_path)))
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
            passed = [j for j in icfg.jobs if j.jobstatus.completed and j.jobstatus.successful]
            failed = [j for j in icfg.jobs if j.jobstatus == j.jobstatus.FAILED]
            skipped = [j for j in icfg.jobs if j.jobstatus not in [j.jobstatus.FAILED, j.jobstatus.PASSED]]

            total_passed += len(passed)
            total_failed += len(failed)
            total_skipped += len(skipped)

            try:
                assert len(passed) + len(failed) + len(skipped) == len(icfg.jobs), print(
                    len(passed), len(failed), len(skipped), len(icfg.jobs))
            except AssertionError as exc:
                if not jm.exited_prematurely:
                    raise exc

            table_data.append(
                ("", icfg.jobs[0].name, str(len(passed)) if passed else "", str(len(skipped)) if skipped else "",
                 str(len(failed)) if failed else "", ""))
            if rcfg.options.nt:
                for j in passed or failed:
                    table_data.append(("", "", "", "", "", j.log_path if j.log_path else ''))
            else:
                for j in failed:
                    table_data.append(("", "", "", "", "", j.log_path if j.log_path else ''))
        if i != last:
            table_data.append(separator)

    # Check that entries are consistent
    assert all(len(i) == len(table_data[0]) for i in table_data)
    columns = list(zip(*table_data))
    column_widths = [max([len(cell) for cell in col]) for col in columns]
    formatter = " " * LOGGER_INDENT + "  ".join(
        ["{{:{}{}s}}".format('>' if i in [2, 3, 4] else '', c) for i, c in enumerate(column_widths)])
    for i, entry in enumerate(table_data):
        if entry == separator:
            table_data[i] = ['-' * cw for cw in column_widths]
    table_data_formatted = [formatter.format(*i) for i in table_data]
    rcfg.log.summary("Job Results\n%s", "\n".join(table_data_formatted))
    if total_tests > 1 and not rcfg.options.no_run:
        with open(REGRESSION_LOG_PATH, 'a') as file:
            formatted_string = "Job Results\n" + "\n".join(map(str, table_data_formatted))
            file.write(formatted_string)

    table_data = [("", "", "passed", "skipped", "failed", "")]
    table_data.append(['-' * len(i) for i in table_data[0]])
    table_data.append(("", "", str(total_passed), str(total_skipped), str(total_failed), ""))
    table_data_formatted = [formatter.format(*i) for i in table_data]
    rcfg.log.summary("Simulation Summary\n%s", "\n".join(table_data_formatted))
    if total_tests > 1 and not rcfg.options.no_run:
        with open(REGRESSION_LOG_PATH, 'a') as file:
            formatted_string = "\n" + "Simulation Summary\n" + "\n".join(map(str, table_data_formatted))
            file.write(formatted_string)


def calc_simresults_location(checkout_path):
    """Calculate the path to put regression results."""
    username = getpass.getuser()

    # FIXME, we may want to detect who owns the check to allow
    # for rerunning in someone else's area? # pylint: disable=fixme
    sim_results_home = os.path.join(SIMRESULTS, username)
    if not os.path.exists(sim_results_home):
        os.mkdir(sim_results_home)

    # If username is in the checkout_path try to reduce the name
    # Assume username is somewhere is path
    try:
        checkout_path = re.search(r"{}/(.*)".format(username), checkout_path).group(1)
    except AttributeError:
        pass
    checkout_path = checkout_path.replace('/', '_')
    # Adding the datetime into the regression directory will force a recompile.
    # Ideally, the vcomp directory will need to have the same name
    # strdate = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
    # regression_directory = '{}__{}'.format(checkout_path, strdate)
    regression_directory = checkout_path
    regression_directory = os.path.join(sim_results_home, regression_directory)
    return regression_directory
