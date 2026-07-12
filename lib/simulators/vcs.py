# lib/simulators/vcs.py
import os
import stat
import logging
import re
import shlex
import shutil
import subprocess

from lib.coverage_data import aggregate_coverage_metrics, parse_coverage_summary
from .base import SimulatorInterface, ValidationErrorParser
from .options import validate_explicit_switches
from .vcs_options import validate_vcs_runtime_options
from .vso import VsoWorkflow

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

    VCS_PARTCOMP_OPTION_BY_MODE = {
        'adaptive': '-partcomp=adaptive_sched',
        'auto': '-partcomp',
        'low': '-partcomp=autopart_low',
        'high': '-partcomp=autopart_high',
        'relax': '-partcomp=autopart_relax',
    }

    def __init__(self, options, rcfg, env):
        super().__init__(options, rcfg, env)
        self.vso_workflow = VsoWorkflow(options, rcfg)

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

    def validate_resolved_options(self):
        parser = ValidationErrorParser()
        validate_explicit_switches(self.options.xcelium_explicit_switches, "Xcelium", "VCS", parser)
        validate_vcs_runtime_options(self.options, parser)

    def validate_run_options(self, vcomp_count):
        if not self.options.vso:
            return
        if not os.environ.get("VSO_HOME"):
            raise ValueError("VSO_HOME is not set. Source the VSO.ai environment before using --vso.")
        if self.options.vso_buildname and vcomp_count > 1:
            raise ValueError("--vso-buildname can only be used with one selected VCS build.")

    def uses_shared_regression_init(self):
        return self.options.ico

    def uses_dynamic_test_plan(self):
        return self.options.vso

    def prepare_test_job(self, test_job):
        return self.vso_workflow.prepare_test(test_job) if self.options.vso else None

    def should_spawn_test_job(self, test_job):
        return self.options.vso and test_job.icfg.spawn_count <= test_job.icfg.target

    def coverage_enabled(self):
        return bool(self.options.cm)

    def get_compile_template_context(self, vcomp_job):
        vso_workdir = self.vso_workflow.workdir() if self.options.vso_cbv else ''
        if vso_workdir:
            os.makedirs(vso_workdir, exist_ok=True)
        return {
            'vcs_runner': self.get_tool_runner(),
            'vso_build_name': self.vso_workflow.build_name(vcomp_job) if self.options.vso else '',
            'vso_workdir': vso_workdir,
        }

    def get_scheduler_threads_per_test(self):
        return self.options.fgp if self.options.fgp is not None else 1

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

    def _get_ico_artifact_dir(self):
        artifact_dir = os.path.join(self.rcfg.regression_dir, "ico_artifacts")
        os.makedirs(artifact_dir, exist_ok=True)
        return artifact_dir

    def _get_ico_workdir(self):
        if self.options.ico_workdir is not None:
            return os.path.abspath(os.path.join(self.rcfg.proj_dir, self.options.ico_workdir))
        return os.path.join(self._get_ico_artifact_dir(), "workdir")

    def _get_ico_shared_record(self):
        if self.options.ico_shared_record is not None:
            return os.path.abspath(os.path.join(self.rcfg.proj_dir, self.options.ico_shared_record))
        return os.path.join(self._get_ico_artifact_dir(), "shared_record")

    def build_ico_init_command(self):
        workdir = self._get_ico_workdir()
        dbdir = self._get_ico_shared_record()
        os.makedirs(workdir, exist_ok=True)
        log_path = os.path.join(self._get_ico_artifact_dir(), "ico_init.log")
        if os.path.isfile(os.path.join(dbdir, "readme.txt")):
            return None, log_path
        os.makedirs(os.path.dirname(dbdir), exist_ok=True)
        return shlex.split(self.get_tool_runner()) + ["crg", "-dir", dbdir, "-shared", "init"], log_path

    def generate_compile_options(self, vcomp_job):
        opts = {
            'cov_opts': '',
            'partcomp_opts': self.get_partition_compile_options(vcomp_job),
            'xprop_cmd': None,
            'additional_defines': [],
        }
        additional_vcs_defines = [] # Add VCS specific defines here if any

        # Coverage (Functional/Code)
        if self.options.cm:
            vcomp_job.cov_work_dir = os.path.join(self.rcfg.regression_dir, vcomp_job.name + "__COV_WORK_VCS.vdb")
            if self.options.no_compile:
                shutil.rmtree(os.path.join(vcomp_job.cov_work_dir, "snps", "coverage", "db", "testdata"),
                              ignore_errors=True)
            else:
                shutil.rmtree(vcomp_job.cov_work_dir, ignore_errors=True)
            opts['cov_opts'] += ' -cm_dir {} '.format(vcomp_job.cov_work_dir)
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level:
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            opts['cov_opts'] += ' -cm {} '.format(cm_level)
            if self.options.vcs_cm_line is not None:
                opts['cov_opts'] += ' -cm_line {} '.format(self.options.vcs_cm_line)
            for report_mode in self.options.vcs_cm_report or []:
                opts['cov_opts'] += ' -cm_report {} '.format(report_mode)
            if self.options.vcs_cm_cond is not None:
                opts['cov_opts'] += ' -cm_cond {} '.format(self.options.vcs_cm_cond)
            if self.options.vcs_cm_tgl is not None:
                opts['cov_opts'] += ' -cm_tgl {} '.format(self.options.vcs_cm_tgl)
            cm_hier = self.options.vcs_cm_hier or getattr(vcomp_job, "tb_options", {}).get("vcs_cm_hier")
            if cm_hier:
                opts['cov_opts'] += ' -cm_hier {} '.format(cm_hier)
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

    def get_partition_compile_options(self, vcomp_job):
        jobs = '-fastpartcomp=j{}'.format(self.options.vcs_partcomp_jobs)
        if self.options.dtl:
            return shlex.join([
                '-partcomp',
                '-dir={}'.format(os.path.join(vcomp_job.job_dir, 'dtl_static')),
                jobs,
            ])

        mode_option = self.VCS_PARTCOMP_OPTION_BY_MODE.get(self.options.vcs_partcomp_mode)
        if mode_option is None:
            return ''

        partition_dir = self.options.vcs_partcomp_dir or os.path.join(vcomp_job.job_dir, 'partitionlib')
        if not os.path.isabs(partition_dir):
            partition_dir = os.path.join(self.rcfg.proj_dir, partition_dir)
        args = [
            mode_option,
            '-partcomp_dir={}'.format(os.path.abspath(partition_dir)),
            '-partcomp=incr_clean',
            jobs,
        ]
        if self.options.vcs_partcomp_sharedlib is not None:
            args.append('-partcomp_sharedlib={}'.format(os.path.abspath(self.options.vcs_partcomp_sharedlib)))
        return shlex.join(args)

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
        coverage_name = "{}_sv{}_i{}".format(test_job.name, seed, test_job.iteration)
        test_job.test_name_seed = coverage_name
        if self.options.vso:
            sim_args.extend(self.vso_workflow.sim_options(test_job))
        if self.options.vso_ccex:
            sim_args.extend(["-vso", "ccex"])
            if self.options.vso_ccex_rca:
                sim_args.extend(["-ccex_opts", "rca"])
            if self.options.vso_ccex_auto_merge_dir:
                merge_dir = os.path.abspath(os.path.join(self.rcfg.proj_dir, self.options.vso_ccex_auto_merge_dir))
                os.makedirs(merge_dir, exist_ok=True)
                sim_args.extend(["-ccex_opts", "auto_merge_dir={}".format(merge_dir)])
        if self.options.ico:
            sim_args.extend([
                "+ntb_solver_bias_mode_auto_config=2",
                "+ntb_solver_bias_shared_record={}".format(self._get_ico_shared_record()),
                "+ntb_solver_bias_wdir={}".format(self._get_ico_workdir()),
                "+ntb_solver_bias_test_type=uvm",
                "+ntb_solver_bias_test_name={}".format(coverage_name),
            ])
        sim_args.extend(["+ntb_random_seed={}".format(seed), "-xlrm", "hier_inst_seed", "-assert", "nopostproc"])
        if self.options.fgp is not None:
            sim_args.append("-fgp=num_threads:{}".format(self.options.fgp))
        if self.options.vcs_xprop_banner:
            sim_args.append("-xprop=banner")
        if self.options.vcs_xprop_report:
            sim_args.append("-report=xprop")
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
                coverage_name,
            ])
            test_job.coverage_db_path = os.path.join(
                test_job.vcomper.cov_work_dir,
                "snps",
                "coverage",
                "db",
                "testdata",
                coverage_name,
            )

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
            'render_template': not self.options.wave_tcl,
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
                    urg_parallel=self.options.vcs_urg_parallel,
                    urg_show_tests=self.options.vcs_urg_show_tests,
                    verdi_command=self.get_tool_command("verdi"),
                ))
        st = os.stat(merge_sh)
        os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)
        vcomp_job.coverage_merge_script = merge_sh
        vcomp_job.coverage_report_dir = report_dir
        vcomp_job.merged_coverage_dir = merged_db_path
        self.rcfg.deferred_messages.append("Merge/Launch VCS coverage with {}".format(merge_sh))

    def run_report_coverage_merge(self, vcomp_jobs):
        if not self.options.cm:
            return
        for vcomp_job in vcomp_jobs.values():
            merge_script = getattr(vcomp_job, "coverage_merge_script", None)
            if not merge_script:
                continue
            try:
                result = subprocess.run(["bash", merge_script], capture_output=True, text=True)
            except OSError as exc:
                log.error("VCS coverage merge could not start for %s: %s", vcomp_job, exc)
                continue
            if result.returncode != 0:
                log.error("VCS coverage merge failed for %s:\n%s\n%s", vcomp_job, result.stdout, result.stderr)

    def cleanup_test_coverage(self, test_job):
        path = getattr(test_job, "coverage_db_path", None)
        if path:
            shutil.rmtree(path, ignore_errors=True)

    def collect_coverage_data(self, vcomp_jobs):
        if not self.options.cm:
            return {vcomp.split(":")[-1]: aggregate_coverage_metrics({}) for vcomp in vcomp_jobs}
        coverage = {}
        for vcomp, job in vcomp_jobs.items():
            report_dir = getattr(job, "coverage_report_dir", None)
            metrics = parse_coverage_summary(os.path.join(report_dir, "dashboard.txt")) if report_dir else {}
            coverage[vcomp.split(":")[-1]] = aggregate_coverage_metrics(metrics)
        return coverage

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
        return []

    def get_post_sim_commands(self, test_job):
        return []
