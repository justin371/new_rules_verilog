# lib/simulators/vcs.py
import os
import stat
import logging

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

    def get_wave_view_command(self, wave_file_path, job_dir=None):
        cmd = 'runmod vcs -- verdi -apex -lca -ssf "{}"'.format(wave_file_path)
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
        if self.options.xprop and not self.options.mce:
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
        sim_opts = ""
        sim_opts += " +ntb_random_seed=%0d " % seed
        sim_opts += " -xlrm hier_inst_seed "
        sim_opts += " -assert nopostproc "
        if self.options.fgp is not None:
            sim_opts += " -fgp=num_threads:{} ".format(self.options.fgp)
        if self.options.vcs_xprop_banner:
            sim_opts += " -xprop=banner "
        if self.options.vcs_xprop_report:
            sim_opts += " -report=xprop "
        test_job.test_name_seed = "{}_seed_{}".format(test_job.name, seed) # Needed for VCS sim script template

        # Coverage
        if self.options.cm:
            # Translate coverage level options if needed
            cm_level = self.options.cm
            if 'A' in cm_level:
                cm_level = 'line+cond+fsm+tgl+assert+branch'
            sim_opts += ' -cm {} '.format(cm_level)
            sim_opts += ' -cm_dir {} '.format(test_job.vcomper.cov_work_dir)
            sim_opts += ' -cm_name {}_sv{} '.format(test_job.name, seed)

        return sim_opts

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

        sim_opts += " -ucli -do {} ".format(wave_tcl_path)
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
            'sim_opts': " -ucli -do {} ".format(nwaves_tcl_path),
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

        merge_sh = os.path.join(self.rcfg.regression_dir, "vcs_cov_merge.sh")
        merged_db_path = os.path.join(self.rcfg.regression_dir, "merged_cov.vdb")
        report_dir = os.path.join(self.rcfg.regression_dir, "vcs_cov_report")
        cov_db_path = "{}.vdb".format(vcomp_job.cov_work_dir)
        merge_template = self.env.get_template('vcs_cov_merge_template.sh.j2')

        with open(merge_sh, 'w') as filep:
            filep.write(merge_template.render(
                cov_db_path=cov_db_path,
                merged_db_path=merged_db_path,
                report_dir=report_dir,
            ))
        st = os.stat(merge_sh)
        os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)
        self.rcfg.deferred_messages.append("Merge/Launch VCS coverage with {}".format(merge_sh))

    def run_report_coverage_merge(self, vcomp_jobs):
        pass

    def get_log_parsing_info(self):
        # Adjust regex if VCS warnings look different, e.g., "^Warning:"
        return {'warning_regex': r"^(Warning|Error):.*"} # Example, adjust as needed

    def get_gui_command_options(self):
        # Enable Verdi debug features along with DVE/Verdi GUI
        return " -gui=verdi +UVM_VERDI_TRACE=UVM_AWARE +UVM_CONFIG_TRACE +UVM_PHASE_TRACE +UVM_OBJECTION_TRACE +UVM_RESOURCE_DB_TRACE +UVM_LOG_TRACE "

    def validate_reusable_compile_artifacts(self, vcomp_job):
        simv_path = os.path.join(vcomp_job.job_dir, "simv")
        if not os.path.exists(simv_path):
            raise FileNotFoundError(
                "VCS --no-compile requires an existing elaborated executable at '{}'".format(simv_path)
            )

    # --- Method to implement for generating the simulation command ---
    def get_sim_command(self, test_job, sim_opts, vcomp_job_dir, log_path, user_args_list=None):
        """
        Constructs the full simulation command string for VCS, including logging.
        """
        # Base executable and common flags
        base_exec = "runmod vcs --"
        simv_path = f"{vcomp_job_dir}/simv" # Path to compiled executable

        # VCS smartlog is enabled by `-sml -l <logfile>`, which also generates
        # the companion `<logfile>.sml` automatically.
        smartlog_handling = "-sml"
        log_handling = f"-l {log_path}"

        # Combine parts
        cmd_parts = [
            base_exec,
            simv_path,
            smartlog_handling,
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
        """Run each VCS simulation from its own test job directory."""
        return test_job.job_dir

    def get_pre_sim_commands(self, test_job):
        return []

    def get_post_sim_commands(self, test_job):
        return []
