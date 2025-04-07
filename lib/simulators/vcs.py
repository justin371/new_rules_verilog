# lib/simulators/vcs.py
import os
import re
import stat
import logging

from .base import SimulatorInterface

log = logging.getLogger(__name__)


class VcsSimulator(SimulatorInterface):
    """Implementation for Synopsys VCS simulator."""

    def get_name(self):
        return "vcs"

    def get_compile_template(self, vcomp_job):
        return self.env.get_template('vcs_compile_template.sh.j2')

    def get_sim_template(self):
        # Assuming a single sim_template works for now, driven by options
        return self.env.get_template('sim_template.sh.j2')

    def get_wave_cmd_template(self):
        # Assuming a single wave template works, driven by options and sim type
        # If needed, create vcs_wave_cmd_template.tcl.j2
        return self.env.get_template('wave_cmd_template.tcl.j2') # Or specialized one

    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args_vcs.f".format(bazel_target))

    def get_bazel_runtime_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_runtime_args_vcs.f".format(bazel_target))

    def generate_compile_options(self, vcomp_job):
        opts = {'cov_opts': '', 'xprop_cmd': None, 'additional_defines': []}
        additional_vcs_defines = [] # Add VCS specific defines here if any

        # Coverage (Functional/Code)
        if self.options.cm:
            vcomp_job.cov_work_dir = os.path.join(self.rcfg.regression_dir, vcomp_job.name + "__COV_WORK_VCS")
            # No need to create dir here, VCS does it with -cm_dir
            opts['cov_opts'] += ' -cm_dir {} '.format(vcomp_job.cov_work_dir)
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level or 'U' in cm_level: # Assume 'A' or 'U' means all
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            opts['cov_opts'] += ' -cm {} '.format(cm_level)
            self.setup_coverage_merge(vcomp_job) # Setup merge script

        # XPROP
        if self.options.xprop and not (self.options.mce or self.options.msie or self.options.msie_prim
                                       or self.options.msie_href):
            xprop_file_path = os.path.join(vcomp_job.bench_dir, 'vcs_xprop.cfg')
            if os.path.exists(xprop_file_path):
                opts['xprop_cmd'] = "-xprop={}".format(xprop_file_path)
            else:
                log.warning(f"VCS XPROP file not found: {xprop_file_path}")

        # Defines
        opts['additional_defines'].extend(additional_vcs_defines)
        if self.options.rtl_defines is not None:
            opts['additional_defines'].extend(self.options.rtl_defines)

        return opts

    def generate_sim_options(self, test_job, seed):
        sim_opts = ""
        sim_opts += " +ntb_random_seed=%0d " % seed
        test_job.test_name_seed = "{}_seed_{}".format(test_job.name, seed) # Needed for VCS sim script template

        # Coverage
        if self.options.cm:
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level or 'U' in cm_level:
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            sim_opts += ' -cm {} '.format(cm_level)
            sim_opts += ' -cm_name {}_sv{} '.format(test_job.name, seed)
            # -cm_dir is compile-time only for VCS

        # Waves
        if self.options.waves is not None:
            waves_tcl = os.path.join(test_job.job_dir, "waves.tcl") # Assumes wave tcl name is standard
            sim_opts += " -ucli -do {} ".format(waves_tcl)

        return sim_opts

    def setup_coverage_merge(self, vcomp_job):
        # Only create merge script if coverage was enabled
        if not self.options.cm or not hasattr(vcomp_job, 'cov_work_dir') or not vcomp_job.cov_work_dir:
            return

        merge_sh = os.path.join(self.rcfg.regression_dir, "vcs_cov_merge.sh")
        merged_db_path = os.path.join(self.rcfg.regression_dir, "merged_cov.vdb")
        report_dir = os.path.join(vcomp_job.cov_work_dir + ".vdb") # URG expects .vdb suffix on dir

        with open(merge_sh, 'w') as filep:
            # Updated merge command using -input for multiple dirs
            filep.write("".join([
                "#!/usr/bin/env bash\n",
                "# Merge individual simulation coverage databases\n",
                "# Ensure the target directory exists\n",
                f"mkdir -p {merged_db_path}\n",
                "# Find all simulation coverage dirs (ending in .vdb) and merge them\n",
                f"find {self.rcfg.regression_dir} -maxdepth 1 -type d -name '{vcomp_job.name}__*__*_seed_*.vdb' -print0 | xargs -0 urg -full64 -dir -dbname {merged_db_path} -flex_merge union -report {report_dir}/urgReport\n",
                "# Alternative: Merge directly from the -cm_dir (may require post-processing)\n",
                "# urg -full64 -dir {vcomp_job.cov_work_dir}.vdb -dbname {merged_db_path} ... \n",
                "\n",
                "# Launch Verdi for the merged database\n",
                f"echo \"To view merged coverage: runmod vcs -- verdi -cov -covdir {merged_db_path}\"\n",
                "# Or launch Verdi for the unmerged simulation databases (shows individual runs)\n",
                f"echo \"To view unmerged coverage: runmod vcs -- verdi -cov -covdir {vcomp_job.cov_work_dir}.vdb\"\n",
            ]))
        st = os.stat(merge_sh)
        os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)
        self.rcfg.deferred_messages.append("Merge/Launch VCS coverage with {}".format(merge_sh))

    def get_log_parsing_info(self):
        # Adjust regex if VCS warnings look different, e.g., "^Warning:"
        return {'warning_regex': r"^(Warning|Error):.*"} # Example, adjust as needed

    def get_gui_command_options(self):
        # Enable Verdi debug features along with DVE/Verdi GUI
        return " -gui=verdi +UVM_VERDI_TRACE=UVM_AWARE +UVM_CONFIG_TRACE +UVM_PHASE_TRACE +UVM_OBJECTION_TRACE +UVM_RESOURCE_DB_TRACE +UVM_LOG_TRACE "

    # --- Method to implement for generating the simulation command ---
    def get_sim_command(self, test_job, sim_opts, vcomp_job_dir, log_path, user_args_list=None):
        """
        Constructs the full simulation command string for VCS, including logging.
        """
        options = self.options
        job = test_job

        # Base executable and common flags
        base_exec = "runmod vcs --" # Assume runmod wrapper
        simv_path = f"{vcomp_job_dir}/simv" # Path to compiled executable

        # VCS uses -l for logging
        log_handling = f"-l {log_path}"

        # Combine parts
        cmd_parts = [
            base_exec,
            simv_path,
            log_handling,
            sim_opts # Includes seed, coverage, waves, gui, uvm opts etc.
        ]

        # Add user arguments if provided
        if user_args_list:
            cmd_parts.extend(user_args_list)

        # Join into final command string
        full_command = " ".join(filter(None, cmd_parts))

        log.debug(f"Constructed VCS sim command: {full_command}")
        return full_command.strip()

    def get_sim_working_dir(self, test_job):
        """VCS runs inside a temporary seed-specific subdirectory within runfiles main."""
        if not hasattr(test_job, 'vcomper') or not hasattr(test_job.vcomper, 'bazel_runfiles_main'):
            raise AttributeError(f"Missing vcomper or bazel_runfiles_main for test job {test_job.name}")
        if not hasattr(test_job, 'test_name_seed') or not test_job.test_name_seed:
            # This should have been set in generate_sim_options
            raise AttributeError(f"Missing test_name_seed for VCS test job {test_job.name}")
        # The working dir is the bazel runfiles main dir initially
        # The pre-sim command will create the subdir, but the template needs the base dir
        # Correction: The template cds into sim_working_dir first. So this should be the runfiles main.
        # The pre/post commands handle the subdirectory relative to this.
        # Let's try having the working dir be the runfiles main, and pre/post handle the subdir.
        # return test_job.vcomper.bazel_runfiles_main

        # --- Alternative: Define working dir as the sub-directory itself ---
        # This might be cleaner if the template just needs to `cd` once.
        return os.path.join(test_job.vcomper.bazel_runfiles_main, test_job.test_name_seed)

    def get_pre_sim_commands(self, test_job):
        """Create the seed-specific subdirectory for VCS."""
        if not hasattr(test_job, 'test_name_seed') or not test_job.test_name_seed:
            raise AttributeError(f"Missing test_name_seed for VCS test job {test_job.name} in pre_sim_commands")
        # Create the directory relative to the *parent* of sim_working_dir if using the Alternative above
        # Or just create the absolute path if working dir is the subdir.
        # Let's assume sim_working_dir *is* the final subdir based on the Alternative above.
        # Use mkdir -p for safety (idempotent)
        return [f"mkdir -p {self.get_sim_working_dir(test_job)}"] # Command creates the target dir

    def get_post_sim_commands(self, test_job):
        """Remove the seed-specific subdirectory after VCS simulation."""
        if not hasattr(test_job, 'test_name_seed') or not test_job.test_name_seed:
            log.warning(
                f"Missing test_name_seed for VCS test job {test_job.name} in post_sim_commands, cannot clean up.")
            return []
        # Remove the directory defined by get_sim_working_dir
        return [f"rm -rf {self.get_sim_working_dir(test_job)}"]
