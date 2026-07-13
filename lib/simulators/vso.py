"""VSO.ai CSO workflow support owned by the VCS backend."""

import csv
import json
import os
import re
import shlex
import subprocess


class VsoWorkflow:

    def __init__(self, options, rcfg):
        self.options = options
        self.rcfg = rcfg

    def artifact_dir(self):
        path = os.path.join(self.rcfg.regression_dir, "vso_artifacts")
        os.makedirs(path, exist_ok=True)
        return path

    def _project_path(self, value):
        return os.path.abspath(os.path.join(self.rcfg.proj_dir, value))

    def workdir(self):
        if self.options.vso_workdir is not None:
            return self._project_path(self.options.vso_workdir)
        return os.path.join(self.artifact_dir(), "workdir")

    def dbdir(self):
        if self.options.vso_dbdir is not None:
            return self._project_path(self.options.vso_dbdir)
        return os.path.join(self.artifact_dir(), "dbdir")

    def driver_path(self):
        return os.path.join(os.environ["VSO_HOME"], "bin", "driver")

    def build_name(self, vcomp_job):
        return self.options.vso_buildname or vcomp_job.name

    def target_metric(self):
        if self.options.vso_target_metric is not None:
            return self.options.vso_target_metric
        if self.options.cm == "A":
            return "all"
        return ",".join(metric for metric in ("assert", "cond", "fsm", "line", "tgl")
                        if metric in self.options.cm.split("+"))

    def _templates(self, all_vcomp):
        for _, (iteration_cfgs, tests) in all_vcomp.items():
            yield from zip(iteration_cfgs, tests)

    def write_regression_config(self, all_vcomp):
        path = os.path.join(self.artifact_dir(), "vso_regr_config.yaml")
        config_name = os.path.basename(self.rcfg.proj_dir.rstrip(os.sep)) or "rules_verilog"
        builds = []
        seen_builds = set()
        for _, test in self._templates(all_vcomp):
            build_name = self.build_name(test.vcomper)
            if build_name not in seen_builds:
                seen_builds.add(build_name)
                builds.append(build_name)

        with open(path, "w", encoding="utf-8") as filep:
            filep.write("config_name: {}\n".format(json.dumps(config_name)))
            filep.write("builds:\n")
            for build_name in builds:
                filep.write("  - name: {}\n".format(json.dumps(build_name)))
            filep.write("tests:\n")
            for iteration_cfg, test in self._templates(all_vcomp):
                filep.write("  - name: {}\n".format(json.dumps(test.target)))
                filep.write("    build: {}\n".format(json.dumps(self.build_name(test.vcomper))))
                filep.write("    count: {}\n".format(iteration_cfg.target))
        return path

    def write_simv_path_list(self, vcomp_jobs):
        path = os.path.join(self.artifact_dir(), "vso_simv_path_list.txt")
        with open(path, "w", encoding="utf-8") as filep:
            for vcomp_job in vcomp_jobs.values():
                filep.write(os.path.join(vcomp_job.job_dir, "simv") + "\n")
        return path

    def build_init_command(self, all_vcomp, vcomp_jobs):
        os.makedirs(self.workdir(), exist_ok=True)
        os.makedirs(self.dbdir(), exist_ok=True)
        args = [
            "--init",
            "--dbdir",
            self.dbdir(),
            "--workdir",
            self.workdir(),
            "--regr_config",
            self.write_regression_config(all_vcomp),
            "--target_metric",
            self.target_metric(),
            "--simv_path_list",
            self.write_simv_path_list(vcomp_jobs),
        ]
        for phase in self.options.vso_phase or []:
            args.extend(["--phase", phase])
        return args, os.path.join(self.artifact_dir(), "vso_init.log")

    def build_ask_command(self):
        return ["--ask", "all", "--workdir", self.workdir(), "--fmt",
                "csv"], os.path.join(self.artifact_dir(), "vso_ask.log")

    def _parse_ask_record(self, line):
        if "CSO_RESULT:" not in line:
            return None
        record = {}
        for token in shlex.split(line.split("CSO_RESULT:", 1)[1]):
            if "=" in token:
                key, value = token.split("=", 1)
                record[key] = value
        required = {"BUILD", "TEST", "RUN_ID"}
        if not required.issubset(record):
            raise RuntimeError("Malformed VSO.ai ask record: {!r}".format(line.rstrip()))
        return record

    def apply_ask_results(self, all_vcomp, log_path):
        templates = {}
        for iteration_cfg, test in self._templates(all_vcomp):
            iteration_cfg.backend_assignments = []
            templates[(self.build_name(test.vcomper), test.target)] = (iteration_cfg, test)

        planned_runs = 0
        with open(log_path, "r", encoding="utf-8", errors="ignore") as filep:
            for line in filep:
                record = self._parse_ask_record(line)
                if record is None:
                    continue
                key = (record["BUILD"], record["TEST"])
                if key not in templates:
                    raise RuntimeError("VSO.ai ask returned unknown build/test pair {}.".format(key))
                templates[key][0].backend_assignments.append({
                    "run_id": record["RUN_ID"],
                    "seed": record.get("SEED") or None,
                })
                planned_runs += 1

        selected_tests = []
        for iteration_cfg, test in self._templates(all_vcomp):
            iteration_cfg.target = len(iteration_cfg.backend_assignments)
            if iteration_cfg.target:
                selected_tests.append(test)
            else:
                test.jobstatus = test.jobstatus.SKIPPED
        return {"selected_tests": selected_tests, "planned_runs": planned_runs}

    def prepare_test(self, test_job):
        if not test_job.icfg.backend_assignments:
            raise RuntimeError("No VSO.ai assignment available for {}".format(test_job.target))
        assignment = test_job.icfg.backend_assignments.pop(0)
        test_job.vso_run_id = assignment["run_id"]
        if assignment["seed"] is None:
            return None
        try:
            return int(str(assignment["seed"]), 0)
        except ValueError as exc:
            raise RuntimeError("VSO.ai returned a non-integer seed {!r} for {}.".format(
                assignment["seed"], test_job.target)) from exc

    def sim_options(self, test_job):
        return [
            "-vso",
            "cso",
            "-vso_opts",
            "workdir={}".format(self.workdir()),
            "-vso_opts",
            "run_id={}".format(test_job.vso_run_id),
        ]

    def failure_signature(self, test_job):
        for line in (getattr(test_job, "error_message", None) or "").splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            if normalized:
                return normalized[:240]
        return "FAILED"

    def _run_driver(self, args, log_path, step_name):
        command = [self.driver_path()] + args
        with open(log_path, "w", encoding="utf-8") as filep:
            filep.write("Command: {}\n\n".format(shlex.join(command)))
            result = subprocess.run(
                command,
                cwd=self.rcfg.regression_dir,
                stdout=filep,
                stderr=subprocess.STDOUT,
                check=False,
                text=True,
            )
        if result.returncode:
            raise RuntimeError("VSO.ai {} failed with return code {}. See {}.".format(
                step_name, result.returncode, log_path))

    def _write_failures(self, all_vcomp):
        path = os.path.join(self.artifact_dir(), "vso_fails.csv")
        count = 0
        with open(path, "w", encoding="utf-8", newline="") as filep:
            writer = csv.writer(filep)
            for iteration_cfg, test in self._templates(all_vcomp):
                for job in iteration_cfg.jobs:
                    if job.jobstatus.name not in ("PASSED", "FAILED"):
                        continue
                    failed = job.jobstatus.name == "FAILED"
                    writer.writerow([
                        test.target,
                        self.build_name(test.vcomper),
                        "fail" if failed else "pass",
                        self.failure_signature(job) if failed else "",
                    ])
                    count += 1
        return path, count

    def finalize_merge(self, all_vcomp):
        args = ["--finalize", "--merge", "--workdir", self.workdir(), "--dbdir", self.dbdir()]
        failures, count = self._write_failures(all_vcomp)
        if count:
            args.extend(["--update_fails", failures])
        log_path = os.path.join(self.artifact_dir(), "vso_finalize_merge.log")
        self._run_driver(args, log_path, "finalize/merge")
        self.rcfg.deferred_messages.append("VSO.ai finalize/merge log: {}".format(log_path))
