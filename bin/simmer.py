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
import shutil
import stat
import subprocess

################################################################################
# Bigger libraries (better to place these later for dependency ordering
import jinja2

# Determine the absolute path to the directory containing this script
dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.dirname(__file__))

################################################################################
# rules_verilog lib imports
from args_parser import parse_args
from args_parse.vcs import validate_vcs_runtime_options, validate_vcs_switches_for_xcelium
from args_parse.xcelium import validate_xcelium_runtime_options, validate_xcelium_switches_for_vcs
from lib.job_lib import Job, JobStatus
from lib import cmn_logging
from lib import job_lib
from lib import regression
from lib import rv_utils
from lib.runtime_options import (
    format_sim_opts_dict,
    merge_test_runtime_sim_opts,
    resolve_test_timeout_hours,
)
from lib.simulators.base import SimulatorInterface
from lib.simulators.xcelium import XceliumSimulator
from lib.simulators.vcs import VcsSimulator
from lib import regression_report

log = None

# Use the absolute path to locate the 'templates' directory
file_loader = jinja2.FileSystemLoader(searchpath=os.path.join(dir_path, 'templates'))
jinja2_env = jinja2.Environment(loader=file_loader)

#XRUN_COMPILE_TEMPLATE = jinja2_env.get_template('xrun_compile_template.sh.j2')
#VCS_COMPILE_TEMPLATE = jinja2_env.get_template('vcs_compile_template.sh.j2')
#SIM_TEMPLATE = jinja2_env.get_template('sim_template.sh.j2')
RERUN_TEMPLATE = jinja2_env.get_template('rerun_template.sh.j2')
RUN_WAVE_TEMPLATE = jinja2_env.get_template('run_waves_template.sh.j2')

# Get the path from the environment variable EMU_JINJA2_PATH
# xrun_emu_compile_template.sh.j2 located here
emu_template_path = os.getenv('EMU_JINJA2_PATH')


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
                is_re_compile = (
                    isinstance(item.func.value, ast.Name) and
                    item.func.value.id == 're' and
                    item.func.attr == 'compile'
                )
                has_string_arg = item.args and isinstance(item.args[0], ast.Constant) and isinstance(item.args[0].value, str)
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


# --- Simulator Factory Function ---
def get_simulator(options, rcfg, jinja_env) -> SimulatorInterface:
    """Instantiates and returns the correct simulator object."""
    sim_name = options.simulator.lower()
    if sim_name == 'xrun':
        # Pass options, rcfg, and jinja env to the constructor
        return XceliumSimulator(options, rcfg, jinja_env)
    elif sim_name == 'vcs':
        return VcsSimulator(options, rcfg, jinja_env)
    # Add elif for other simulators here
    # elif sim_name == 'questa':
    #    from lib.simulators.questa import QuestaSimulator
    #    return QuestaSimulator(options, rcfg, jinja_env)
    else:
        raise ValueError(f"Unsupported simulator specified: {options.simulator}")


class _ValidationErrorParser:

    def error(self, message):
        raise ValueError(message)


def validate_resolved_simulator_options(options):
    parser = _ValidationErrorParser()
    if options.simulator == 'VCS':
        validate_xcelium_switches_for_vcs(options, parser)
        validate_vcs_runtime_options(options, parser)
        return

    if options.simulator == 'XRUN':
        validate_vcs_switches_for_xcelium(options, parser)
        validate_xcelium_runtime_options(options, parser)
        return

    raise ValueError("Unsupported simulator specified: {}".format(options.simulator))


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

    try:
        validate_resolved_simulator_options(options)
    except ValueError as exc:
        rcfg.log.critical("%s", exc)
        sys.exit(1)

    return resolved_simulator


