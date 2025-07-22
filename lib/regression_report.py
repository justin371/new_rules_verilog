#!/usr/bin/env python
"""Report regression result in HTML."""

# standard lib imports
import getpass
import os
import re
import sys
import subprocess
import shutil
from datetime import datetime, timedelta

# Bigger libraries
import json
import jinja2


class RegressionReport():
    """
    All html update&create here
    """

    def __init__(self, rcfg, template_env, webroot_dir):
        self.rcfg = rcfg
        self.env = template_env  # template loader
        self.webroot_dir = webroot_dir

        # common path
        self.output_path = os.path.join(self.webroot_dir, "regression_report")
        self.project_info_path = self.output_path + '/' + 'project_info.json'

        # template filep load
        self.env.filters['zip'] = zip
        self.HOME_TEMPLATE = self.env.get_template("regression_report_templates/home_template.html.j2")
        self.BENCHS_TEMPLATE = self.env.get_template("regression_report_templates/benchs_template.html.j2")
        self.REGRESSION_REPORT_TEMPLATE = self.env.get_template('regression_report_templates/regression_report_template.html.j2')
        self.LOGS_TEMPLATE = self.env.get_template('regression_report_templates/logs_template.html.j2')

        # result info
        self.header = {}
        self.trd = {}
        self.cov = {}
        self.proj_name = ""
        self.project_info = {}

    def process_trd(self, trd):
        """
        Process test result data
        """
        # Tuple2List : for process data
        trdl = [list(item) for item in trd]
        # 1.1 logs match test, delete log entry
        # 1.2 calc pass rate
        last_job_index = 0
        for i, entry in enumerate(trdl):
            if entry[3] and entry[6]: # calc pass rate
                entry.insert(-2, f"{int(entry[3]) / int(entry[6]) * 100:.2f}")
            else:
                entry.insert(-2, "0.00")
            if entry[1]: # record last job
                last_job_index = i
            if entry[-2]:
                trdl[last_job_index][-2] += entry[-2] + '|'
        trdl = [list(item) for item in trdl if item[1]]
        # 1.3 list2dict
        # 1.4 dict.keys()
        current_value = []
        current_key = None
        for entry in trdl:
            entry[-2] = entry[-2].rstrip('|')
            if entry[0] != "":
                if current_value:
                    self.trd[current_key] = current_value
                current_key = entry[0]
                current_value = []
            current_value.append(entry)
        if current_value:
            self.trd[current_key] = current_value
        self.bench_list = list(self.trd.keys())
        # 1.5 add total summary
        for b, t in self.trd.items():
            passed = sum([int(entry[3]) for entry in t if entry[3] != ""])
            skipped = sum([int(entry[4]) for entry in t if entry[4] != ""])
            failed = sum([int(entry[5]) for entry in t if entry[5] != ""])
            passed -= 1 # skip compile
            total = passed + skipped + failed
            self.trd[b].append(["Total", "", "",
                                "" if passed == 0 else str(passed), "" if skipped == 0 else str(skipped),
                                "" if failed == 0 else str(failed), "" if total == 0 else str(total),
                                f"{passed / total * 100:.2f}", "", ""])

    def update_past_report_page(self, phtml, rlist, prlist, q1_prlist, cclist, cflist, ori_rlist, ori_prlist, ori_q1_prlist):
        """
        Update 'Past Result' part of regression report page
        """

        # Reverser for date order
        rlist.reverse()
        prlist.reverse()
        q1_prlist.reverse()
        cclist.reverse()
        cflist.reverse()

        if len(rlist) > 0:
            # new page index
            page_info = [f'                  <li><a href="{r}.html">{r}_{pr}%_{cc}_{cf}</a></li>\n' for r, pr, cc, cf in zip(rlist, prlist, cclist, cflist)]
            chart_info = [f'      const labels = {ori_rlist};\n      const data0 = {ori_prlist}\n      const data1 = {ori_q1_prlist}\n']

            for pr in rlist:
                start_index_0 = None
                end_index_0 = None
                start_index_1 = None
                end_index_1 = None
                with open(phtml + '/' + pr + '.html', 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                for i, line in enumerate(lines):
                    if line.strip() == "<!-- update past result -->":
                        if start_index_0 is None:
                            start_index_0 = i
                        else:
                            end_index_0 = i
                    if line.strip() == "<!-- update chart -->":
                        if start_index_1 is None:
                            start_index_1 = i
                        else:
                            end_index_1 = i
                            break
                # new lines
                updated_lines = (
                    lines[:start_index_0 + 1] +  # before past result comment
                    page_info +                # new lines
                    lines[end_index_0:start_index_1 + 1] + # after past result comment
                    chart_info +               # new lines
                    lines[end_index_1:]        # after chart comment
                )
                # write back to html
                with open(phtml + '/' + pr + '.html', 'w', encoding='utf-8') as file:
                    file.writelines(updated_lines)

    def run(self, header, trd, cov):
        """
        API for simmer to create report page
        """
        self.header = header
        self.cov = cov
        self.process_trd(trd)
        self.proj_name = self.header["project_name"]
        # Create html
        self.render_home_page()
        self.render_bench_page()
        self.render_regression_page()

    def render_home_page(self):
        """
        Render home.html
        param : project
        """
        html_file_path = self.output_path + '/' + 'index.html'

        # Makesure project exist
        # Update project info to json
        os.makedirs(self.output_path, exist_ok=True)
        if not os.path.exists(self.project_info_path):
            self.project_info[self.proj_name] = []
        else:
            with open(self.project_info_path, 'r', encoding='utf-8') as f:
                self.project_info = json.load(f)
            if self.proj_name not in self.project_info.keys():
                self.project_info[self.proj_name] = []
        #with open(self.project_info_path, 'w', encoding='utf-8') as f:
        #    json.dump(self.project_info, f, ensure_ascii=False, indent=4)

        # Render
        rendered_html = self.HOME_TEMPLATE.render(
            project=self.project_info,
        )
        
        # Write html
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(rendered_html)

    def render_bench_page(self):
        """
        Render bench_name.html
        param : project_name
        param : benchs
        """
        project_path = os.path.join(self.output_path, self.proj_name)
        html_file_path = project_path + '/' + 'index.html'

        # Makesure benchs exist
        # Update benchs info
        os.makedirs(project_path, exist_ok=True)
        for b in self.bench_list:
            os.makedirs(project_path + '/' + b, exist_ok=True)
            if b not in self.project_info[self.proj_name]:
                self.project_info[self.proj_name].append(b)
        with open(self.project_info_path, 'w', encoding='utf-8') as f:
            json.dump(self.project_info, f, ensure_ascii=False, indent=4)

        # Render
        rendered_html = self.BENCHS_TEMPLATE.render(
            project_name=self.header["project_name"],
            project=self.project_info,
        )
        
        # Write html
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(rendered_html)

    def render_regression_page(self):
        """
        Render regression result page
        param : header
        param : bench_name
        param : regression_details
        """
        # Split multi benchs
        for (b, t), (_, c) in zip(self.trd.items(), self.cov.items()):
            bench_path = os.path.join(self.output_path, self.header["project_name"], b)
            html_file_path = bench_path + '/' + 'index.html'
            json_file_path = bench_path + '/' + 'regressions.json'
            logs_path = bench_path + '/logs'
            regressions = {}
            regression_summary = {}
            logs_list = []
            passed = 0
            total = 0

            # Makesure logs dir exist
            os.makedirs(logs_path, exist_ok=True)

            # Bakeup failed logs
            for l in t[1:-1]: # skip compile info
                if l[3] == '':
                    passed += 0
                else:
                    passed += int(l[3])
                total += int(l[6])
                logs = l[-2].split('|')
                if any(item for item in logs if item.strip()): # logs html
                    rendered_html = self.LOGS_TEMPLATE.render(
                        project_name=self.header['project_name'],
                        bench_name=b,
                        logs=[f"{os.path.basename(os.path.dirname(log))}.log" for log in logs if log],
                    )
                    logs_html = '{}_{}'.format(l[1], self.header['time'])
                    with open(logs_path + '/' + logs_html, 'w', encoding='utf-8') as f:
                        f.write(rendered_html)
                    l.append(logs_html)
                else:
                    l.append("")
                for log in logs:
                    if log:
                        shutil.copy2(log, f"{logs_path}/{os.path.basename(os.path.dirname(log))}.log")
                logs = [f"{logs_path}/{os.path.basename(os.path.dirname(log))}.log" for log in logs if log]
                if logs != None:
                    logs_list.append(logs)
            t[0].append("")
            t[-1].append("")
            #self.rcfg.log.info(t)
            regression_summary['logs'] = logs_list
            regression_summary['passrate'] = round((passed / total) * 100, 2)
            if c != {}:
                regression_summary['cov_code'] = c['cc']['Overall']
                regression_summary['cov_func'] = c['cf']['Overall']
            else:
                regression_summary['cov_code'] = 0
                regression_summary['cov_func'] = 0

            # Create Q1 case pass rate
            q1_regr = {}
            q1_total = 0
            q1_pass = 0
            q1_passrate = 0.0
            for l in t[1:]:
                if l[-2] == "Q1":
                    if l[3] == '':
                        q1_pass += 0
                    else:
                        q1_pass += int(l[3])
                    q1_total += int(l[6])
            if q1_total == 0:
                q1_passrate = 0
            else:
                q1_passrate = round((q1_pass / q1_total) * 100, 2)
            q1_regr["Total_Q1"] = q1_total
            q1_regr["Pass_Q1"] = q1_pass
            q1_regr["Passrate_Q1"] = q1_passrate
            regression_summary['q1_passrate'] = q1_passrate

            # Record and update regressions info
            if not os.path.exists(json_file_path):
                regressions[self.header['time']] = regression_summary
            else:
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    regressions = json.load(f)
                if self.header['time'] not in regressions.keys():
                    regressions[self.header['time']] = regression_summary

            # Only remain 30days regression info
            regression_list = regressions.keys()
            sorted_list = sorted(regression_list, key=lambda ts: datetime.strptime(ts.split("_")[0], "%Y%m%d"))
            if len(sorted_list) > 30:
                remain_list.sorted_list[-30:]
                removed_list = [ts for ts in regression_list if ts not in remain_list]
                for removed_key in removed_list:
                    if removed_key in regressions:
                        log_files = regressions[removed_key]['logs']
                        for log_file in log_files:
                            for log in log_file:
                                if os.path.exists(log):  # files exist
                                    os.remove(log)  # delete files
                        # Update regressions
                        del regressions[removed_key]
            else:
                remain_list = sorted_list

            # Process regressions summary for chart
            passrate_list = [regressions[ts]['passrate'] for ts in remain_list if ts in regressions.keys()]
            cov_code_list = [regressions[ts]['cov_func'] for ts in remain_list if ts in regressions.keys()]
            cov_func_list = [regressions[ts]['cov_func'] for ts in remain_list if ts in regressions.keys()]
            q1_passrate_list = [regressions[ts]['q1_passrate'] for ts in remain_list if ts in regressions.keys()]

            # Update old regression report page
            self.update_past_report_page(bench_path, 
                                        remain_list[:-1], passrate_list[:-1], q1_passrate_list[:-1], cov_code_list[:-1], cov_func_list[:-1],
                                        remain_list, passrate_list, q1_passrate_list) 

            # Render
            rendered_html = self.REGRESSION_REPORT_TEMPLATE.render(
                header=self.header,
                bench_name=b,
                regression_details=t,
                regressions=remain_list,
                q1_regression_details=q1_regr,
                passrate_list=passrate_list,
                q1_passrate_list=q1_passrate_list,
                cov_code_list=cov_code_list,
                cov_func_list=cov_func_list,
                project=self.project_info,
                cc_info=c['cc'] if c != {} else {},
                cf_info=c['cf'] if c != {} else {},
            )

            # Write html
            with open(html_file_path, 'w', encoding='utf-8') as f:
                f.write(rendered_html)
            # Bakeup html
            shutil.copy2(html_file_path, bench_path + '/' + '{}.html'.format(self.header["time"]))

            # Update regressions json
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(regressions, f, ensure_ascii=False, indent=4)
