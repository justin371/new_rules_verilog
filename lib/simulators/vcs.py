# lib/simulators/vcs.py
import os
import stat
import logging
import csv
import json
import re
import shlex
import subprocess

from .base import SimulatorInterface

log = logging.getLogger(__name__)


class VcsSimulator(SimulatorInterface):
    """Implementation for Synopsys VCS simulator."""

    VCS_XPROP_CONFIG_BY_MODE = {
        'F': ['vcs_fox_xprop.cfg', 'fox_xprop.cfg'],
        'C': ['vcs_cat_xprop.cfg', 'cat_xprop.cfg'],
    }

    VCS_XPROP_FALLBACK_BY_MODE = {
        'F': '-xprop=xmerge',
        'C': '-xprop=tmerge',
    }

    def get_name(self):
        return "vcs"

    def get_compile_template(self, vcomp_job):
        return self.env.get_template('vcs_compile_template.sh.j2')

    def get_sim_template(self):
        # Assuming a single sim_template works for now, driven by options
        return self.env.get_template('sim_template.sh.j2')

    def get_wave_cmd_template(self):
        return self.env.get_template('vcs_wave_cmd_template.tcl.j2')

    def get_tool_runner(self):
        return self.options.vcs_runner or os.environ.get("RV_VCS_RUNNER") or "runmod vcs --"

    def get_tool_command(self, tool_name):
        return "{} {}".format(self.get_tool_runner(), tool_name).strip()

    def use_smartlog(self):
        return self.options.smartlog or self.options.waves is not None or self.options.gui

    def get_wave_view_command(self, wave_file_path, job_dir=None):
        cmd = '{} -apex -lca -ssf "{}"'.format(self.get_tool_command("verdi"), wave_file_path)
        if job_dir is not None:
            smartlog_path = os.path.join(job_dir, "stdout.log")
            if os.path.exists(smartlog_path):
                cmd += ' -smlog "{}"'.format(smartlog_path)
        return cmd

    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args.f".format(bazel_target))

    def get_vcomp_job_dir(self, default_job_dir):
        return default_job_dir

    def get_bazel_runtime_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_runtime_args.f".format(bazel_target))

    def _get_vso_artifact_dir(self):
        artifact_dir = os.path.join(self.rcfg.regression_dir, "vso_artifacts")
        os.makedirs(artifact_dir, exist_ok=True)
        return artifact_dir

    def _get_vso_workdir(self):
        if self.options.vso_workdir is not None:
            return self.options.vso_workdir
        return os.path.join(self._get_vso_artifact_dir(), "workdir")

    def _get_vso_dbdir(self):
        if self.options.vso_dbdir is not None:
            return self.options.vso_dbdir
        return os.path.join(self._get_vso_artifact_dir(), "dbdir")

    def _get_vso_driver_path(self):
        vso_home = os.environ.get("VSO_HOME")
        if not vso_home:
            raise RuntimeError("VSO_HOME is not set. Please source the VSO/VCS environment before using --vso.")
        return os.path.join(vso_home, "bin", "driver")

    def get_vso_build_name(self, vcomp_job):
        if self.options.vso_buildname is not None:
            return self.options.vso_buildname
        return vcomp_job.name

    def get_vso_test_template_name(self, test_job):
        return test_job.target

    def get_vso_test_run_name(self, test_job):
        if test_job.test_name_seed:
            return test_job.test_name_seed
        return "{}__{}".format(test_job.name, test_job.iteration)

    def get_vso_target_metric(self):
        if self.options.vso_target_metric is not None:
            return self.options.vso_target_metric

        if not self.options.cm:
            raise ValueError("VSO.ai init requires coverage targeting information. "
                             "Please pass '--cm ...' or '--vso-target-metric ...'.")

        tokens = set(self.options.cm.split('+'))
        ordered_metrics = ['line', 'fsm', 'tgl', 'assert']
        if 'A' in tokens:
            return ",".join(ordered_metrics)

        metrics = [metric for metric in ordered_metrics if metric in tokens]
        if not metrics:
            raise ValueError("Could not derive a VSO.ai target metric from '--cm {}'. "
                             "Please pass '--vso-target-metric ...' explicitly.".format(self.options.cm))
        return ",".join(metrics)

    def _run_vso_driver(self, args, log_path, step_name):
        driver_path = self._get_vso_driver_path()
        with open(log_path, 'w', encoding='utf-8') as log_fp:
            log_fp.write("Command: {}\n\n".format(" ".join(shlex.quote(part) for part in [driver_path] + args)))
            result = subprocess.run(
                [driver_path] + args,
                cwd=self.rcfg.regression_dir,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                check=False,
                text=True,
            )
        if result.returncode != 0:
            raise RuntimeError("VSO.ai {} failed with return code {}. See {}.".format(
                step_name, result.returncode, log_path))

    def write_vso_regression_config(self, all_vcomp):
        config_path = os.path.join(self._get_vso_artifact_dir(), "vso_regr_config.yaml")
        config_name = os.path.basename(self.rcfg.proj_dir.rstrip(os.sep)) or "rules_verilog"
        written_builds = set()

        with open(config_path, 'w', encoding='utf-8') as filep:
            filep.write("config_name: {}\n".format(json.dumps(config_name)))
            filep.write("builds:\n")
            for _, (_, tests) in all_vcomp.items():
                if not tests:
                    continue
                build_name = self.get_vso_build_name(tests[0].vcomper)
                if build_name in written_builds:
                    continue
                written_builds.add(build_name)
                filep.write("  - name: {}\n".format(json.dumps(build_name)))

            filep.write("tests:\n")
            for _, (icfgs, tests) in all_vcomp.items():
                for icfg, test in zip(icfgs, tests):
                    filep.write("  - name: {}\n".format(json.dumps(self.get_vso_test_template_name(test))))
                    filep.write("    build: {}\n".format(json.dumps(self.get_vso_build_name(test.vcomper))))
                    filep.write("    count: {}\n".format(icfg.target))

        return config_path

    def write_vso_simv_path_list(self, vcomp_jobs):
        simv_path_list = os.path.join(self._get_vso_artifact_dir(), "vso_simv_path_list.txt")
        with open(simv_path_list, 'w', encoding='utf-8') as filep:
            for vcomp_job in vcomp_jobs.values():
                filep.write(os.path.join(vcomp_job.job_dir, "simv"))
                filep.write("\n")
        return simv_path_list

    def write_vso_fails_csv(self, all_vcomp):
        fails_csv_path = os.path.join(self._get_vso_artifact_dir(), "vso_fails.csv")
        row_count = 0
        with open(fails_csv_path, 'w', encoding='utf-8', newline='') as csv_fp:
            writer = csv.writer(csv_fp)
            for _, (icfgs, tests) in all_vcomp.items():
                for icfg, test in zip(icfgs, tests):
                    build_name = self.get_vso_build_name(test.vcomper)
                    for job in icfg.jobs:
                        job_status = job.jobstatus.name
                        if job_status not in ['PASSED', 'FAILED']:
                            continue
                        status = 'pass' if job_status == 'PASSED' else 'fail'
                        signature = '' if status == 'pass' else self.get_vso_failure_signature(job)
                        writer.writerow([
                            self.get_vso_test_template_name(job),
                            build_name,
                            status,
                            signature,
                        ])
                        row_count += 1
        return fails_csv_path, row_count

    def get_vso_failure_signature(self, test_job):
        error_message = getattr(test_job, "error_message", None) or ""
        for line in error_message.splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            if normalized:
                return normalized[:240]
        return "FAILED"

    def build_vso_init_command(self, all_vcomp, vcomp_jobs):
        workdir = self._get_vso_workdir()
        dbdir = self._get_vso_dbdir()
        os.makedirs(workdir, exist_ok=True)
        os.makedirs(dbdir, exist_ok=True)
        config_path = self.write_vso_regression_config(all_vcomp)
        simv_path_list = self.write_vso_simv_path_list(vcomp_jobs)
        args = [
            "--init",
            "--dbdir",
            dbdir,
            "--workdir",
            workdir,
            "--regr_config",
            config_path,
            "--target_metric",
            self.get_vso_target_metric(),
            "--simv_path_list",
            simv_path_list,
        ]
        log_path = os.path.join(self._get_vso_artifact_dir(), "vso_init.log")
        return args, log_path

    def build_vso_ask_command(self):
        workdir = self._get_vso_workdir()
        os.makedirs(workdir, exist_ok=True)
        args = [
            "--ask",
            "all",
            "--workdir",
            workdir,
            "--fmt",
            "csv",
        ]
        log_path = os.path.join(self._get_vso_artifact_dir(), "vso_ask.log")
        return args, log_path

    def _parse_vso_ask_record(self, line):
        payload = line.strip()
        if "CSO_RESULT:" not in payload:
            return None
        payload = payload.split("CSO_RESULT:", 1)[1].strip()
        if not payload:
            return None

        record = {}
        for token in shlex.split(payload):
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            record[key] = value
        if "BUILD" not in record or "TEST" not in record:
            raise RuntimeError("Malformed VSO.ai ask record: {!r}".format(line.rstrip()))
        return record

    def apply_vso_ask_results(self, all_vcomp, log_path):
        by_key = {}
        for _, (icfgs, tests) in all_vcomp.items():
            for icfg, test in zip(icfgs, tests):
                icfg.vso_assignments = []
                by_key[(self.get_vso_build_name(test.vcomper), self.get_vso_test_template_name(test))] = (icfg, test)

        planned_runs = 0
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as log_fp:
            for line in log_fp:
                record = self._parse_vso_ask_record(line)
                if record is None:
                    continue
                key = (record["BUILD"], record["TEST"])
                if key not in by_key:
                    raise RuntimeError("VSO.ai ask returned unknown build/test pair {} from {}.".format(key, log_path))
                icfg, _ = by_key[key]
                icfg.vso_assignments.append({
                    "run_id": record.get("RUN_ID"),
                    "seed": record.get("SEED"),
                    "seed_type": record.get("SEED_TYPE"),
                    "phase": record.get("PHASE"),
                    "peak_memory": record.get("PEAK_MEMORY"),
                })
                planned_runs += 1

        selected_tests = []
        selected_templates = 0
        for _, (icfgs, tests) in all_vcomp.items():
            for icfg, test in zip(icfgs, tests):
                icfg.target = len(icfg.vso_assignments)
                if icfg.target == 0:
                    test.jobstatus = test.jobstatus.SKIPPED
                else:
                    selected_templates += 1
                    selected_tests.append(test)

        return {
            "selected_tests": selected_tests,
            "selected_templates": selected_templates,
            "planned_runs": planned_runs,
        }

    def run_vso_tell(self, test_job):
        workdir = self._get_vso_workdir()
        os.makedirs(workdir, exist_ok=True)
        run_id = getattr(test_job, "vso_run_id", None) or test_job.simname
        args = [
            "--tell",
            run_id,
            "--workdir",
            workdir,
        ]
        if test_job.jobstatus != test_job.jobstatus.PASSED:
            args.extend(["--failed", self.get_vso_failure_signature(test_job)])
        log_path = os.path.join(test_job.job_dir, "vso_tell.log")
        self._run_vso_driver(args, log_path, "tell")

    def run_vso_finalize_merge(self, all_vcomp):
        workdir = self._get_vso_workdir()
        dbdir = self._get_vso_dbdir()
        os.makedirs(workdir, exist_ok=True)
        os.makedirs(dbdir, exist_ok=True)
        args = [
            "--finalize",
            "--merge",
            "--workdir",
            workdir,
            "--dbdir",
            dbdir,
        ]
        fails_csv_path, row_count = self.write_vso_fails_csv(all_vcomp)
        if row_count > 0:
            args.extend(["--update_fails", fails_csv_path])
        log_path = os.path.join(self._get_vso_artifact_dir(), "vso_finalize_merge.log")
        self._run_vso_driver(args, log_path, "finalize/merge")
        self.rcfg.deferred_messages.append("VSO.ai finalize/merge log: {}".format(log_path))

    def generate_compile_options(self, vcomp_job):
        opts = {'cov_opts': '', 'xprop_cmd': None, 'additional_defines': []}
        additional_vcs_defines = [] # Add VCS specific defines here if any

        # Coverage (Functional/Code)
        if self.options.cm:
            vcomp_job.cov_work_dir = os.path.join(self.rcfg.regression_dir, vcomp_job.name + "__COV_WORK_VCS.vdb")
            # No need to create dir here, VCS does it with -cm_dir
            opts['cov_opts'] += ' -cm_dir {} '.format(vcomp_job.cov_work_dir)
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level:
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            opts['cov_opts'] += ' -cm {} '.format(cm_level)
            if self.options.vcs_cm_line is not None:
                opts['cov_opts'] += ' -cm_line {} '.format(self.options.vcs_cm_line)
            if self.options.vcs_cm_report is not None:
                opts['cov_opts'] += ' -cm_report {} '.format(self.options.vcs_cm_report)
            if self.options.vcs_cm_hier is not None:
                opts['cov_opts'] += ' -cm_hier {} '.format(self.options.vcs_cm_hier)
            self.setup_coverage_merge(vcomp_job) # Setup merge script

        # XPROP
        if self.options.xprop_was_explicit and self.options.xprop and not self.options.mce:
            xprop_mode = self.options.xprop
            xprop_cmds = []
            xprop_cfg_path = self._find_vcs_xprop_config(vcomp_job.bench_dir, xprop_mode)
            if xprop_cfg_path is not None:
                xprop_cmds.append("-xprop={}".format(xprop_cfg_path))
            else:
                xprop_fallback = self.VCS_XPROP_FALLBACK_BY_MODE.get(xprop_mode)
                if xprop_fallback is None:
                    log.warning("Unsupported VCS XPROP mode '%s'; XPROP disabled.", xprop_mode)
                else:
                    xprop_cmds.append(xprop_fallback)

            if xprop_cmds:
                if self.options.vcs_xprop_flowctrl:
                    xprop_cmds.append("-xprop=flowctrl")
                if self.options.vcs_xprop_mmsopt:
                    xprop_cmds.append("-xprop=mmsopt")
                opts['xprop_cmd'] = " ".join(xprop_cmds)

        # Defines
        opts['additional_defines'].extend(additional_vcs_defines)
        if self.options.rtl_defines is not None:
            opts['additional_defines'].extend(self.options.rtl_defines)

        return opts

    def _find_vcs_xprop_config(self, bench_dir, xprop_mode):
        for cfg_name in self.VCS_XPROP_CONFIG_BY_MODE.get(xprop_mode, []):
            cfg_path = os.path.join(bench_dir, cfg_name)
            if os.path.exists(cfg_path):
                return cfg_path

        generic_cfg_path = os.path.join(bench_dir, 'vcs_xprop.cfg')
        if os.path.exists(generic_cfg_path):
            log.info(
                "Using generic VCS XPROP config '%s'; merge mode is controlled inside the config file.",
                generic_cfg_path,
            )
            return generic_cfg_path

        return None

    def generate_sim_options(self, test_job, seed):
        sim_args = []
        if self.options.vso:
            vso_run_id = getattr(test_job, "vso_run_id", None) or test_job.simname
            sim_args.extend(["-vso", "cso", "-vso_opts", "workdir={}".format(self._get_vso_workdir())])
            sim_args.extend(["-vso_opts", "run_id={}".format(vso_run_id)])
        sim_args.extend(["+ntb_random_seed={}".format(seed), "-xlrm", "hier_inst_seed", "-assert", "nopostproc"])
        if self.options.fgp is not None:
            sim_args.append("-fgp=num_threads:{}".format(self.options.fgp))
        if self.options.vcs_xprop_banner:
            sim_args.append("-xprop=banner")
        if self.options.vcs_xprop_report:
            sim_args.append("-report=xprop")
        test_job.test_name_seed = "{}_seed_{}".format(test_job.name, seed) # Needed for VCS sim script template

        # Coverage
        if self.options.cm:
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level:
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            sim_args.extend([
                "-cm",
                cm_level,
                "-cm_dir",
                test_job.vcomper.cov_work_dir,
                "-cm_name",
                "{}_sv{}".format(test_job.name, seed),
            ])

        return shlex.join(sim_args)

    def get_wave_capture_options(self, test_job, wave_tcl_path):
        wave_type = self.options.wave_type.lower()
        waves_db = test_job.job_dir
        default_capture = 'hdl_top'
        sim_opts = ""

        if self.options.wave_tcl:
            if os.path.exists(self.options.wave_tcl):
                wave_tcl_path = self.options.wave_tcl
                log.info(f"Using user-provided wave Tcl: {wave_tcl_path}")
            else:
                raise ValueError("{} not exists".format(self.options.wave_tcl))

        if wave_type == 'fsdb':
            waves_db = os.path.join(waves_db, "waves.fsdb")
        else:
            raise ValueError("{} wave dumping is not supported for VCS".format(self.options.wave_type))

        sim_opts += " " + shlex.join(["-ucli", "-do", wave_tcl_path])
        return {
            'sim_opts': sim_opts,
            'wave_tcl_path': wave_tcl_path,
            'waves_db': waves_db,
            'default_capture': default_capture,
        }

    def get_no_wave_capture_options(self, test_job, nwaves_tcl_path):
        if not self.options.gui:
            return {
                'sim_opts': "",
                'tcl_commands': [],
            }

        tcl_commands = ["config reversedebug on", "run"]
        return {
            'sim_opts': " " + shlex.join(["-ucli", "-do", nwaves_tcl_path]),
            'tcl_commands': tcl_commands,
        }

    def get_wave_artifact_path(self, job_dir, wave_type):
        wave_type = wave_type.lower()
        if wave_type == 'fsdb':
            return os.path.join(job_dir, 'waves.fsdb')
        raise ValueError("{} wave dumping is not supported for VCS".format(wave_type))

    def setup_coverage_merge(self, vcomp_job):
        # Only create merge script if coverage was enabled
        if not self.options.cm or not hasattr(vcomp_job, 'cov_work_dir') or not vcomp_job.cov_work_dir:
            return

        merge_sh = os.path.join(self.rcfg.regression_dir, "{}_vcs_cov_merge.sh".format(vcomp_job.name))
        merged_db_path = os.path.join(self.rcfg.regression_dir, "{}__MERGED_COV.vdb".format(vcomp_job.name))
        report_dir = os.path.join(self.rcfg.regression_dir, "{}__vcs_cov_report".format(vcomp_job.name))
        cov_db_path = vcomp_job.cov_work_dir
        merge_template = self.env.get_template('vcs_cov_merge_template.sh.j2')

        with open(merge_sh, 'w') as filep:
            filep.write(
                merge_template.render(
                    cov_db_path=cov_db_path,
                    merged_db_path=merged_db_path,
                    report_dir=report_dir,
                    urg_command=self.get_tool_command("urg"),
                    verdi_command=self.get_tool_command("verdi"),
                ))
        st = os.stat(merge_sh)
        os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)
        vcomp_job.coverage_merge_script = merge_sh
        self.rcfg.deferred_messages.append("Merge/Launch VCS coverage with {}".format(merge_sh))

    def run_report_coverage_merge(self, vcomp_jobs):
        if not self.options.cm:
            return
        for vcomp_job in vcomp_jobs.values():
            merge_script = getattr(vcomp_job, "coverage_merge_script", None)
            if not merge_script:
                continue
            result = subprocess.run(["bash", merge_script], capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError("VCS coverage merge failed:\n{}\n{}".format(result.stdout, result.stderr))

    def get_log_parsing_info(self):
        return {'warning_regex': r"^(?:Warning|Error)(?:-|\s*:).*"}

    def get_gui_command_options(self):
        # Enable Verdi debug features along with DVE/Verdi GUI
        return " -gui=verdi +UVM_VERDI_TRACE=UVM_AWARE +UVM_CONFIG_TRACE +UVM_PHASE_TRACE +UVM_OBJECTION_TRACE +UVM_RESOURCE_DB_TRACE +UVM_LOG_TRACE "

    def validate_reusable_compile_artifacts(self, vcomp_job):
        simv_path = os.path.join(vcomp_job.job_dir, "simv")
        if not os.path.exists(simv_path):
            raise FileNotFoundError(
                "VCS --no-compile requires an existing elaborated executable at '{}'".format(simv_path))

    # --- Method to implement for generating the simulation command ---
    def get_sim_command(self, test_job, sim_opts, vcomp_job_dir, log_path, user_args_list=None):
        """
        Constructs the full simulation command string for VCS, including logging.
        """
        cmd_parts = shlex.split(self.get_tool_runner())
        cmd_parts.append(os.path.join(vcomp_job_dir, "simv"))
        if self.use_smartlog():
            cmd_parts.append("-sml")
        cmd_parts.extend(["-l", log_path])
        if user_args_list:
            cmd_parts.extend(user_args_list)
        full_command = shlex.join(cmd_parts)
        if sim_opts:
            full_command += " " + sim_opts

        log.debug(f"Constructed VCS sim command: {full_command}")
        return full_command

    def get_sim_working_dir(self, test_job):
        """Run each VCS simulation from its own test job directory."""
        return test_job.job_dir

    def get_pre_sim_commands(self, test_job):
        if self.options.vso:
            return ['mkdir -p "{}"'.format(self._get_vso_workdir())]
        return []

    def get_post_sim_commands(self, test_job):
        return []