def get_active_job_limit(options, rcfg):
    total_tests = sum(
        icfg.target
        for _, (icfgs, _) in rcfg.all_vcomp.items()
        for icfg in icfgs
    )
    if total_tests <= 1:
        return 1

    if options.gui:
        return 1

    if options.simulator == 'VCS':
        cpu_count = os.cpu_count() or 1
        return max(1, min(total_tests, cpu_count))

    return 1


def path_from_sim_root(path, bazel_runfiles_main):
    abs_path = os.path.abspath(path)
    abs_runfiles = os.path.abspath(bazel_runfiles_main)
    try:
        rel_path = os.path.relpath(abs_path, abs_runfiles)
    except ValueError:
        return path

    if rel_path.startswith(".."):
        return path

    return os.path.join("bazel_runfiles_main", rel_path).replace("\\", "/")


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

        self.job_dir = self.simulator.get_vcomp_job_dir(os.path.join(self.rcfg.regression_dir, job_dir))
        self.log_path = os.path.join(self.job_dir, "cmp.log")

        self.main_cmdline = None
        self.cov_work_dir = None

    def pre_run(self):
        super(VCompJob, self).pre_run()

        options = self.rcfg.options
        debug_mode = "default"
        if options.waves is not None:
            debug_mode = "waves"
        if options.gui:
            debug_mode = "gui"

        compile_gen_opts = self.simulator.generate_compile_options(self)
        cov_opts = compile_gen_opts['cov_opts']
        xprop_cmd = compile_gen_opts['xprop_cmd']
        additional_defines = compile_gen_opts['additional_defines']

        log.debug("workdir = %s", self.job_dir)

        if options.lmstat:
            with open("lmstat.out", "w") as lmstat_out:
                subprocess.run(["lmstat", "-a"], stdout=lmstat_out, stderr=subprocess.STDOUT, check=False)
        else:
            log.debug("Skipping lmstat -a")

        with open(os.path.join(self.job_dir, 'env.out'), 'w') as env_out:
            for key, value in sorted(os.environ.items()):
                env_out.write("{}={}\n".format(key, value))
        with open(os.path.join(self.job_dir, 'hostname.out'), 'w') as hostname_out:
            subprocess.run(["hostname"], stdout=hostname_out, stderr=subprocess.STDOUT, check=False)

        if options.compile_args_file and not os.path.exists(options.compile_args_file):
            self.rcfg.log.critical(f"The specified compile arguments file does not exist: {options.compile_args_file}")
            sys.exit(1)

        if options.recompile:
            log.info("Removing vcomp library %s due to --recompile flag", self.job_dir)
            shutil.rmtree(self.job_dir, ignore_errors=True)
            os.makedirs(self.job_dir, exist_ok=True)

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
        # RTL file list for Emu (if needed by template, keep calculation here or move to simulator)
        self.bazel_compile_args_emu_rtl = os.path.join(self.bazel_runfiles_main, relpath,
                                                       "{}_rtl_compile_args".format(bazel_target))

        # --- Template Rendering ---
        vcomp_sh_path = os.path.join(self.job_dir, "vcomp.sh")
        compile_template = self.simulator.get_compile_template(self)

        # Determine tb_name (used in some templates) - extract from first test?
        # This assumes all tests under a vcomp target share the same tb_name base
        tb_name = "unknown_tb"

        if options.tests:
            # format like: //path/to/bench:test_name
            first_test_target = options.tests[0].btiglob if options.tests[0].btiglob else options.tests[0].name
            tb_name_match = re.match(r'//([^:]+):', first_test_target)
            if tb_name_match:
                tb_name = os.path.basename(tb_name_match.group(1))

        template_context = {
            'VCOMP_DIR': self.job_dir,
            'cov_opts': cov_opts,
            'bazel_runfiles_main': self.bazel_runfiles_main,
            'bazel_compile_args': self.bazel_compile_args,
            'bazel_compile_args_rtl': self.bazel_compile_args_emu_rtl, # Pass even if not used by all templates
            'debug_mode': debug_mode,
            'xprop_cmd': xprop_cmd,
            'relpath': relpath,
            'tb_name': tb_name, # Pass derived tb_name
            'additional_defines': additional_defines,
            'options': options, # Pass full options object
            # Add simulator name if needed in template
            'simulator_name': self.simulator.get_name(),
        }

        with open(vcomp_sh_path, 'w') as filep:
            filep.write(compile_template.render(**template_context))

        # Make executable
        st = os.stat(vcomp_sh_path)
        os.chmod(vcomp_sh_path, st.st_mode | stat.S_IEXEC)

        log.debug("bazel_runfiles_main: %s", self.bazel_runfiles_main)

        if self.rcfg.options.no_compile:
            self.simulator.validate_reusable_compile_artifacts(self)
            self.main_cmdline = "echo \"Bypassing {} due to --no-compile\"".format(self)
        else:
            self.main_cmdline = "bash {}".format(vcomp_sh_path)

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

                    with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as logp:
                        text = logp.read()
                        # Find all lines matching the base warning pattern
                        warnings_found = re.findall(base_warning_pattern, text, re.MULTILINE)
                        log.debug(f"Found {len(warnings_found)} lines matching base warning pattern.")

                        for warning_line in warnings_found: # Iterate through full lines found
                            waived = False
                            # Strip leading/trailing whitespace for comparison
                            warning_line_stripped = warning_line.strip()
                            if not warning_line_stripped: continue # Skip empty lines if captured

                            # Check against each compiled waiver regex
                            for ww_regex in warning_waivers: # ww_regex is a compiled re.Pattern object
                                # Use re.search() to find the pattern ANYWHERE in the stripped line
                                log.debug(
                                    f"Checking line '{warning_line_stripped}' against pattern '{ww_regex.pattern}'"
                                ) # DEBUG PRINT
                                if ww_regex.search(warning_line_stripped):
                                    waived = True
                                    log.debug(f"  --> Waived.")
                                    break # Found a match, stop checking waivers for this line

                            if not waived:
                                unwaived_count += 1
                                log.warning("%s had unwaived warning: %s", self,
                                            warning_line_stripped) # Log as warning first
                                if first_unwaived_warning is None:
                                    first_unwaived_warning = warning_line_stripped
                                # If this is the first unwaived warning found, mark job as failed
                                if self.jobstatus == JobStatus.PASSED:
                                    self.jobstatus = JobStatus.FAILED
                                    log_level = log.error # Change subsequent log level
                                    log.error("%s failed due to first unwaived warning: %s", self,
                                              first_unwaived_warning)

                    log.debug(f"Finished scanning log. Found {unwaived_count} unwaived warning lines.")

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
        # log_level is determined by initial return code and potential warning failures
        log_level("%s vcomp %s in %s", self.name, self.jobstatus, self.job_dir)

        # Base class post_run might handle completion, but setting explicitly ensures it
        # Note: '_completed' isn't standard, jobstatus.completed is the way to check
        # self._completed = True # This line might be unnecessary if super() handles it

    def __repr__(self):
        sim_name = self.simulator.get_name() if hasattr(self, 'simulator') else '???'
        return 'Vcomp("{}@{}" -> {})'.format(self.bazel_vcomp_target, sim_name, self.name) # Add simulator info


