# lib/simulators/vcs.py
import json
import os
import stat
import logging
import platform
import re
import shlex
import shutil
import socket
import subprocess
import tempfile

from lib.coverage_data import aggregate_coverage_metrics, parse_coverage_summary
from .base import SimulatorInterface, ValidationErrorParser
from .options import validate_explicit_switches
from .vcs_options import validate_vcs_runtime_options
from .vso import VsoWorkflow
from .vcs_jobs import IcoInitJob, VsoAskJob, VsoInitJob

log = logging.getLogger(__name__)

PARTCOMP_MANIFEST_FILENAME = ".rules_verilog_partcomp.json"


def _positive_integer(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _lsf_host_slots(value, hostname=None):
    tokens = (value or "").split()
    if len(tokens) < 2 or len(tokens) % 2:
        return None
    pairs = []
    for index in range(0, len(tokens), 2):
        slots = _positive_integer(tokens[index + 1])
        if slots is None:
            return None
        pairs.append((tokens[index], slots))
    if len(pairs) == 1:
        return pairs[0][1]

    hostname = hostname or socket.gethostname()
    local_names = {hostname.lower(), hostname.split('.', 1)[0].lower()}
    for host, slots in pairs:
        if host.lower() in local_names or host.split('.', 1)[0].lower() in local_names:
            return slots
    return min(slots for _, slots in pairs)


def _lsf_host_list_slots(value, hostname=None):
    hosts = (value or "").split()
    if not hosts:
        return None
    hostname = hostname or socket.gethostname()
    local_names = {hostname.lower(), hostname.split('.', 1)[0].lower()}
    local_slots = sum(1 for host in hosts
                      if host.lower() in local_names or host.split('.', 1)[0].lower() in local_names)
    if local_slots:
        return local_slots
    slots_by_host = {}
    for host in hosts:
        short_name = host.split('.', 1)[0].lower()
        slots_by_host[short_name] = slots_by_host.get(short_name, 0) + 1
    return min(slots_by_host.values())


def detect_allocated_cpus(environment=None):
    """Return CPUs assigned to this process and the allocation source."""
    environment = os.environ if environment is None else environment

    affinity_count = None
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        try:
            affinity_count = len(affinity(0)) or None
        except OSError:
            pass

    host_slots = _lsf_host_slots(environment.get("LSB_MCPU_HOSTS"))
    if host_slots is None:
        host_slots = _lsf_host_list_slots(environment.get("LSB_HOSTS"))
        host_source = "LSB_HOSTS"
    else:
        host_source = "LSB_MCPU_HOSTS"
    if host_slots is not None:
        if affinity_count is not None and affinity_count < host_slots:
            return affinity_count, "{} capped by CPU affinity".format(host_source)
        return host_slots, host_source

    slurm_cpus = _positive_integer(environment.get("SLURM_CPUS_PER_TASK"))
    if slurm_cpus is not None:
        if affinity_count is not None and affinity_count < slurm_cpus:
            return affinity_count, "SLURM_CPUS_PER_TASK capped by CPU affinity"
        return slurm_cpus, "SLURM_CPUS_PER_TASK"

    lsf_total = _positive_integer(environment.get("LSB_DJOB_NUMPROC"))
    if lsf_total is not None:
        if affinity_count is not None and affinity_count < lsf_total:
            return affinity_count, "LSB_DJOB_NUMPROC capped by CPU affinity"
        if lsf_total == 1:
            return 1, "LSB_DJOB_NUMPROC"
        return 1, "LSB_DJOB_NUMPROC without per-host allocation (conservative)"

    if affinity_count is not None:
        return min(affinity_count, 8), "CPU affinity fallback (capped at 8)"

    return min(os.cpu_count() or 1, 8), "host CPU count fallback (capped at 8)"


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
        self._vso_init_job = None
        self._vso_ask_job = None
        self._resolved_partcomp_jobs = None
        self._vcs_tool_identity = None

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

    def get_tool_identity(self):
        if self._vcs_tool_identity is not None:
            return self._vcs_tool_identity
        configured_identity = os.environ.get("RV_VCS_TOOL_ID")
        if configured_identity:
            self._vcs_tool_identity = configured_identity
            return self._vcs_tool_identity

        command = shlex.split(self.get_tool_runner()) + ["vcs", "-full64", "-ID"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "Unable to resolve the VCS build ID with '{}'. Set RV_VCS_TOOL_ID to the site VCS release ID: {}".
                format(shlex.join(command), exc)) from exc
        identity = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        if result.returncode != 0 or not identity:
            raise RuntimeError(
                "Unable to resolve the VCS build ID with '{}'. Set RV_VCS_TOOL_ID to the site VCS release ID.\n{}".
                format(shlex.join(command), identity))
        self._vcs_tool_identity = identity
        return self._vcs_tool_identity

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

    def uses_dynamic_test_plan(self):
        return self.options.vso

    def create_regression_jobs(self, vcomp_jobs):
        if self.options.no_run:
            return []

        jobs = []
        if self.options.ico:
            ico_init_job = IcoInitJob(self.rcfg, self)
            for vcomp_job in vcomp_jobs.values():
                ico_init_job.add_dependency(vcomp_job)
            for _, tests in self.rcfg.all_vcomp.values():
                for test in tests:
                    test.add_dependency(ico_init_job)
            jobs.append(ico_init_job)

        if self.options.vso:
            self._vso_init_job = VsoInitJob(self.rcfg, self, vcomp_jobs)
            for vcomp_job in vcomp_jobs.values():
                self._vso_init_job.add_dependency(vcomp_job)
            self._vso_ask_job = VsoAskJob(self.rcfg, self)
            self._vso_ask_job.add_dependency(self._vso_init_job)
            for _, tests in self.rcfg.all_vcomp.values():
                for test in tests:
                    test.add_dependency(self._vso_ask_job)
            jobs.extend([self._vso_init_job, self._vso_ask_job])
        return jobs

    def finalize_regression_workflow(self):
        if not self.options.vso or self.options.no_run:
            return False
        if not self._vso_init_job.jobstatus.successful or not self._vso_ask_job.jobstatus.successful:
            return False
        try:
            self.vso_workflow.finalize_merge(self.rcfg.all_vcomp)
        except (OSError, RuntimeError) as exc:
            log.error("%s", exc)
            return True
        return False

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

    def get_compile_fingerprint_inputs(self, vcomp_job):
        inputs = super().get_compile_fingerprint_inputs(vcomp_job)
        if self.options.vcs_cm_hier:
            inputs["extra_input_paths"].append(self.options.vcs_cm_hier)
        xprop_config = getattr(vcomp_job, "vcs_xprop_config_path", None)
        if xprop_config:
            inputs["extra_input_paths"].append(xprop_config)
        inputs["environment"].update(
            {key: os.environ.get(key, "")
             for key in ("LM_LICENSE_FILE", "VCS_HOME", "VSO_HOME")})
        inputs["environment"]["VCS_TOOL_ID"] = self.get_tool_identity()
        return inputs

    def compile_script_for_fingerprint(self, compile_script):
        return re.sub(r"-fastpartcomp=j\d+", "-fastpartcomp=jAUTO", compile_script)

    def should_auto_reuse_compile(self):
        return self.options.vcs_auto_compile_cache

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
            vcomp_job.vcs_xprop_config_path = xprop_cfg_path
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
        if self.options.dtl:
            jobs = '-fastpartcomp=j{}'.format(self.get_partcomp_jobs())
            dtl_dir = os.path.join(vcomp_job.job_dir, self._debug_partition_dirname('dtl_static'))
            return shlex.join([
                '-partcomp',
                '-dir={}'.format(dtl_dir),
                jobs,
            ])

        mode_option = self.VCS_PARTCOMP_OPTION_BY_MODE.get(self.options.vcs_partcomp_mode)
        if mode_option is None:
            return ''

        job_count = self.get_partcomp_jobs()
        jobs = '-fastpartcomp=j{}'.format(job_count)
        partition_dir = self.get_partition_compile_dir(vcomp_job)
        args = [
            mode_option,
            '-partcomp_dir={}'.format(os.path.abspath(partition_dir)),
            '-partcomp=incr_clean',
            jobs,
        ]
        if self.options.vcs_partcomp_sharedlib is not None:
            args.append('-partcomp_sharedlib={}'.format(os.path.abspath(self.options.vcs_partcomp_sharedlib)))
        return shlex.join(args)

    def get_partcomp_jobs(self):
        if self._resolved_partcomp_jobs is not None:
            return self._resolved_partcomp_jobs
        if self.options.vcs_partcomp_jobs != 'auto':
            self._resolved_partcomp_jobs = self.options.vcs_partcomp_jobs
            return self._resolved_partcomp_jobs
        self._resolved_partcomp_jobs, source = detect_allocated_cpus()
        log.info("VCS Partition Compile auto-selected j%d from %s", self._resolved_partcomp_jobs, source)
        return self._resolved_partcomp_jobs

    def get_partition_compile_dir(self, vcomp_job):
        partition_dir = self.options.vcs_partcomp_dir or os.path.join(
            vcomp_job.job_dir,
            self._debug_partition_dirname('partitionlib'),
        )
        if not os.path.isabs(partition_dir):
            partition_dir = os.path.join(self.rcfg.proj_dir, partition_dir)
        return os.path.abspath(partition_dir)

    def _debug_partition_dirname(self, base_name):
        if self.options.gui:
            return base_name + '_gui'
        if self.options.waves is not None:
            return base_name + '_waves'
        return base_name

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
            return False
        failed = False
        for vcomp_job in vcomp_jobs.values():
            merge_script = getattr(vcomp_job, "coverage_merge_script", None)
            if not merge_script:
                log.error("VCS coverage merge script is unavailable for %s", vcomp_job)
                failed = True
                continue
            try:
                result = subprocess.run(["bash", merge_script], capture_output=True, text=True)
            except OSError as exc:
                log.error("VCS coverage merge could not start for %s: %s", vcomp_job, exc)
                failed = True
                continue
            if result.returncode != 0:
                log.error("VCS coverage merge failed for %s:\n%s\n%s", vcomp_job, result.stdout, result.stderr)
                failed = True
        return failed

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

    def _partcomp_manifest_identity(self, vcomp_job):
        fingerprint = vcomp_job.compile_fingerprint
        try:
            os_release = platform.freedesktop_os_release()
        except (AttributeError, OSError):
            os_release = {}
        return {
            "schema_version": 1,
            "tool": {
                "vcs_home": os.environ.get("VCS_HOME", ""),
                "vcs_tool_id": self.get_tool_identity(),
                "runner": self.get_tool_runner(),
                "platform": platform.system(),
                "machine": platform.machine(),
                "os_id": os_release.get("ID", ""),
                "os_version": os_release.get("VERSION_ID", ""),
            },
            "inputs": {
                "compile_args_sha256": fingerprint.get("compile_args_sha256"),
                "compile_inputs_manifest_sha256": fingerprint.get("compile_inputs_manifest_sha256"),
                "extra_inputs_content_sha256": fingerprint.get("extra_inputs_content_sha256"),
            },
            "configuration": {
                "partcomp_mode": self.options.vcs_partcomp_mode,
                "debug_mode": "gui" if self.options.gui else "waves" if self.options.waves is not None else "default",
                "coverage": self.options.cm,
                "coverage_line": self.options.vcs_cm_line,
                "coverage_report": self.options.vcs_cm_report or [],
                "coverage_cond": self.options.vcs_cm_cond,
                "coverage_tgl": self.options.vcs_cm_tgl,
                "fgp": self.options.fgp is not None,
                "smartlog": self.use_smartlog(),
                "xprop": self.options.xprop if self.options.xprop_was_explicit else None,
                "xprop_flowctrl": self.options.vcs_xprop_flowctrl,
                "xprop_mmsopt": self.options.vcs_xprop_mmsopt,
                "rtl_defines": self.options.rtl_defines or [],
                "vso": self.options.vso,
                "vso_cbv": self.options.vso_cbv,
                "vso_build_name": self.vso_workflow.build_name(vcomp_job) if self.options.vso else None,
                "vso_workdir": self.vso_workflow.workdir() if self.options.vso_cbv else None,
                "vso_ccex": self.options.vso_ccex,
                "vso_ccex_rca": self.options.vso_ccex_rca,
            },
        }

    def validate_compile_cache_context(self, vcomp_job):
        sharedlib = self.options.vcs_partcomp_sharedlib
        if sharedlib is None:
            return
        manifest_path = os.path.join(os.path.abspath(sharedlib), PARTCOMP_MANIFEST_FILENAME)
        if not os.path.isfile(manifest_path):
            log.warning("VCS Partition Compile shared library has no rules_verilog manifest: %s", manifest_path)
            return
        try:
            with open(manifest_path, "r", encoding="utf-8") as filep:
                actual = json.load(filep)
        except (OSError, ValueError) as exc:
            raise RuntimeError("Cannot read VCS Partition Compile manifest '{}': {}".format(manifest_path,
                                                                                            exc)) from exc
        expected = self._partcomp_manifest_identity(vcomp_job)
        if actual != expected:
            mismatches = sorted(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key))
            raise RuntimeError("VCS Partition Compile shared library is incompatible ({}): {}".format(
                ", ".join(mismatches), manifest_path))

    def prepare_compile_execution(self, vcomp_job, reusing_compile):
        if not self.options.cm:
            return
        if reusing_compile:
            shutil.rmtree(os.path.join(vcomp_job.cov_work_dir, "snps", "coverage", "db", "testdata"),
                          ignore_errors=True)
        else:
            shutil.rmtree(vcomp_job.cov_work_dir, ignore_errors=True)

    def validate_reusable_compile_artifacts(self, vcomp_job):
        simv_path = os.path.join(vcomp_job.job_dir, "simv")
        if not os.path.exists(simv_path):
            raise FileNotFoundError(
                "VCS --no-compile requires an existing elaborated executable at '{}'".format(simv_path))

    def record_compile_artifacts(self, vcomp_job):
        self.validate_reusable_compile_artifacts(vcomp_job)
        if (self.options.dtl or self.options.vcs_partcomp_mode == 'disabled'
                or (self.options.vcs_partcomp_dir is None and self.options.vcs_partcomp_sharedlib is None)):
            return
        partition_dir = self.get_partition_compile_dir(vcomp_job)
        os.makedirs(partition_dir, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(prefix=".partcomp-manifest-", dir=partition_dir, text=True)
        manifest_path = os.path.join(partition_dir, PARTCOMP_MANIFEST_FILENAME)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as filep:
                json.dump(self._partcomp_manifest_identity(vcomp_job), filep, indent=2, sort_keys=True)
                filep.write("\n")
            os.replace(temporary_path, manifest_path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

    def collect_compile_metrics(self, vcomp_job):
        reused = bool(self.options.no_compile or getattr(vcomp_job, "compile_cache_hit", False))
        metrics = {
            "compile_cache_hit":
            bool(getattr(vcomp_job, "compile_cache_hit", False)),
            "compile_reused":
            reused,
            "partcomp_mode":
            self.options.vcs_partcomp_mode,
            "partcomp_jobs":
            self.get_partcomp_jobs() if self.options.vcs_partcomp_mode != 'disabled' and not reused else None,
        }
        if reused or not self.options.vcs_profile or not os.path.isfile(vcomp_job.log_path):
            return metrics
        markers = {"PC_SHARED": 0, "PC_RECOMPILE": 0}
        with open(vcomp_job.log_path, "r", encoding="utf-8", errors="ignore") as filep:
            for line in filep:
                for marker in markers:
                    if marker in line:
                        markers[marker] += 1
        metrics["profile_marker_lines"] = markers
        return metrics

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
