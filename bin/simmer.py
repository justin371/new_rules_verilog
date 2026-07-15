#!/usr/bin/env python

################################################################################
# standard lib imports
from copy import deepcopy
import ast
import datetime
from hashlib import sha1
import os
import sys
import random
import re
import shlex
import shutil
import subprocess

################################################################################
# Bigger libraries (better to place these later for dependency ordering
import jinja2

# Determine the absolute path to the directory containing this script
dir_path = os.path.dirname(os.path.realpath(__file__))

################################################################################
# rules_verilog lib imports
from args_parser import parse_args
from lib.job_lib import Job, JobStatus
from lib import cmn_logging
from lib import compile_cache
from lib import job_lib
from lib import regression
from lib import rv_utils
from lib import seed_plan
from lib import sim_artifacts
from lib import simmer_results
from lib.runtime_options import (
    append_uvm_control_options,
    format_log_check_args,
    format_sim_opts_dict,
    merge_test_runtime_sim_opts,
    resolve_test_timeout_hours,
)
from lib.simulators.base import SimulatorInterface
from lib.simulators.xcelium import XceliumSimulator
from lib.simulators.vcs import VcsSimulator
from lib import regression_report

log = None

ENV_CAPTURE_KEYS = (
    "HOME",
    "HOSTNAME",
    "LM_LICENSE_FILE",
    "LOADEDMODULES",
    "MODULEPATH",
    "PATH",
    "PROJ_DIR",
    "SIMRESULTS",
    "SIM_PLATFORM",
    "VCS_HOME",
    "VSO_HOME",
    "XCELIUMHOME",
)

# Use the absolute path to locate the 'templates' directory
file_loader = jinja2.FileSystemLoader(searchpath=os.path.join(dir_path, 'templates'))
jinja2_env = jinja2.Environment(loader=file_loader)
jinja2_env.filters['shell_quote'] = shlex.quote
report_jinja2_env = regression_report.create_template_environment(os.path.join(dir_path, 'templates'))

#XRUN_COMPILE_TEMPLATE = jinja2_env.get_template('xrun_compile_template.sh.j2')
#VCS_COMPILE_TEMPLATE = jinja2_env.get_template('vcs_compile_template.sh.j2')
#SIM_TEMPLATE = jinja2_env.get_template('sim_template.sh.j2')
RERUN_TEMPLATE = jinja2_env.get_template('rerun_template.sh.j2')
RUN_WAVE_TEMPLATE = jinja2_env.get_template('run_waves_template.sh.j2')


