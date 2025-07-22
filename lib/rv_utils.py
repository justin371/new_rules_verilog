#!/usr/bin/env python
"""Utility class definitions."""

import datetime
import getpass
import os
import re
import jinja2
import subprocess
from bs4 import BeautifulSoup

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


def print_summary(rcfg, vcomp_jobs, icfgs, jm, trd):
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
            max_job_time = max(icfg.jobs, key=lambda x: x.job_time)._get_total_time_str()
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
            #if rcfg.options.nt:
            #    for j in passed or failed:
            #        table_data.append(("", "", "", "", "", j.log_path if j.log_path else ''))
            #else:
            #    for j in failed:
            #        table_data.append(("", "", "", "", "", j.log_path if j.log_path else ''))
        if i != last:
            table_data.append(separator)

    # add tags to trd
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
    # Check that entries are consistent
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
        checkout_path = re.search(r'{}/(.*)'.format(username), checkout_path).group(1)
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

def get_report_header(rcfg):
    """Get report header from regression"""
    header = {}

    # Header
    header['username'] = getpass.getuser()
    header['simulator'] = rcfg.options.simulator
    header['time'] = rcfg.current_time
    try:
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], text=True).strip()
        commit_id = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        short_revision = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], text=True).strip()
        repo_url = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip().replace(":", "/").replace("git@", "https://")
        match = re.search(r"/([^/]+)\.git$", repo_url)
        if match:
            header['project_name'] = match.group(1)
        else:
            print("Error: Invalid Git URL format or .git suffix missing.")
        header["branch"] = branch
        header["revision"] = short_revision
        header["commit"] = repo_url.rstrip(".git") + "/commit/" + commit_id
    except subprocess.CalledProcessError as e:
        print("Error: Not a Git repository or Git command failed.")
        return None
    return header

def process_value(value):
    if '%' in value:
        return value.split('%')[0] + '%'
    return value

def get_coverage_data(rcfg, vcomp_jobs):
    """Get coverage data from regression"""
    cov = {}

    # file info
    include = 'summ'
    dut_pattern = 'hdl_top</A>.dut'
    env_pattern = 'uvm_pkg</A>.uvm_test_top'

    # IMC report(html)
    for vcomp, job in vcomp_jobs.items():
        vcomp_name = vcomp.split(":")[-1]
        cov[vcomp_name] = {}
        if rcfg.options.coverage:
            report_dir = os.path.join(job.cov_work_dir, "imc_report")
            # Generate IMC report dir
            cmd = 'runmod xrun -- imc -exec {} -verbose'.format(os.path.join(job.cov_work_dir, "imc_report.tcl"))
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            p.wait()
            assert p.returncode == 0

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
                        if len(rows) >= 2:  # Must have at least 2 rows for header and data
                            header = [th.get_text(strip=True).replace('\u00a0', '') for th in rows[0].find_all('th')]
                            for row in rows[1:]:
                                cells = [td.get_text(strip=True).replace('\u00a0', '') for td in row.find_all('td')]
                                # Check if the last cell in the row contains 'Cumulative'
                                if 'Cumulative' in cells:
                                    cov[vcomp_name]['cc'] =  dict(zip(header, cells))  # Return dictionary for the Cumulative row
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
                        if len(rows) >= 2:  # Must have at least 2 rows for header and data
                            header = [th.get_text(strip=True).replace('\u00a0', '') for th in rows[0].find_all('th')]
                            for row in rows[1:]:
                                cells = [td.get_text(strip=True).replace('\u00a0', '') for td in row.find_all('td')]
                                # Check if the last cell in the row contains 'Cumulative'
                                if 'Cumulative' in cells:
                                    cov[vcomp_name]['cf'] =  dict(zip(header, cells))  # Return dictionary for the Cumulative row

            cc_filtered = {
                k.split(' ')[0]: process_value(v)
                for k, v in cov[vcomp_name]['cc'].items()
                if 'Average' in k and 'CoverGroup' not in k
            }
            cf_filtered = {
                k.split(' ')[0]: process_value(v)
                for k, v in cov[vcomp_name]['cf'].items()
                if k in ['Overall Average', 'Assertion Average', 'CoverGroup Average']
            }
            cov[vcomp_name]['cc'] = cc_filtered
            cov[vcomp_name]['cf'] = cf_filtered

            # Remove imc report dir
            subprocess.run(['rm', '-rf', report_dir])

    return cov
