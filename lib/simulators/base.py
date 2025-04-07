# lib/simulators/base.py
import abc
import os


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
    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        """Get the path to the simulator-specific compile args file."""
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
    def get_log_parsing_info(self):
        """Return info needed for parsing logs (e.g., warning patterns)."""
        # Example: return {'warning_regex': r"\*W.*"}
        pass

    @abc.abstractmethod
    def get_gui_command_options(self):
        """Return simulator-specific options required for GUI mode."""
        pass
