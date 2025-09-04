# lib/simulators/xrun.py
import os
import sys
import re
import stat
import logging

from .base import SimulatorInterface

log = logging.getLogger(__name__)

# Determine the absolute path to the directory containing this script's package
# Adjust based on your actual structure if lib/simulators is not directly under the main script dir
simulators_dir_path = os.path.dirname(os.path.realpath(__file__))
project_root_path = os.path.abspath(os.path.join(simulators_dir_path, os.pardir, os.pardir))
sys.path.append(project_root_path) # Add project root to path if necessary


class XrunSimulator(SimulatorInterface):
    """Implementation for Cadence XRUN simulator (including EMU variant)."""

    def get_name(self):
        return "xrun"

    def get_compile_template(self, vcomp_job):
        if self.options.emulator.upper() != '':
            # Use the absolute path to locate the 'templates' directory
            dir_path = os.path.dirname(os.path.realpath(sys.modules['__main__'].__file__))
            # Get the path from the environment variable EMU_JINJA2_PATH
            emu_template_path = os.getenv('EMU_JINJA2_PATH')
            if emu_template_path:
                import jinja2 # Import locally if needed
                # fetch xrun_emu_compile_template.sh.j2 from project specific folder
                emu_loader = jinja2.FileSystemLoader(searchpath=emu_template_path)
                emu_env = jinja2.Environment(loader=emu_loader)
                try:
                    template = emu_env.get_template('xrun_emu_compile_template.sh.j2')
                    log.debug("Using EMU compile template from EMU_JINJA2_PATH")
                    return template
                except jinja2.TemplateNotFound:
                    log.error(("%s EMU_JINJA2_PATH environment variable is set, but "
                               "xrun_emu_compile_template.sh.j2 not found in %s"), vcomp_job, emu_template_path)
                    sys.exit(1) # Or raise an exception
            else:
                log.error(("%s EMU_JINJA2_PATH environment variable is not set, please set the path "
                           "where xrun_emu_compile_template.sh.j2 is located, "
                           "default path is in digital/emu/script"), vcomp_job)
                sys.exit(1) # Or raise an exception
        else:
            log.debug("Using standard XRUN compile template")
            return self.env.get_template('xrun_compile_template.sh.j2')

    def get_sim_template(self):
        # Assuming a single sim_template works for now, driven by options
        return self.env.get_template('sim_template.sh.j2')

    def get_wave_cmd_template(self):
        # Assuming a single wave template works, driven by options and sim type
        # If needed, create xrun_wave_cmd_template.tcl.j2
        return self.env.get_template('wave_cmd_template.tcl.j2') # Or specialized one

    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        # Handle EMU exception first
        if self.options.emulator == 'pldm_sa':
            return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args".format(bazel_target))
        # Default XRUN/non-pldm_sa EMU
        return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args_xrun.f".format(bazel_target))

    def get_bazel_runtime_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_runtime_args_xrun.f".format(bazel_target))

    def generate_compile_options(self, vcomp_job):
        opts = {'cov_opts': '', 'xprop_cmd': None, 'additional_defines': []}

        # Coverage
        if self.options.coverage:
            vcomp_job.cov_work_dir = os.path.join(self.rcfg.regression_dir, vcomp_job.name + "__COV_WORK")
            os.makedirs(vcomp_job.cov_work_dir, exist_ok=True) # Use makedirs
            merge_exec_tcl = os.path.join(vcomp_job.cov_work_dir, "merge_exec.tcl")
            imc_report_tcl = os.path.join(vcomp_job.cov_work_dir, "imc_report.tcl")
            merged_output = os.path.join(vcomp_job.cov_work_dir, "merged_db")
            with open(merge_exec_tcl, 'w') as filep:
                filep.write("merge -initial_model union_all -out {} -overwrite {}".format(
                    merged_output, os.path.join(vcomp_job.cov_work_dir, "scope", "*")))
            report_output = os.path.join(vcomp_job.cov_work_dir, "imc_report")
            with open(imc_report_tcl, 'w') as filep:
                filep.write("".join([
                    "load {}\n".format(merged_output),
                    "report -html -out {} -grading both -overwrite\n".format(report_output),
                ]))
            merge_sh = os.path.join(vcomp_job.cov_work_dir, "merge.sh")
            with open(merge_sh, 'w') as filep:
                filep.write("".join([
                    "#!/usr/bin/env bash\n", "" if self.options.report else "runmod xrun -- imc -exec {} -verbose\n".format(merge_exec_tcl),
                    "runmod xrun -- imc -load {}\n".format(merged_output)
                ]))
            st = os.stat(merge_sh)
            os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)
            opts['cov_opts'] += ' -coverage {} '.format(self.options.coverage)

            # --- CCF Aspect (Keep as is for now, might need refactoring if complex) ---
            # ... (keep the bazel build ccf aspect logic here) ...
            # ---

            self.rcfg.deferred_messages.append("Launch XRUN coverage with {}".format(merge_sh))

        # XPROP
        if self.options.xprop and not (self.options.mce or self.options.msie or self.options.msie_prim
                                       or self.options.msie_href):
            if self.options.xprop == 'F':
                xprop_file = 'fox_xprop.txt'
            else:
                xprop_file = 'cat_xprop.txt'
            xprop_file_path = os.path.join(vcomp_job.bench_dir, xprop_file)
            if os.path.exists(xprop_file_path):
                opts['xprop_cmd'] = '-xfile {} -xverbose'.format(xprop_file_path)
            else:
                log.warning(f"Xcelium XPROP file not found: {xprop_file_path}")

        # Defines
        if self.options.rtl_defines is not None:
            opts['additional_defines'].extend(self.options.rtl_defines)
        # Add any XRUN-specific defines here if needed

        return opts

    def generate_sim_options(self, test_job, seed):
        sim_opts = ""
        sim_opts += " -svseed %d " % seed
        # Coverage
        if self.options.coverage:
            sim_opts += ' -covoverwrite '
            # Ensure cov_work_dir exists on the vcomper object
            if hasattr(test_job.vcomper, 'cov_work_dir') and test_job.vcomper.cov_work_dir:
                sim_opts += ' -covworkdir {} '.format(test_job.vcomper.cov_work_dir)
            else:
                log.warning(f"Coverage enabled but cov_work_dir not set for vcomp job {test_job.vcomper.name}")
            sim_opts += ' -covbaserun {} '.format(test_job.name)
            if 'A' in self.options.coverage or 'U' in self.options.coverage:
                sim_opts += ' +SVFCOV=1 '
        # Waves
        if self.options.waves is not None:
            waves_tcl = os.path.join(test_job.job_dir, "waves.tcl") # Assumes wave tcl name is standard
            sim_opts += " -input {} ".format(waves_tcl)
            if self.options.wave_type == 'shm':
                sim_opts += ' -debug_opts verisium_pp '
            elif self.options.wave_type == 'fsdb':
                # Assuming VERDI_HOME is set correctly
                verdi_pli = os.path.join(os.environ.get('VERDI_HOME', ''), 'share/PLI/IUS/LINUX64/boot',
                                         'debpli.so:novas_pli_boot')
                if os.path.exists(verdi_pli.split(':')[0]):
                    sim_opts += " -loadpli1 {} ".format(verdi_pli)
                    sim_opts += " +UVM_VERDI_TRACE=UVM_AWARE+HIER+RAL+TLM+COMPWAVE "
                    sim_opts += " +fsdb+delta +fsdb+force +fsdb+functions +fsdb+struct=on "
                    sim_opts += " +fsdb+parameter=on +fsdb+sva_status +fsdb+sva_success "
                    sim_opts += " +fsdb+autoflush "
                else:
                    log.warning(f"Verdi PLI not found for FSDB: {verdi_pli}. FSDB dumping might fail.")
            # Add other wave types if XRUN specific options are needed (VCD, EVCD)
        # MCE
        if self.options.mce:
            sim_opts += " -mce "
            sim_opts += " -mce_pie "
            sim_opts += " -mce_newperf "
            sim_opts += " -mce_parallel_probing 0 "
            sim_opts += " -mce_sim_cpu_configuration {} ".format(self.options.mce_sim_cfg)
            sim_opts += " -mce_sim_thread_count {} ".format(self.options.mce_sim_count)
        # Profile
        if self.options.profile:
            sim_opts += " -profile "

        return sim_opts

    def setup_coverage_merge(self, vcomp_job):
        # The merge script setup is already done within generate_compile_options for XRUN/IMC
        pass

    def get_log_parsing_info(self):
        return {'warning_regex': r"\*W.*"}

    def get_gui_command_options(self):
        return " -gui -R " # -R makes it run automatically in GUI

    # --- Method to implement for generating the simulation command ---
    def get_sim_command(self, test_job, sim_opts, vcomp_job_dir, log_path, user_args_list=None):
        """
        Constructs the full simulation command string for XRUN, including logging.
        """
        options = self.options # Convenience alias
        job = test_job # Convenience alias

        # Base executable and common flags
        # Handle runmod wrapper if used consistently
        base_exec = "runmod -t xrun -- " # Assume runmod for standard sim
        run_flags = "-R" # Common run flag
        if options.gui:
            # GUI flag handled by get_gui_command_options() adding to sim_opts,
            # but ensure -R isn't duplicated if GUI already adds it.
            if " -gui " not in sim_opts and " -R " not in sim_opts:
                run_flags += " -gui" # Add gui if not already in sim_opts by GUI logic

        # Snapshot location
        # Use vcomp_job_dir directly, assuming it's the dir containing 'snapshot'
        snapshot_arg = f"-snapshot {vcomp_job_dir}/snapshot:snap" # Check if 'snapshot:snap' is correct dir/file name

        # Combine basic parts (excluding logging and user args for now)
        cmd_parts = [
            base_exec,
            run_flags,
            f"-xmlibdirname {vcomp_job_dir}", # Point to the compile dir
            #snapshot_arg,
            sim_opts # Includes seed, coverage, waves, gui, uvm opts etc. from generate_sim_options & common logic
        ]

        # --- Handle Emulator Variations ---
        emu_type = options.emulator.upper()
        if emu_type == 'PLDM_SA' or emu_type == 'PLDM_SIM':
            # Specific EMU command structure (adjust paths/libs as needed)
            # Note: Original template used `xrun` directly, not `runmod`
            base_exec = "xrun"
            emu_libs = "-sv_lib dv_common/global/libwc_time_dpi.so" # Example lib path
            emu_xmlib = "-xmlibdirname hw_lib" # Example xmlib for this emu type
            # Construct specific command parts for this EMU type
            cmd_parts = [
                base_exec,
                "-R -64 -xmfatal NOTEXP", # Common EMU flags from original template
                emu_xmlib,
                emu_libs,
                sim_opts # Pass the calculated sim_opts
                # Snapshot might not be used or different for EMU? Verify. If needed add snapshot_arg here.
            ]
            # NOTE: EMU log file was specified differently in original template:
            # -l user_work/{{job.simname}}/sim.log
            # We need to decide: Use -l or | tee? If -l works for EMU, use it.
            # If EMU needs '| tee', handle it below. Let's assume for now '| tee' is safer.
            log_handling = f"| tee {log_path}" # Use pipe tee

        elif emu_type == 'SIM': # Another emulator type from original template
            base_exec = "xrun"
            emu_libs = "-sv_lib dv_common/global/libwc_time_dpi.so"
            emu_xmlib = "-xmlibdirname sw_lib"
            cmd_parts = [base_exec, "-R -64 -xmfatal NOTEXP", emu_xmlib, emu_libs, sim_opts]
            log_handling = f"| tee {log_path}" # Use pipe tee

        else: # Standard XRUN simulation (not EMU)
            # Add user arguments if provided
            if user_args_list:
                cmd_parts.extend(user_args_list)
            # Standard XRUN uses pipe tee for logging based on original template
            log_handling = f"| tee {log_path}"

        # Join command parts into a single string
        base_command = " ".join(filter(None, cmd_parts)) # Filter removes empty strings

        # Combine base command with the log handling mechanism
        full_command = f"{base_command} {log_handling}"

        log.debug(f"Constructed XRUN sim command: {full_command}")
        return full_command.strip() # Return the complete command string

    def get_sim_working_dir(self, test_job):
        """XRUN runs directly from the runfiles main directory."""
        # Ensure vcomper and bazel_runfiles_main exist
        if not hasattr(test_job, 'vcomper') or not hasattr(test_job.vcomper, 'bazel_runfiles_main'):
            raise AttributeError(f"Missing vcomper or bazel_runfiles_main for test job {test_job.name}")
        return test_job.vcomper.bazel_runfiles_main

    def get_pre_sim_commands(self, test_job):
        """No specific pre-simulation commands needed for XRUN directory setup."""
        return []

    def get_post_sim_commands(self, test_job):
        """No specific post-simulation commands needed for XRUN directory cleanup."""
        return []