class TestJob(Job):

    LOG_NAME = 'stdout.log'

    @property
    def execution_mode(self):
        return "parallel"

    class RegexWrap():

        def __init__(self):
            self.match = None

        def search(self, regex, line):
            self.match = re.search(regex, line)
            return self.match

    def __init__(self, rcfg, target, vcomper: VCompJob, icfg, btcj, simulator: SimulatorInterface): # Add simulator
        self.target = target
        name = target.split(":")[1]

        self.icfg = icfg
        self.iteration = icfg.spawn_count
        self.icfg.inc(self)
        self.btcj = btcj
        self.job_time = 0

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

    def _flatten_test_cfg(self, path):
        flattened = []
        with open(path) as filep:
            rw = self.RegexWrap()
            for line in filep.readlines():
                if rw.search(r'^<INCLUDE>(.*)', line):
                    include = rw.match.group(1).strip()
                    include = os.path.join(os.path.dirname(path), include)
                    flattened.append("# Jumping into {}\n".format(include))
                    flattened.extend(self._flatten_test_cfg(include))
                    flattened.append("# Popping back from {}\n".format(include))
                else:
                    flattened.append(line)
        return flattened

    def pre_run(self):
        log.debug("Preparing test: %s:%s (Simulator: %s)", self.vcomper.name, self.name, self.simulator.get_name())

        options = self.rcfg.options
        vcomp_dir = self.vcomper.job_dir

        seed = options.seed
        if seed is None:
            seed = random.randint(0, 1 << (32 - 1)) # xrun is treating the seed as a signed integer

        # Using the timestamp as the name uniquifier is causing issues when trying to spawn many jobs at once
        # strdate = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
        # simname = "%s__%s__%s" % (self.vcomper.name, self.name, strdate)
        simname = "%s__%s__%s__%d%s" % (self.vcomper.name, self.simulator.get_name(), self.name, seed,
                                        self.rcfg.options.dir_suffix)
        self.simname = simname
        self.job_dir = os.path.join(self.rcfg.regression_dir, simname)
        self._log_path = os.path.join(self.job_dir, self.LOG_NAME)

        # --- Create job directory immediately --- Required before simulator methods use it
        # Note: super().pre_run() might also try to create it, but -p makes it safe.
        # Ensure the PARENT regression directory exists first
        os.makedirs(self.rcfg.regression_dir, exist_ok=True)
        # Now create the specific job directory
        os.makedirs(self.job_dir, exist_ok=True)

        # --- Super pre_run and Socket Logic ---
        super(TestJob, self).pre_run()

        sim_opts = self.simulator.generate_sim_options(self, seed)

        sockets = []
        runtime_options = self.btcj.dynamic_args()
        dynamic_simulator = runtime_options['simulator']
        if dynamic_simulator != self.simulator.get_name().upper():
            raise ValueError(
                "Test cfg {} resolved simulator {} but simmer is running with {}.".format(
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
            sim_opts += " +SOCKET__{}={}".format(socket_name, socket_file)
            socket_command = socket_command.format(socket_file=socket_file)
            sockets.append((socket_name, socket_command, socket_file))

        # --- Add Test Name and Merge CLI/Bazel Options (Common Logic) ---
        sim_opts += " +UVM_TESTNAME={uvm_testname} ".format(uvm_testname=runtime_options['uvm_testname'], )
        combined_sim_args = merge_test_runtime_sim_opts(runtime_options, options.sim_opts)
        sim_opts += ' ' + format_sim_opts_dict(combined_sim_args)

        pre_run_cmd = runtime_options['pre_run']

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

        if options.uvm_set_int:
            sim_opts += ' +uvm_set_config_int=' + ' +uvm_set_config_int='.join(options.uvm_set_int)
        if options.uvm_set_str:
            sim_opts += ' +uvm_set_config_string=' + ' +uvm_set_config_string='.join(options.uvm_set_str)
        if options.sim_opts_file:
            with open(options.sim_opts_file, 'r') as sim_opts_file:
                for line in sim_opts_file:
                    sim_opts += ' ' + line.strip()

        if options.verbosity:
            if 'UVM_VERBOSITY' not in sim_opts:
                sim_opts += ' +UVM_VERBOSITY=' + options.verbosity
                if options.verbosity == 'UVM_DEBUG':
                    sim_opts += " +UVM_TR_RECORD +UVM_LOG_RECORD "
            else:
                sim_opts = re.sub(r' \+UVM_VERBOSITY=[A-Z_]+', ' +UVM_VERBOSITY=' + options.verbosity, sim_opts)
        else:
            if 'UVM_VERBOSITY' not in sim_opts:
                sim_opts += ' +UVM_VERBOSITY=UVM_MEDIUM'
        if options.uvm_config_db_trace:
            sim_opts += ' +UVM_CONFIG_DB_TRACE'
        if options.uvm_resource_db_trace:
            sim_opts += ' +UVM_RESOURCE_DB_TRACE'
        if options.uvm_max_quit_count:
            sim_opts += ' +UVM_MAX_QUIT_COUNT={}'.format(options.uvm_max_quit_count)
        if options.uvm_set_verbosity:
            sim_opts += ' +uvm_set_verbosity=' + ' +uvm_set_verbosity='.join(options.uvm_set_verbosity)
        if options.uvm_set_config_int:
            sim_opts += ' +uvm_set_config_int=' + ' +uvm_set_config_int='.join(options.uvm_set_config_int)
        if options.uvm_set_config_string:
            sim_opts += ' +uvm_set_config_string=' + ' +uvm_set_config_string='.join(options.uvm_set_config_string)
        if options.gui:
            sim_opts += self.simulator.get_gui_command_options()

        # --- Runtime Args File (Delegate path) ---
        bazel_runtime_args_file = self.vcomper.bazel_runtime_args # Get path from vcomper
        if os.path.exists(bazel_runtime_args_file):
            sim_opts += " -f {} ".format(
                path_from_sim_root(bazel_runtime_args_file, self.vcomper.bazel_runfiles_main)
            )
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
        }

        # Render sim.sh
        with open(testscript_path, 'w') as filep:
            filep.write(sim_template.render(**script_context))
        os.chmod(testscript_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH) # 755
        log.debug('Created %s', testscript_path)

        # Render rerun.sh
        with open(rerun_script_path, 'w') as filep:
            tmp = locals()
            del tmp['self']
            tmp['job'] = self
            cmd_line_sim_opts = ""
            if options.sim_opts_file:
                with open(options.sim_opts_file, 'r') as sim_opts_file:
                    for line in sim_opts_file:
                        cmd_line_sim_opts += ' ' + line.strip()
            if options.sim_opts:
                cmd_line_sim_opts += ' ' + (' '.join(options.sim_opts)).replace('\"', ' ')
            if cmd_line_sim_opts:
                cmd_line_sim_opts = "--sim-opts \"{}\"".format(cmd_line_sim_opts.lstrip())
            tmp['cmd_line_sim_opts'] = cmd_line_sim_opts
            filep.write(rerun_template.render(**tmp))
        os.chmod(rerun_script_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH) # 755
        log.debug('Created %s', rerun_script_path)

        # Create a symlink back the vcomp directory for easy reference
        replace_symlink(os.path.join(self.job_dir, '.vcomp'), self.vcomper.job_dir)

        if not self.rcfg.tidy:
            # Use relative path for symlink for portability
            last_sim_link_target = os.path.relpath(self.job_dir, start=os.getcwd())
            replace_symlink(".last_sim", last_sim_link_target)
            log.debug("Created link to sim dir as '.last_sim'")

        self.main_cmdline = '/usr/bin/env bash %s' % (testscript_path)

    def post_run(self):
        super(TestJob, self).post_run()

        # Parse file for duration
        net_time_str, cps_str = self._get_stats_from_log_file()
        total_time_str = self._get_total_time_str()
        time_stats_str = "({} cps / {} net_time / {} total_time)".format(cps_str, net_time_str, total_time_str)
        self.job_time = int(self.duration_s)

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

        # Wave path logging (adjust based on actual file names if they differ)
        if options.waves is not None:
            wave_path = self.job_dir
            abs_wave_path = self.simulator.get_wave_artifact_path(wave_path, options.wave_type)

            if os.path.exists(abs_wave_path):
                #log.info("Waves available: {}".format(abs_wave_path))
                subprocess.run(["chmod", "-R", "755", abs_wave_path], check=False)
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
                "wave_view_command": self.simulator.get_wave_view_command(absolute_wave_path, wave_path),
            }
            run_wave_script_content = RUN_WAVE_TEMPLATE.render(run_wave_template_vars)

            with open(run_wave_script_path, 'w') as f:
                f.write(run_wave_script_content)

            os.chmod(run_wave_script_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
            log.info(f"Run wave: {run_wave_script_path}")

        sys.stdout.flush()

        if self.rcfg.tidy and self.jobstatus.successful:
            log.debug("tidy=%s removing %s", self.rcfg.tidy, self.job_dir)
            shutil.rmtree(self.job_dir, ignore_errors=True)
            if os.path.exists(".last_sim"):
                os.remove(".last_sim")

        # If iteration count hasnt been hit yet, add another copy onto the run list
        if self.icfg.spawn_count <= self.icfg.target:
            log.debug(f"Spawning next iteration for {self.name} ({self.icfg.spawn_count}/{self.icfg.target})")
            c = self.clone()
            self.job_lib.manager.add_job(c)
        elif self.icfg.spawn_count == self.icfg.target:
            log.debug(f"Target iterations reached for {self.name} ({self.icfg.target})")

    def _get_total_time_str(self):
        hours = int(self.duration_s // 3600)
        minutes = int((self.duration_s % 3600) // 60)
        seconds = int(self.duration_s % 60)
        return "{:0d}:{:02d}:{:02d}".format(hours, minutes, seconds)

    def _get_stats_from_log_file(self):
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
    resolved_simulator = resolve_run_simulator(rcfg, options)
    rcfg.log.info("Resolved simulator for this run: %s", resolved_simulator.upper())

    # --- Instantiate the selected simulator ---
    try:
        # Pass the global Jinja environment.
        simulator = get_simulator(options, rcfg, jinja2_env)
        rcfg.log.info("Using Simulator: %s", simulator.get_name().upper())
    except ValueError as e:
        rcfg.log.critical(str(e))
        sys.exit(1)
    # ---

    vcomp_jobs = {}
    btcj_jobs = []
    btbj_jobs = []
    trd = []
    webroot_path = "/nfs/regression/webroot/"

    bazel_shutdown_job = job_lib.BazelShutdownJob(rcfg)

    for vcomp, test_list in rcfg.all_vcomp.items():
        vcomper = VCompJob(rcfg, vcomp, simulator)
        vcomp_jobs[vcomp] = vcomper

        btbj = job_lib.BazelTBJob(rcfg, vcomp, vcomper)
        btbj_jobs.append(btbj)

        tests = []
        icfgs = []
        for test, iterations in test_list.items():
            icfg = rv_utils.IterationCfg(iterations)
            icfgs.append(icfg)

            btcj = job_lib.BazelTestCfgJob(rcfg, test, vcomper)
            btcj_jobs.append(btcj)

            # Create TestJob with simulator
            t = TestJob(rcfg, test, vcomper=vcomper, icfg=icfg, btcj=btcj, simulator=simulator)
            tests.append(t)

            # Test depends on its config being built
            t.add_dependency(btcj)

        rcfg.all_vcomp[vcomp] = (icfgs, tests)

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

    try:
        jm_opts = {
            'idle_print_seconds': options.idle_print_seconds,
            'quit_count': options.quit_count,
            'active_job_limit': get_active_job_limit(options, rcfg),
        }
        jm = job_lib.JobManager(jm_opts, log)

        for job in btbj_jobs:
            if options.no_compile:
                job.jobstatus = JobStatus.TO_BE_BYPASSED
            jm.add_job(job)
            bazel_shutdown_job.add_dependency(job)

        for vcomp, vcomper in vcomp_jobs.items():
            if options.no_compile:
                vcomper.jobstatus = JobStatus.TO_BE_BYPASSED
            jm.add_job(vcomper)
            bazel_shutdown_job.add_dependency(vcomper)
        jm.add_job(bazel_shutdown_job)

        for btcj in btcj_jobs:
            if options.no_run:
                btcj.jobstatus = JobStatus.TO_BE_BYPASSED
            else:
                jm.add_job(btcj)
                bazel_shutdown_job.add_dependency(btcj)

        if options.python_seed:
            random.seed(options.python_seed)
            log.info("Set python random seed to %s", options.python_seed)

        for vcomp, (icfgs, test_list) in rcfg.all_vcomp.items():
            tests = test_list
            suppress_via_tests = False
            if len(tests) > 1:
                if options.gui:
                    rcfg.log.critical("--gui can only be used on one bench/test at a time")
                if options.seed:
                    rcfg.log.critical("--seed can only be used on one bench/test at a time")
                log.info("Suppressing output due to multiple tests begin run")
                suppress_via_tests = True

            [setattr(t, 'suppress_output', suppress_via_tests or suppress_via_vcomp_jobs) for t in tests]

            for test in tests:
                if options.no_run:
                    test.jobstatus = JobStatus.TO_BE_BYPASSED
                else:
                    jm.add_job(test)

        jm.wait()
        jm.stop()
        if options.no_run:
            rcfg.log.info("run_test:main(): --no_run option selected, exiting")

    except KeyboardInterrupt:
        log.info("Saw keyboard interrupt, attempting to shutdown jobs.")
        jm.kill()
        log.critical("Exiting due to keyboard interrupt")

    rv_utils.print_summary(rcfg, vcomp_jobs, icfgs, jm, trd)
    # add category_stats for soc
    category_stats = None
    if options.category_cfg is not None:
        category_stats = rv_utils.calc_category_stats(rcfg)
        rv_utils.print_category_summary(category_stats, rcfg.log, rv_utils.LOGGER_INDENT)

    report_header = {}
    if options.report:
        if options.coverage:
            simulator.run_report_coverage_merge(vcomp_jobs)
        
        report_header = rv_utils.get_report_header(rcfg)
        if report_header is not None and 'tag' in report_header:
            if '-' in report_header['tag']:
                report_header['tag'] = ''
        rrt = regression_report.RegressionReport(rcfg, jinja2_env, webroot_path)
        rrt.run(report_header, trd, rv_utils.get_coverage_data(rcfg, vcomp_jobs), category_stats)

    failures = {}
    for bench, (icfgs, test_list) in rcfg.all_vcomp.items():
        failures[bench] = sum([not j.jobstatus.successful for icfg in icfgs for j in icfg.jobs])
        # Count failures directly from the job objects stored in test_jobs_list
        #num_failed = sum(1 for j in test_jobs_list if j.jobstatus and not j.jobstatus.successful)
        #failures[bench] = num_failed
        if options.report:
            rrt.change_permissions_recursively(os.path.join(webroot_path, "regression_report", report_header['project_name'], bench.split(":")[1]))
            log.info("Report at: http://dv-sh.rd.lgt.ai/regression_report/{0}/{1}".format(report_header['project_name'], bench.split(":")[1]))

    for message in rcfg.deferred_messages:
        log.info(message)

    simulator.cleanup_shared_runtime_artifacts(vcomp_jobs)

    rcfg.log.exit_if_warnings_or_errors("Previous errors")

    # Exit with non-zero code if any test failed
    total_failures = sum(failures.values())
    if total_failures > 0:
        log.info(f"Exiting with status 1 due to {total_failures} test failure(s).")
        sys.exit(1)
    else:
        log.info("All tests passed.")
        sys.exit(0)

if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    verbosity = cmn_logging.DEBUG if options.tool_debug else cmn_logging.INFO
    log = cmn_logging.build_logger("sim", level=verbosity, use_color=options.use_color, filehandler="simmer.log")
    rcfg = regression.RegressionConfig(options, log)
    main(rcfg, options)