def get_bazel_bin():
    result = subprocess.run(["bazel", "info", "bazel-bin"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("bazel info bazel-bin failed:\n{}\n{}".format(result.stdout, result.stderr))
    return result.stdout.strip()


def load_warning_waivers(path):
    with open(path, 'r') as filep:
        content = filep.read()

    try:
        waiver_patterns = ast.literal_eval(content)
    except (SyntaxError, ValueError):
        tree = ast.parse(content, mode='eval')
        if not isinstance(tree.body, ast.List):
            raise TypeError("Waiver file content must be a list.")
        waiver_patterns = []
        for item in tree.body.elts:
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
                is_re_compile = (isinstance(item.func.value, ast.Name) and item.func.value.id == 're'
                                 and item.func.attr == 'compile')
                has_string_arg = item.args and isinstance(item.args[0], ast.Constant) and isinstance(
                    item.args[0].value, str)
                if is_re_compile and has_string_arg:
                    waiver_patterns.append(item.args[0].value)
                    continue
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                waiver_patterns.append(item.value)
                continue
            raise TypeError("Unsupported waiver entry: {}".format(ast.dump(item)))

    if not isinstance(waiver_patterns, list):
        raise TypeError("Waiver file content must be a list.")
    return [p if isinstance(p, re.Pattern) else re.compile(p) for p in waiver_patterns]


def replace_symlink(link_path, target_path):
    if os.path.lexists(link_path):
        os.remove(link_path)
    os.symlink(target_path, link_path)


SIMULATOR_CLASSES = {
    "vcs": VcsSimulator,
    "xrun": XceliumSimulator,
}


def get_simulator(options, rcfg, jinja_env) -> SimulatorInterface:
    """Instantiates and returns the correct simulator object."""
    simulator_class = SIMULATOR_CLASSES.get(options.simulator.lower())
    if simulator_class is None:
        raise ValueError(f"Unsupported simulator specified: {options.simulator}")
    return simulator_class(options, rcfg, jinja_env)


def resolve_run_simulator(rcfg, options):
    selected_simulators = {}
    for _, test_list in rcfg.all_vcomp.items():
        for test_target in test_list.keys():
            simulator = rcfg.tests_to_simulator.get(test_target, "XRUN").upper()
            selected_simulators.setdefault(simulator, []).append(test_target)

    if not selected_simulators:
        rcfg.simulator = options.simulator
        return options.simulator

    if len(selected_simulators) > 1:
        details = []
        for simulator, tests in sorted(selected_simulators.items()):
            preview = ", ".join(tests[:3])
            if len(tests) > 3:
                preview += ", ..."
            details.append("{}: {}".format(simulator, preview))
        rcfg.log.critical(
            "Selected tests resolve to multiple simulators (%s). Mixed XRUN/VCS runs are not supported. "
            "Please run each simulator group separately.",
            "; ".join(details),
        )
        sys.exit(1)

    resolved_simulator = next(iter(selected_simulators))
    if getattr(options, "simulator_was_explicit", False) and options.simulator != resolved_simulator:
        rcfg.log.critical(
            "--simulator %s conflicts with the selected test cfg simulator %s. "
            "Please remove the override or run matching tests only.",
            options.simulator,
            resolved_simulator,
        )
        sys.exit(1)

    options.simulator = resolved_simulator
    rcfg.simulator = resolved_simulator

    return resolved_simulator


def get_active_job_limit(options, rcfg, simulator):
    total_tests = sum(icfg.target for _, (icfgs, _) in rcfg.all_vcomp.items() for icfg in icfgs)
    if total_tests <= 1:
        return 1

    if options.gui:
        return 1

    if options.jobs is not None:
        requested_jobs = options.jobs
    else:
        cpu_count = os.cpu_count() or 1
        requested_jobs = max(1, cpu_count // simulator.get_scheduler_threads_per_test())
    return max(1, min(total_tests, requested_jobs))


# The jobs of the verification compilation and elaboration stages
class VCompJob(Job):
    # All found vcomp names to prevent collisions
    all_names = {}

    def __init__(self, rcfg, bazel_vcomp_target, simulator: SimulatorInterface):
        self.bazel_vcomp_target = bazel_vcomp_target
        name = os.path.basename(self.bazel_vcomp_target.split(":")[1])
        if name in self.__class__.all_names:
            log.critical("Found duplicate dv_tb name in %s and %s", self.bazel_vcomp_target,
                         self.__class__.all_names[name].bazel_vcomp_target)
        else:
            self.__class__.all_names[name] = self

        super(VCompJob, self).__init__(rcfg, name)
        self.simulator = simulator
        self.rcfg = rcfg

        self.bench_dir = os.path.join(self.rcfg.proj_dir, self.bazel_vcomp_target.split(':')[0][2:])

        # Use simulator name in dir for clarity if needed, or keep original
        #job_dir = "{}__VCOMP{}".format(self.name, self.rcfg.options.dir_suffix)
        job_dir = "{}__{}_VCOMP{}".format(self.name, self.simulator.get_name().upper(), self.rcfg.options.dir_suffix)

        self.base_job_dir = os.path.join(self.rcfg.regression_dir, job_dir)
        self.job_dir = self.simulator.get_vcomp_job_dir(self.base_job_dir)
        self.log_path = os.path.join(self.job_dir, "cmp.log")

        self.main_cmdline = None
        self.cov_work_dir = None
        self.compile_cache_hit = False

    def pre_run(self):
        super(VCompJob, self).pre_run()

        options = self.rcfg.options
        relpath, bazel_target = self.bazel_vcomp_target.split(':')
        relpath = relpath[2:] # Remove leading //
        bazel_bin = get_bazel_bin()
        self.bazel_runfiles_main = os.path.join(bazel_bin, relpath, "{}.runfiles".format(bazel_target), "__main__")
        self.bazel_compile_args = self.simulator.get_bazel_compile_args_file(self.bazel_runfiles_main, relpath,
                                                                             bazel_target)
        self.bazel_runtime_args = self.simulator.get_bazel_runtime_args_file(self.bazel_runfiles_main, relpath,
                                                                             bazel_target)
        self.compile_warning_waivers_path = os.path.join(self.bazel_runfiles_main, relpath,
                                                         "{}_compile_warning_waivers".format(bazel_target))
        tb_options_path = os.path.join(self.bazel_runfiles_main, relpath, "{}_tb_options.py".format(bazel_target))
        self.tb_options = {
            "dut_instance": "hdl_top.dut",
            "dut_top": "dut",
            "compile_inputs": "",
        }
        if os.path.isfile(tb_options_path):
            with open(tb_options_path, "r", encoding="utf-8") as filep:
                self.tb_options.update(ast.literal_eval(filep.read()))
        self.simulator.prepare_compile_job(self)
        debug_mode = "default"
        if options.waves is not None:
            debug_mode = "waves"
        if options.gui:
            debug_mode = "gui"

        compile_gen_opts = self.simulator.generate_compile_options(self)
        cov_opts = compile_gen_opts['cov_opts']
        partcomp_opts = compile_gen_opts.get('partcomp_opts', '')
        xprop_cmd = compile_gen_opts['xprop_cmd']
        additional_defines = compile_gen_opts['additional_defines']

        log.debug("workdir = %s", self.job_dir)

        with open(os.path.join(self.job_dir, 'env.out'), 'w') as env_out:
            for key in ENV_CAPTURE_KEYS:
                if key in os.environ:
                    env_out.write("{}={}\n".format(key, os.environ[key]))
        with open(os.path.join(self.job_dir, 'hostname.out'), 'w') as hostname_out:
            subprocess.run(["hostname"], stdout=hostname_out, stderr=subprocess.STDOUT, check=False)

        if options.compile_args_file and not os.path.exists(options.compile_args_file):
            self.rcfg.log.critical(f"The specified compile arguments file does not exist: {options.compile_args_file}")
            sys.exit(1)

        if options.recompile:
            log.info("Removing vcomp library %s due to --recompile flag", self.job_dir)
            shutil.rmtree(self.job_dir, ignore_errors=True)
            os.makedirs(self.job_dir, exist_ok=True)

        # --- Template Rendering ---
        vcomp_sh_path = os.path.join(self.job_dir, "vcomp.sh")
        compile_template = self.simulator.get_compile_template(self)

        tb_name = bazel_target

        template_context = {
            'VCOMP_DIR': self.job_dir,
            'cov_opts': cov_opts,
            'partcomp_opts': partcomp_opts,
            'bazel_runfiles_main': self.bazel_runfiles_main,
            'bazel_compile_args': self.bazel_compile_args,
            'debug_mode': debug_mode,
            'xprop_cmd': xprop_cmd,
            'relpath': relpath,
            'tb_name': tb_name, # Pass derived tb_name
            'additional_defines': additional_defines,
            'options': options, # Pass full options object
            # Add simulator name if needed in template
            'simulator_name': self.simulator.get_name(),
            'msie_href_file': getattr(self, 'msie_href_file', None),
            'msie_primary_dir': getattr(self, 'msie_primary_dir', None),
            'msie_primary_name': getattr(self, 'msie_primary_name', None),
            'msie_primary_top': getattr(self, 'msie_primary_top', None),
            'msie_extern_files': getattr(self, 'msie_extern_files', []),
        }
        template_context.update(self.simulator.get_compile_template_context(self))

        compile_script = compile_template.render(**template_context)
        sim_artifacts.write_executable_script(vcomp_sh_path, compile_script)
        fingerprint_inputs = self.simulator.get_compile_fingerprint_inputs(self)
        self.compile_fingerprint = compile_cache.compile_fingerprint(
            self.rcfg.proj_dir,
            self.simulator.compile_script_for_fingerprint(compile_script),
            self.bazel_compile_args,
            os.path.join(self.bazel_runfiles_main, self.tb_options["compile_inputs"])
            if self.tb_options["compile_inputs"] else None,
            self.bazel_runfiles_main,
            **fingerprint_inputs,
        )
        self.simulator.validate_compile_cache_context(self)

        log.debug("bazel_runfiles_main: %s", self.bazel_runfiles_main)

        if self.rcfg.options.no_compile:
            self.simulator.validate_reusable_compile_artifacts(self)
            compile_cache.validate_compile_fingerprint(self.job_dir, self.compile_fingerprint)
            self.main_cmdline = "echo \"Bypassing {} due to --no-compile\"".format(self)
        elif self.simulator.should_auto_reuse_compile():
            self.compile_cache_hit, miss_reason = compile_cache.can_reuse_compile(
                self.job_dir,
                self.compile_fingerprint,
                lambda: self.simulator.validate_reusable_compile_artifacts(self),
            )
            if not self.compile_cache_hit:
                log.info("VCS compile cache miss for %s: %s", self, miss_reason)
                self.main_cmdline = shlex.join(["bash", vcomp_sh_path])
            else:
                self.main_cmdline = "echo \"Bypassing {} due to VCS compile cache hit\"".format(self)
        else:
            self.main_cmdline = shlex.join(["bash", vcomp_sh_path])

        if not self.rcfg.options.no_compile and not self.compile_cache_hit:
            compile_cache.invalidate_compile_fingerprint(self.job_dir)

        self.simulator.prepare_compile_execution(
            self,
            reusing_compile=self.rcfg.options.no_compile or self.compile_cache_hit,
        )

        log.debug(" > %s", self.main_cmdline)

    def post_run(self):
        # --- Determine initial status based on return code ---
        if self.job_lib.returncode == 0:
            log_level = log.info
            self.jobstatus = JobStatus.PASSED # Start assuming PASSED if return code is 0
        else:
            log_level = log.error
            self.jobstatus = JobStatus.FAILED # Assume FAILED initially if non-zero exit

        # --- Warning Waiver Processing ---
        # Get simulator-specific parsing info (warning regex)
        parse_info = self.simulator.get_log_parsing_info()
        # Use a reasonable default if the simulator doesn't provide one
        base_warning_pattern = parse_info.get('warning_regex', r"^\s*\*W.*")
        log.debug(f"Using base warning pattern: '{base_warning_pattern}'")

        warning_waivers = [] # Initialize waiver list

        # Check if waivers file exists
        if not os.path.exists(self.compile_warning_waivers_path):
            log.debug(
                f"Compile warning waivers file not found: {self.compile_warning_waivers_path}. Skipping warning check.")
        # Check if compile log exists
        elif not os.path.exists(self.log_path):
            log.warning(f"Compile log file not found: {self.log_path}. Cannot check for warnings.")
            # Consider if missing log should be a failure
            # if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED
        else:
            # Proceed only if waiver and log files exist
            try:
                warning_waivers = load_warning_waivers(self.compile_warning_waivers_path)
                log.debug(f"Loaded {len(warning_waivers)} waiver patterns from file.")

            except FileNotFoundError:
                # This case is handled by the os.path.exists check above, but included for robustness
                log.error(f"Waiver file disappeared unexpectedly: {self.compile_warning_waivers_path}")
                if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED
            except SyntaxError as parse_err:
                log.error(f"Syntax error parsing waiver file '{self.compile_warning_waivers_path}': {parse_err}")
                if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED
            except Exception as e:
                # Catch other potential errors during file reading/parsing/compilation
                log.error(f"Unexpected error processing waiver file '{self.compile_warning_waivers_path}': {e}")
                # Fail the job if waivers couldn't be processed correctly
                if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED

            # --- Promote unwaived warnings to errors ---
            # Only proceed if waivers were loaded/compiled without critical errors above
            if self.jobstatus == JobStatus.PASSED or self.job_lib.returncode == 0: # Check warnings even if waivers failed loading? Maybe only if returncode=0
                try:
                    log.debug(f"Scanning compile log '{self.log_path}' for warnings...")
                    unwaived_count = 0
                    first_unwaived_warning = None
                    warnings_found = 0
                    warning_regex = re.compile(base_warning_pattern)

                    with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as logp:
                        for warning_line in logp:
                            if not warning_regex.search(warning_line):
                                continue
                            warnings_found += 1
                            warning_line_stripped = warning_line.strip()
                            if warning_line_stripped and not any(
                                    waiver.search(warning_line_stripped) for waiver in warning_waivers):
                                unwaived_count += 1
                                log.warning("%s had unwaived warning: %s", self, warning_line_stripped)
                                if first_unwaived_warning is None:
                                    first_unwaived_warning = warning_line_stripped
                                if self.jobstatus == JobStatus.PASSED:
                                    self.jobstatus = JobStatus.FAILED
                                    log_level = log.error
                                    log.error("%s failed due to first unwaived warning: %s", self,
                                              first_unwaived_warning)

                    log.debug(
                        "Finished scanning log. Found %d warning lines, %d unwaived.",
                        warnings_found,
                        unwaived_count,
                    )

                except FileNotFoundError:
                    log.error(f"Compile log file disappeared unexpectedly: {self.log_path}")
                    if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED
                except Exception as e:
                    log.error(f"Unexpected error reading or parsing compile log '{self.log_path}' for warnings: {e}")
                    # Decide if failure to parse log should fail the job
                    if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED

        # --- Call superclass post_run ---
        # Call *after* determining final status based on return code and warnings
        # Do NOT pass 'completed=False' as the base class method doesn't expect it.
        try:
            super(VCompJob, self).post_run()
        except TypeError as te:
            # Catch the specific error if the base class signature changes unexpectedly
            log.error(f"Error calling super().post_run() for {self}: {te}. Base class signature might have changed.")
            # Ensure status reflects potential prior failure
            if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED
        except Exception as e:
            log.error(f"Unexpected error during super().post_run() for {self}: {e}")
            if self.jobstatus == JobStatus.PASSED: self.jobstatus = JobStatus.FAILED

        # --- Final Logging ---
        if (self.jobstatus == JobStatus.PASSED and not self.rcfg.options.no_compile and not self.compile_cache_hit):
            try:
                self.simulator.record_compile_artifacts(self)
            except (OSError, RuntimeError) as exc:
                self.jobstatus = JobStatus.FAILED
                log_level = log.error
                log.error("%s produced incomplete compile artifacts: %s", self, exc)
            if self.jobstatus == JobStatus.PASSED:
                try:
                    compile_cache.write_compile_fingerprint(self.job_dir, self.compile_fingerprint)
                except OSError as exc:
                    log.warning("Could not write compile fingerprint for %s: %s", self, exc)

        self.compile_metrics = self.simulator.collect_compile_metrics(self)

        # log_level is determined by initial return code and potential warning failures
        log_level("%s vcomp %s in %s", self.name, self.jobstatus, self.job_dir)
        simmer_results.record_compile_job(getattr(self.rcfg, "simmer_results_run", None), self)

        # Base class post_run might handle completion, but setting explicitly ensures it
        # Note: '_completed' isn't standard, jobstatus.completed is the way to check
        # self._completed = True # This line might be unnecessary if super() handles it

    def launch_failed(self, exc):
        super().launch_failed(exc)
        self.error_message = str(exc)
        simmer_results.record_compile_job(getattr(self.rcfg, "simmer_results_run", None), self)

    def post_run_failed(self, exc):
        super().post_run_failed(exc)
        simmer_results.record_compile_job(getattr(self.rcfg, "simmer_results_run", None), self)

    def __repr__(self):
        sim_name = self.simulator.get_name() if hasattr(self, 'simulator') else '???'
        return 'Vcomp("{}@{}" -> {})'.format(self.bazel_vcomp_target, sim_name, self.name) # Add simulator info


class TestJob(Job):

    LOG_NAME = 'stdout.log'

    @property
    def execution_mode(self):
        return "parallel"

    def __init__(self,
                 rcfg,
                 target,
                 vcomper: VCompJob,
                 icfg,
                 btcj,
                 simulator: SimulatorInterface,
                 iteration=None,
                 planned_seed=None): # Add simulator
        self.target = target
        name = target.split(":")[1]

        self.icfg = icfg
        self.iteration = iteration if iteration is not None else icfg.spawn_count
        if iteration is None:
            self.icfg.inc(self)
        else:
            self.icfg.jobs.append(self)
        self.btcj = btcj
        self.job_time = 0
        self.planned_seed = planned_seed

        super(TestJob, self).__init__(rcfg, name)
        self.rcfg = rcfg
        self.vcomper = vcomper
        self.simulator = simulator # Store simulator
        self.sim_opts = None
        if vcomper:
            self.add_dependency(vcomper)
        # Else expected to be added later when vcomper is set
        self._log_path = None
        self.test_name_seed = None # Initialize attribute used by VCS sim script

    def clone(self):
        # --- Ensure simulator is passed to cloned job ---
        c = TestJob(self.rcfg, self.target, self.vcomper, self.icfg, self.btcj, self.simulator)
        c.sim_opts = deepcopy(self.sim_opts)
        c.suppress_output = self.suppress_output
        return c

    def __repr__(self):
        try:
            # Add simulator name to representation
            return self.rcfg.format_test_name(self.vcomper.name,
                                              self.name,
                                              self.iteration,
                                              sim=self.simulator.get_name())
        except AttributeError:
            return self.rcfg.format_test_name("<???>", self.name, self.iteration, sim='???')

    def pre_run(self):
        log.debug("Preparing test: %s:%s (Simulator: %s)", self.vcomper.name, self.name, self.simulator.get_name())

        options = self.rcfg.options

        backend_seed = self.simulator.prepare_test_job(self)
        seed = options.seed
        if backend_seed is not None:
            seed = backend_seed
        elif self.planned_seed is not None:
            seed = self.planned_seed
        elif seed is None:
            seed = random.randint(0, (1 << 31) - 1) # xrun treats the seed as a signed integer
        self.seed = seed

        # Using the timestamp as the name uniquifier is causing issues when trying to spawn many jobs at once
        # strdate = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
        # simname = "%s__%s__%s" % (self.vcomper.name, self.name, strdate)
        simname = "%s__%s__%s__%d__i%d%s" % (self.vcomper.name, self.simulator.get_name(), self.name, seed,
                                             self.iteration, self.rcfg.options.dir_suffix)
        self.simname = simname
        self.job_dir = os.path.join(self.rcfg.regression_dir, simname)
        self._log_path = os.path.join(self.job_dir, self.LOG_NAME)
        self.timeout_start_path = os.path.join(self.job_dir, "simulation_started")

        # --- Create job directory immediately --- Required before simulator methods use it
        # Note: super().pre_run() might also try to create it, but -p makes it safe.
        # Ensure the PARENT regression directory exists first
        os.makedirs(self.rcfg.regression_dir, exist_ok=True)
        # Now create the specific job directory
        os.makedirs(self.job_dir, exist_ok=True)
        for stale_path in (self.timeout_start_path, os.path.join(self.job_dir, "simulation_duration_s")):
            try:
                os.remove(stale_path)
            except FileNotFoundError:
                pass

        # --- Super pre_run and Socket Logic ---
        super(TestJob, self).pre_run()

        sim_opts = self.simulator.generate_sim_options(self, seed)

        sockets = []
        runtime_options = self.btcj.dynamic_args(self.target)
        dynamic_simulator = runtime_options['simulator']
        if dynamic_simulator != self.simulator.get_name().upper():
            raise ValueError("Test cfg {} resolved simulator {} but simmer is running with {}.".format(
                self.target,
                dynamic_simulator,
                self.simulator.get_name().upper(),
            ))
        self.timeout = resolve_test_timeout_hours(
            runtime_options,
            options.timeout,
            getattr(options, "timeout_was_explicit", False),
        )
        log.debug("Resolved timeout for %s: %s hours", self.name, self.timeout)
        for socket_name, socket_command in runtime_options['sockets'].items():
            # While it would be nice to have the socket live in the job_dir,
            # Unfortunately, the paths are frequently too long resulting in:
            #  OSError: AF_UNIX path too long
            # As such, we'll use that name as the unique value to create hash
            socket_file = os.path.join(self.job_dir, "{}.socket".format(socket_name))
            socket_file = os.path.join("/tmp", sha1(socket_file.encode('ascii')).hexdigest())
            sim_opts += " " + shlex.join(["+SOCKET__{}={}".format(socket_name, socket_file)])
            socket_command = socket_command.replace("{socket_file}", socket_file)
            sockets.append((socket_name, socket_command, socket_file))

        # --- Add Test Name and Merge CLI/Bazel Options (Common Logic) ---
        sim_opts += " " + shlex.join(["+UVM_TESTNAME={}".format(runtime_options['uvm_testname'])])
        combined_sim_args = merge_test_runtime_sim_opts(runtime_options, options.sim_opts)
        sim_opts += ' ' + format_sim_opts_dict(combined_sim_args)
        log_check_args = format_log_check_args(runtime_options)

        pre_run_cmd = shlex.quote(runtime_options['pre_run']) if runtime_options['pre_run'] else ""

        default_capture = 'hdl_top'
        waves_db = self.job_dir

        wave_cmd_template = self.simulator.get_wave_cmd_template()
        wave_tcl_path = os.path.join(self.job_dir, "waves.tcl") # Standard name

        if options.waves is not None:
            wave_capture = self.simulator.get_wave_capture_options(self, wave_tcl_path)
            sim_opts += wave_capture['sim_opts']
            wave_tcl_path = wave_capture['wave_tcl_path']
            waves_db = wave_capture['waves_db']
            default_capture = wave_capture['default_capture']

            options.probes = options.waves if options.waves != [] else [default_capture]
            delta = " -event" if options.wave_delta else ""

            # Render the wave command template
            wave_tcl_context = {
                'options': options,
                'job': self,
                'waves_db': waves_db, # Pass the determined path
                'probes': options.probes,
                'delta': delta,
                'simulator_name': self.simulator.get_name(), # Pass simulator name
            }

            if wave_capture.get('render_template', True):
                with open(wave_tcl_path, 'w') as filep:
                    filep.write(wave_cmd_template.render(**wave_tcl_context))

        else: # No waves requested
            # Still need a basic run Tcl for -input/-do
            nwaves_tcl_path = os.path.join(self.job_dir, "nwaves.tcl")
            no_wave_capture = self.simulator.get_no_wave_capture_options(self, nwaves_tcl_path)
            sim_opts += no_wave_capture['sim_opts']
            tcl_commands = no_wave_capture['tcl_commands']
            if tcl_commands:
                with open(nwaves_tcl_path, 'w') as filep:
                    filep.write("\n".join(tcl_commands))

        sim_opts = append_uvm_control_options(sim_opts, options)
        if options.gui:
            sim_opts += self.simulator.get_gui_command_options()

        # --- Runtime Args File (Delegate path) ---
        bazel_runtime_args_file = self.vcomper.bazel_runtime_args # Get path from vcomper
        if os.path.exists(bazel_runtime_args_file):
            sim_opts += " " + shlex.join([
                "-f",
                sim_artifacts.runfiles_path(bazel_runtime_args_file, self.vcomper.bazel_runfiles_main),
            ])
        else:
            log.warning(f"Runtime args file not found: {bazel_runtime_args_file}")

        self.sim_opts = sim_opts.strip()
        log.debug("Final calculated sim opts: %s", self.sim_opts)

        # --- Get the fully constructed simulation command from the simulator object ---
        # User args ($@ in script) are typically handled by the shell automatically appending them
        # when the script is called, so we don't usually pass them here unless needed otherwise.
        # Get the path to the vcomp dir (needed for snapshot/simv path)
        vcomp_directory = self.vcomper.job_dir
        # Get the full path for the log file
        log_file_path = self._log_path # self._log_path is set earlier

        simulation_command = self.simulator.get_sim_command(
            test_job=self,
            sim_opts=self.sim_opts,
            vcomp_job_dir=vcomp_directory,
            log_path=log_file_path,
            # user_args_list=None # Or pass specific args if needed
        )
        log.debug("Full simulation command from simulator object: %s", simulation_command)

        options = self.rcfg.options
        sim_opts = self.sim_opts

        if not os.path.exists(self.job_dir):
            os.mkdir(self.job_dir)

        # --- Script Generation (Templates are now potentially simulator specific) ---
        sim_template = self.simulator.get_sim_template()
        # Rerun/Bugger templates are likely generic shell scripts
        rerun_template = RERUN_TEMPLATE

        testscript_path = os.path.join(self.job_dir, "sim.sh")
        rerun_script_path = os.path.join(self.job_dir, "rerun.sh")

        # --- Get Pre/Post Sim Commands and Working Dir ---
        sim_working_dir = self.simulator.get_sim_working_dir(self) # Get specific working dir
        pre_sim_commands = self.simulator.get_pre_sim_commands(self)
        post_sim_commands = self.simulator.get_post_sim_commands(self)

        # Common context for script rendering
        script_context = {
            'job': self, # Pass the TestJob object itself
            'options': options,
            'vcomp_dir': self.vcomper.job_dir, # Keep for reference if needed
            'sim_opts': self.sim_opts, # Pass original opts for reference if needed
            'seed': seed,
            'sockets': sockets, # Pass socket info if needed by template
            'pre_run_cmd': pre_run_cmd, # Pass pre-run command
            'simulator_name': self.simulator.get_name(),
            # --- Pass the new simulator-derived variables ---
            'sim_working_dir': sim_working_dir,
            'simulation_command': simulation_command, # The full command string
            'pre_sim_commands': pre_sim_commands,
            'post_sim_commands': post_sim_commands,
            # ---
            # Add test_name_seed specifically for VCS template if needed
            'test_name_seed': getattr(self, 'test_name_seed', None),
            'check_test_path': shlex.quote(sim_artifacts.find_bazel_executable(self.rcfg.proj_dir, "check_test")),
            'log_check_args': log_check_args,
        }

        # Render sim.sh
        sim_artifacts.write_executable_script(testscript_path, sim_template.render(**script_context))
        log.debug('Created %s', testscript_path)

        # Render rerun.sh
        sim_artifacts.write_executable_script(
            rerun_script_path,
            rerun_template.render(
                project_dir=shlex.quote(self.rcfg.proj_dir),
                rerun_target=shlex.quote(self.target),
                seed=seed,
                reproduce_args=shlex.join(options.reproduce_args),
            ))
        log.debug('Created %s', rerun_script_path)

        # Create a symlink back the vcomp directory for easy reference
        replace_symlink(os.path.join(self.job_dir, '.vcomp'), self.vcomper.job_dir)

        if not self.rcfg.tidy:
            # Use relative path for symlink for portability
            last_sim_link_target = os.path.relpath(self.job_dir, start=os.getcwd())
            replace_symlink(".last_sim", last_sim_link_target)
            log.debug("Created link to sim dir as '.last_sim'")

        self.main_cmdline = shlex.join(['/usr/bin/env', 'bash', testscript_path])

    def post_run(self):
        options = self.rcfg.options
        run_wave_script_path = None
        abs_wave_path = None
        super(TestJob, self).post_run()

        # Parse file for duration
        net_time_str, cps_str = self._get_stats_from_log_file()
        self.simulation_duration_s = self._read_simulation_duration()
        self.job_time = self.simulation_duration_s or 0
        sim_time_str = self._format_duration(self.job_time)
        total_time_str = self._get_total_time_str()
        time_stats_str = "({} cps / {} net_time / {} sim_time / {} total_time)".format(
            cps_str, net_time_str, sim_time_str, total_time_str)

        if self.job_lib.returncode != 0:
            # Use relative path for symlink for portability
            last_fail_link_target = os.path.relpath(self.job_dir, start=os.getcwd())
            replace_symlink(".last_fail", last_fail_link_target)

            log.debug("Created link to sim dir as '.last_fail'")
            log.error(
                "%s %s",
                self.rcfg.table_format(self.vcomper.name,
                                       self.name + ' ' + str(self.iteration),
                                       "FAILED {}".format(time_stats_str),
                                       indent=''), self._log_path)
            self.jobstatus = JobStatus.FAILED

            # Error message reading remains the same
            err_file_path = os.path.join(self.job_dir, "{}.err".format(self.LOG_NAME))
            if os.path.exists(err_file_path):
                with open(err_file_path) as errors:
                    self.error_message = errors.read()
            else:
                self.error_message = f"Sim failed (return code {self.job_lib.returncode}), no {self.LOG_NAME}.err found."
        else: # PASSED
            if self.rcfg.tidy:
                log_path = ""
            else:
                log_path = self._log_path
            log.info(
                "%s %s",
                self.rcfg.table_format(self.vcomper.name,
                                       self.name + ' ' + str(self.iteration),
                                       "PASSED {} {}".format(time_stats_str,
                                                             datetime.datetime.now().strftime("%H:%M:%S")),
                                       indent=''), log_path)
            self.jobstatus = JobStatus.PASSED
            self.error_message = None
            if not os.path.exists(self._log_path):
                self.log.error("%s completed without simulation log %s", self, self._log_path)
                self.jobstatus = JobStatus.FAILED
                self.error_message = "Simulation completed without producing {}.".format(self._log_path)

        if self.jobstatus == JobStatus.FAILED:
            self.simulator.cleanup_test_coverage(self)

        # Wave path logging (adjust based on actual file names if they differ)
        if options.waves is not None:
            wave_path = self.job_dir
            abs_wave_path = self.simulator.get_wave_artifact_path(wave_path, options.wave_type)

            if os.path.exists(abs_wave_path):
                try:
                    os.chmod(abs_wave_path, 0o755)
                except OSError as exc:
                    log.debug("Could not chmod wave artifact %s: %s", abs_wave_path, exc)
            else:
                log.error("Dumped waves, but waves file doesn't exist.")

            # Create the bash scripts using Jinja2 template
            run_wave_script_name = "run_waves.sh"
            run_wave_script_path = os.path.join(wave_path, run_wave_script_name)

            bazel_runfiles_dir = os.path.join(wave_path, 'bazel_runfiles_main')
            absolute_wave_path = os.path.abspath(abs_wave_path)

            # Variables needed by the template
            run_wave_template_vars = {
                "job_dir": wave_path,
                "wave_file_path": absolute_wave_path,
                "bazel_runfiles_dir": bazel_runfiles_dir,
                "wave_view_command": shlex.quote(self.simulator.get_wave_view_command(absolute_wave_path, wave_path)),
            }
            run_wave_script_content = RUN_WAVE_TEMPLATE.render(run_wave_template_vars)
            sim_artifacts.write_executable_script(run_wave_script_path, run_wave_script_content)
            log.info(f"Run wave: {run_wave_script_path}")

        sys.stdout.flush()
        simmer_results.record_test_job(
            getattr(self.rcfg, "simmer_results_run", None),
            self,
            waves_script=run_wave_script_path,
            waves_path=abs_wave_path,
        )

        if self.rcfg.tidy and self.jobstatus.successful:
            log.debug("tidy=%s removing %s", self.rcfg.tidy, self.job_dir)
            shutil.rmtree(self.job_dir, ignore_errors=True)
            if os.path.exists(".last_sim"):
                os.remove(".last_sim")

        if self.simulator.should_spawn_test_job(self):
            self.job_lib.manager.add_job(self.clone())

    def launch_failed(self, exc):
        super().launch_failed(exc)
        self.error_message = str(exc)
        self.simulation_duration_s = None
        simmer_results.record_test_job(getattr(self.rcfg, "simmer_results_run", None), self)

    def post_run_failed(self, exc):
        super().post_run_failed(exc)
        self.simulation_duration_s = None
        simmer_results.record_test_job(getattr(self.rcfg, "simmer_results_run", None), self)

    @staticmethod
    def _format_duration(duration_s):
        hours = int(duration_s // 3600)
        minutes = int((duration_s % 3600) // 60)
        seconds = int(duration_s % 60)
        return "{:0d}:{:02d}:{:02d}".format(hours, minutes, seconds)

    def _get_total_time_str(self):
        return self._format_duration(self.duration_s)

    def _get_job_time_str(self):
        return self._format_duration(self.job_time)

    def _read_simulation_duration(self):
        path = os.path.join(self.job_dir, "simulation_duration_s")
        try:
            with open(path, "r", encoding="utf-8") as filep:
                duration = int(filep.read().strip())
            return duration if duration >= 0 else None
        except (OSError, ValueError):
            return None

    def _get_stats_from_log_file(self):
        if not os.path.exists(self._log_path):
            return '???', '???'
        stats_re = re.compile(
            r'.*Test Duration: (?P<duration>[0-9]+:[0-9]+:[0-9]+).*Average cycles/sec: (?P<cps>[0-9]+\.[0-9]+).*')
        with open(self._log_path, 'r', encoding="utf8", errors='ignore') as log_file:
            for line in log_file:
                match = stats_re.match(line)
                if match:
                    h, m, s = map(int, match.group('duration').split(':'))
                    self.net_time = 3600 * h + 60 * m + s
                    return match.group('duration'), match.group('cps')
        return '???', '???'

    @property
    def log_path(self):
        if self.jobstatus.completed:
            return self._log_path
        else:
            return "<incomplete>"


def main(rcfg, options):
    """
    Parameters
    ----------
    rcfg : RegressionConfig
         The main configuration knob for the regression
    options: argparse.Namespace
         Parsed command-line options
    """
    uname = os.uname()
    rcfg.log.info("Running on %s", uname[1])
    resolve_run_simulator(rcfg, options)

    # --- Instantiate the selected simulator ---
    try:
        # Pass the global Jinja environment.
        simulator = get_simulator(options, rcfg, jinja2_env)
        simulator.validate_resolved_options()
        simulator.validate_run_options(len(rcfg.all_vcomp))
        rcfg.log.info("Using Simulator: %s", simulator.get_name().upper())
    except ValueError as e:
        rcfg.log.critical(str(e))
        sys.exit(1)
    # ---

    vcomp_jobs = {}
    btcj_jobs = []
    btbj_jobs = []
    trd = []
    webroot_path = options.report_dir
    dynamic_test_plan = simulator.uses_dynamic_test_plan()
    workflow_finalize_failed = False
    coverage_merge_failed = False

    rcfg.all_vcomp = seed_plan.ordered_regression_tests(rcfg.all_vcomp)
    planned_seeds = {}
    if not dynamic_test_plan and options.seed is None:
        planned_seeds = seed_plan.plan_test_seeds(rcfg.all_vcomp, options.python_seed)
    if options.python_seed is not None:
        log.info("Set python random seed to %s", options.python_seed)

    for vcomp, test_list in rcfg.all_vcomp.items():
        vcomper = VCompJob(rcfg, vcomp, simulator)
        vcomp_jobs[vcomp] = vcomper

        btbj = job_lib.BazelTBJob(rcfg, vcomp, vcomper)
        btbj_jobs.append(btbj)

        tests = []
        icfgs = []
        btcj = job_lib.BazelTestCfgJob(rcfg, test_list.keys(), vcomper)
        btcj_jobs.append(btcj)
        for test, iterations in test_list.items():
            icfg = rv_utils.IterationCfg(iterations)
            icfgs.append(icfg)

            planned_iterations = [None] if dynamic_test_plan else range(1, iterations + 1)
            for iteration in planned_iterations:
                planned_seed = None
                if not dynamic_test_plan and options.seed is None:
                    planned_seed = planned_seeds[(vcomp, test, iteration)]
                t = TestJob(rcfg,
                            test,
                            vcomper=vcomper,
                            icfg=icfg,
                            btcj=btcj,
                            simulator=simulator,
                            iteration=iteration,
                            planned_seed=planned_seed)
                tests.append(t)
                t.add_dependency(btcj)

        rcfg.all_vcomp[vcomp] = (icfgs, tests)

    workflow_jobs = simulator.create_regression_jobs(vcomp_jobs)

    suppress_via_vcomp_jobs = False
    if len(vcomp_jobs) > 1:
        [setattr(vj, 'suppress_output', True) for vj in vcomp_jobs.values()]
        suppress_via_vcomp_jobs = True
        log.info("Suppressing output due to multiple vcomp begin run")

    total_tests = sum([icfg.target for _, (icfgs, _) in rcfg.all_vcomp.items() for icfg in icfgs])
    if total_tests > 1:
        if options.gui:
            rcfg.log.critical("--gui can only be used on one test at a time")
            sys.exit(1)
        if options.seed is not None:
            rcfg.log.critical("--seed can only be used if a single test is run")
            sys.exit(1)
    rcfg.simmer_results_run = None
    if not options.no_run:
        rcfg.simmer_results_run = simmer_results.create_run(
            getattr(options, "simmer_argv", sys.argv),
            rcfg,
            total_tests,
        )

    try:
        jm_opts = {
            'idle_print_seconds': options.idle_print_seconds,
            'quit_count': options.quit_count,
            'active_job_limit': get_active_job_limit(options, rcfg, simulator),
        }
        jm = job_lib.JobManager(jm_opts, log)

        for job in btbj_jobs:
            if options.no_compile or options.no_bazel:
                job.jobstatus = JobStatus.TO_BE_BYPASSED
            jm.add_job(job)

        for vcomp, vcomper in vcomp_jobs.items():
            if options.no_compile:
                vcomper.jobstatus = JobStatus.TO_BE_BYPASSED
            jm.add_job(vcomper)

        for workflow_job in workflow_jobs:
            jm.add_job(workflow_job)

        for btcj in btcj_jobs:
            if options.no_run:
                btcj.jobstatus = JobStatus.TO_BE_BYPASSED
            elif options.no_bazel:
                btcj.jobstatus = JobStatus.TO_BE_BYPASSED
                jm.add_job(btcj)
            else:
                jm.add_job(btcj)

        for vcomp, (icfgs, test_list) in rcfg.all_vcomp.items():
            tests = test_list
            suppress_via_tests = False
            if len(tests) > 1:
                if options.gui:
                    rcfg.log.critical("--gui can only be used on one bench/test at a time")
                if options.seed:
                    rcfg.log.critical("--seed can only be used on one bench/test at a time")
                    sys.exit(1)
                log.info("Suppressing output due to multiple tests begin run")
                suppress_via_tests = True

            [setattr(t, 'suppress_output', suppress_via_tests or suppress_via_vcomp_jobs) for t in tests]

            for test in tests:
                if options.no_run:
                    test.jobstatus = JobStatus.TO_BE_BYPASSED
                elif not dynamic_test_plan:
                    jm.add_job(test)

        jm.wait()
        jm.stop()
        if options.no_run:
            rcfg.log.info("run_test:main(): --no_run option selected, exiting")

    except KeyboardInterrupt:
        log.info("Saw keyboard interrupt, attempting to shutdown jobs.")
        jm.kill()
        log.critical("Exiting due to keyboard interrupt")

    workflow_finalize_failed = False
    regression_log_path = None
    post_processing_complete = False
    total_failures = 0
    try:
        workflow_finalize_failed = simulator.finalize_regression_workflow()
        regression_log_path = rv_utils.print_summary(rcfg, vcomp_jobs, jm, trd)

        category_stats = None
        if options.category_cfg is not None:
            category_stats = rv_utils.calc_category_stats(rcfg)
            rv_utils.print_category_summary(category_stats, rcfg.log, rv_utils.LOGGER_INDENT)

        report_header = {}
        if options.report:
            if simulator.coverage_enabled():
                coverage_merge_failed = rcfg._profile_step(
                    "coverage_merge",
                    "merge simulator coverage databases",
                    lambda: simulator.run_report_coverage_merge(vcomp_jobs),
                )

            report_header = rv_utils.get_report_header(rcfg)
            rrt = regression_report.RegressionReport(rcfg, report_jinja2_env, webroot_path)
            report_root = os.path.join(webroot_path, "regression_report")
            project_lock_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", report_header['project_name'])
            project_lock_path = os.path.join(report_root, ".{}.lock".format(project_lock_name))
            index_lock_path = os.path.join(report_root, ".index.lock")
            os.makedirs(report_root, exist_ok=True)
            rrt.prepare(report_header, trd, simulator.collect_coverage_data(vcomp_jobs), category_stats)
            with open(project_lock_path, "w") as report_lock:
                import fcntl
                fcntl.flock(report_lock, fcntl.LOCK_EX)
                rrt.render_regression_page()
            with open(index_lock_path, "w") as report_lock:
                fcntl.flock(report_lock, fcntl.LOCK_EX)
                rrt.render_bench_page()
                rrt.render_home_page()

        rv_utils.print_simmer_profile(rcfg, jm)

        failures = {}
        for bench, (icfgs, test_list) in rcfg.all_vcomp.items():
            failures[bench] = sum([j.jobstatus == JobStatus.FAILED for icfg in icfgs for j in icfg.jobs])
            if options.report:
                report_path = os.path.join(report_root, report_header['project_name'],
                                           bench.split(":")[1], "index.html")
                report_url = os.environ.get("SIMMER_REPORT_URL")
                if report_url:
                    log.info("Report at: %s/%s/%s", report_url.rstrip("/"), report_header['project_name'],
                             bench.split(":")[1])
                else:
                    log.info("Report at: %s", report_path)

        for message in getattr(rcfg, "deferred_messages", []):
            log.info(message)

        simulator.cleanup_shared_runtime_artifacts(vcomp_jobs)
        total_failures = sum(failures.values())
        post_processing_complete = True
        rcfg.log.exit_if_warnings_or_errors("Previous errors")
    finally:
        if getattr(rcfg, "simmer_results_run", None) is not None:
            simmer_results.finalize_run(
                rcfg.simmer_results_run,
                regression_log_path=regression_log_path,
                backend_finalize_failed=(workflow_finalize_failed or coverage_merge_failed
                                         or not post_processing_complete
                                         or bool(rcfg.log.warn_count or rcfg.log.error_count)),
            )
            try:
                simmer_results.save_run(rcfg.proj_dir, rcfg.simmer_results_run)
            except OSError as exc:
                log.error("Failed to write simmer results: %s", exc)

    if workflow_finalize_failed or coverage_merge_failed:
        log.info("Exiting with status 1 due to backend finalization or coverage merge failure.")
        sys.exit(1)
    if total_failures > 0:
        log.info(f"Exiting with status 1 due to {total_failures} test failure(s).")
        sys.exit(1)
    else:
        log.info("All tests passed.")
        sys.exit(0)


if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    if options.history is not None:
        history_use_color = True if options.use_color else None
        simmer_results.print_history(options.proj_dir, options.history, use_color=history_use_color)
        sys.exit(0)
    options.simmer_argv = sys.argv[:]
    verbosity = cmn_logging.DEBUG if options.tool_debug else cmn_logging.INFO
    log = cmn_logging.build_logger("sim", level=verbosity, use_color=options.use_color, filehandler="simmer.log")
    rcfg = regression.RegressionConfig(options, log)
    main(rcfg, options)
