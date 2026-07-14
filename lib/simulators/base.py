# lib/simulators/base.py
import abc
import os


class ValidationErrorParser:

    def error(self, message):
        raise ValueError(message)


class SimulatorInterface(abc.ABC):
    """Abstract base class defining the interface for simulators."""

    def __init__(self, options, rcfg, env):
        self.options = options
        self.rcfg = rcfg
        self.env = env # Jinja2 environment

    @abc.abstractmethod
    def get_name(self):
        """Return the canonical name of the simulator (e.g., 'xrun', 'vcs')."""
        pass

    @abc.abstractmethod
    def get_compile_template(self, vcomp_job):
        """Return the Jinja2 template for the compile script."""
        pass

    @abc.abstractmethod
    def get_sim_template(self):
        """Return the Jinja2 template for the simulation run script."""
        pass

    @abc.abstractmethod
    def get_wave_cmd_template(self):
        """Return the Jinja2 template for the wave command file."""
        pass

    @abc.abstractmethod
    def get_wave_view_command(self, wave_file_path, job_dir=None):
        """Return the command used by run_waves.sh to open a wave artifact."""
        pass

    @abc.abstractmethod
    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        """Get the path to the simulator-specific compile args file."""
        pass

    @abc.abstractmethod
    def get_vcomp_job_dir(self, default_job_dir):
        """Return the simulator-specific vcomp job directory."""
        pass

    @abc.abstractmethod
    def get_bazel_runtime_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        """Get the path to the simulator-specific runtime args file."""
        pass

    @abc.abstractmethod
    def generate_compile_options(self, vcomp_job):
        """Generate simulator-specific compile options (e.g., coverage, xprop)."""
        pass

    @abc.abstractmethod
    def generate_sim_options(self, test_job, seed):
        """Generate simulator-specific simulation options (e.g., seed, coverage, waves, gui)."""
        pass

    @abc.abstractmethod
    def get_wave_capture_options(self, test_job, wave_tcl_path):
        """Return simulator-specific wave options and Tcl rendering metadata."""
        pass

    @abc.abstractmethod
    def get_no_wave_capture_options(self, test_job, nwaves_tcl_path):
        """Return simulator-specific run Tcl options when wave dumping is disabled."""
        pass

    @abc.abstractmethod
    def get_wave_artifact_path(self, job_dir, wave_type):
        """Return the expected simulator wave artifact path."""
        pass

    @abc.abstractmethod
    def get_sim_command(self, test_job, sim_opts, vcomp_job_dir, log_path, user_args_list=None):
        """Constructs the full simulation command string, including logging."""
        pass

    @abc.abstractmethod
    def get_sim_working_dir(self, test_job):
        """Return the directory from which the simulation command should be executed."""
        pass

    @abc.abstractmethod
    def get_pre_sim_commands(self, test_job):
        """Return a list of shell commands to run before the main simulation command."""
        pass

    @abc.abstractmethod
    def get_post_sim_commands(self, test_job):
        """Return a list of shell commands to run after the main simulation command."""
        pass

    @abc.abstractmethod
    def setup_coverage_merge(self, vcomp_job):
        """Create necessary files/scripts for merging coverage reports."""
        pass

    @abc.abstractmethod
    def run_report_coverage_merge(self, vcomp_jobs):
        """Run coverage merges and return whether any merge failed."""
        return False

    @abc.abstractmethod
    def get_log_parsing_info(self):
        """Return info needed for parsing logs (e.g., warning patterns)."""
        # Example: return {'warning_regex': r"\*W.*"}
        pass

    @abc.abstractmethod
    def get_gui_command_options(self):
        """Return simulator-specific options required for GUI mode."""
        pass

    def validate_reusable_compile_artifacts(self, vcomp_job):
        """Validate any simulator-specific outputs needed by `--no-compile`.

        The default implementation does nothing.
        """
        return

    def validate_compile_cache_context(self, vcomp_job):
        """Validate backend metadata after the compile fingerprint is available."""
        return

    def should_auto_reuse_compile(self):
        """Return whether a fingerprint hit may bypass compilation."""
        return False

    def prepare_compile_execution(self, vcomp_job, reusing_compile):
        """Prepare mutable backend state after the compile/reuse decision."""
        return

    def prepare_compile_job(self, vcomp_job):
        """Resolve and validate simulator-specific compile inputs."""
        return

    def record_compile_artifacts(self, vcomp_job):
        """Record simulator-specific outputs after a successful compile."""
        return

    def collect_compile_metrics(self, vcomp_job):
        """Return optional backend metrics for persistent simmer results."""
        return {}

    def cleanup_shared_runtime_artifacts(self, vcomp_jobs):
        """Clean simulator scratch files created under shared runfiles dirs.

        Called once after the regression finishes so cleanup does not race with
        active simulations. The default implementation does nothing.
        """
        return

    def cleanup_test_coverage(self, test_job):
        """Remove one failed test's simulator-specific coverage database."""
        return

    def get_scheduler_threads_per_test(self):
        """Return the effective thread cost of one simulation for job limiting."""
        return 1

    def validate_resolved_options(self):
        """Validate options after test cfgs choose the final simulator."""
        return

    def validate_run_options(self, vcomp_count):
        """Validate simulator capabilities needed by the selected run."""
        return

    def uses_dynamic_test_plan(self):
        """Return whether the backend selects test iterations after compilation."""
        return False

    def create_regression_jobs(self, vcomp_jobs):
        """Create backend-owned jobs and attach their dependencies."""
        return []

    def finalize_regression_workflow(self):
        """Finalize a backend-owned workflow and report whether it failed."""
        return False

    def prepare_test_job(self, test_job):
        """Prepare backend-owned state and optionally return a seed override."""
        return None

    def should_spawn_test_job(self, test_job):
        """Return whether a dynamically planned test needs another iteration."""
        return False

    def coverage_enabled(self):
        """Return whether this backend requested coverage collection."""
        return False

    def get_compile_template_context(self, vcomp_job):
        """Return backend-owned values needed by its compile template."""
        return {}

    def get_compile_fingerprint_inputs(self, vcomp_job):
        """Return common external files and environment affecting compilation."""
        compile_args_file = self.options.compile_args_file
        return {
            "extra_input_paths": [compile_args_file] if compile_args_file else [],
            "environment": {
                key: os.environ.get(key, "")
                for key in ("LOADEDMODULES", "MODULEPATH", "PATH")
            },
        }

    def compile_script_for_fingerprint(self, compile_script):
        """Normalize performance-only compile switches before hashing."""
        return compile_script

    def collect_coverage_data(self, vcomp_jobs):
        """Return dashboard coverage summaries keyed by testbench name."""
        return {vcomp.split(":")[-1]: {"cc": {}, "cf": {}} for vcomp in vcomp_jobs}
