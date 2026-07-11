# lib/simulators/xcelium.py
import os
import stat
import glob
import shutil
import logging
import shlex
import subprocess

import jinja2

from .base import SimulatorInterface

log = logging.getLogger(__name__)


class XceliumSimulator(SimulatorInterface):
    """Implementation for Cadence XRUN simulator (including EMU variant)."""

    def get_name(self):
        return "xrun"

    def get_compile_template(self, vcomp_job):
        if self.options.emulator.upper() != '':
            emu_template_path = os.getenv('EMU_JINJA2_PATH')
            if emu_template_path:
                emu_loader = jinja2.FileSystemLoader(searchpath=emu_template_path)
                emu_env = jinja2.Environment(loader=emu_loader)
                try:
                    template = emu_env.get_template('xrun_emu_compile_template.sh.j2')
                    log.debug("Using EMU compile template from EMU_JINJA2_PATH")
                    return template
                except jinja2.TemplateNotFound:
                    raise RuntimeError("{} EMU template xrun_emu_compile_template.sh.j2 was not found in {}".format(
                        vcomp_job,
                        emu_template_path,
                    ))
            else:
                raise RuntimeError("{} requires EMU_JINJA2_PATH with xrun_emu_compile_template.sh.j2".format(vcomp_job))
        else:
            log.debug("Using standard XRUN compile template")
            return self.env.get_template('xrun_compile_template.sh.j2')

    def get_sim_template(self):
        # Assuming a single sim_template works for now, driven by options
        return self.env.get_template('sim_template.sh.j2')

    def get_wave_cmd_template(self):
        return self.env.get_template('xrun_wave_cmd_template.tcl.j2')

    def get_wave_view_command(self, wave_file_path, job_dir=None):
        return 'runmod xrun -- verisium -64bit -db "{}"'.format(wave_file_path)

    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        if self.options.msie_prim:
            return os.path.join(self.options.proj_dir, relpath, "msie/{}_prim.f".format(bazel_target))
        if self.options.msie_incr:
            return os.path.join(self.options.proj_dir, relpath, "msie/{}_incr.f".format(bazel_target))
        # Handle EMU exception first
        if self.options.emulator == 'pldm_sa':
            return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args".format(bazel_target))
        # Default XRUN/non-pldm_sa EMU
        return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args.f".format(bazel_target))

    def get_vcomp_job_dir(self, default_job_dir):
        if self.options.msie_prim:
            return default_job_dir + "_PRIM"
        return default_job_dir

    def get_bazel_runtime_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_runtime_args.f".format(bazel_target))

    def get_bazel_emu_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_rtl_compile_args".format(bazel_target))

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
                    "#!/usr/bin/env bash\n",
                    "" if self.options.report else "runmod xrun -- imc -exec {} -verbose\n".format(merge_exec_tcl),
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
        sim_args = ["-svseed", str(seed)]
        # Coverage
        if self.options.coverage:
            sim_args.append("-covoverwrite")
            # Ensure cov_work_dir exists on the vcomper object
            if hasattr(test_job.vcomper, 'cov_work_dir') and test_job.vcomper.cov_work_dir:
                sim_args.extend(["-covworkdir", test_job.vcomper.cov_work_dir])
            else:
                log.warning(f"Coverage enabled but cov_work_dir not set for vcomp job {test_job.vcomper.name}")
            sim_args.extend(["-covbaserun", test_job.name])
            if 'A' in self.options.coverage or 'U' in self.options.coverage:
                sim_args.append("+SVFCOV=1")
        # MCE
        if self.options.mce:
            sim_args.extend([
                "-mce",
                "-mce_pie",
                "-mce_newperf",
                "-mce_parallel_probing",
                "0",
                "-mce_sim_cpu_configuration",
                str(self.options.mce_sim_cfg),
                "-mce_sim_thread_count",
                str(self.options.mce_sim_count),
                "-mce_split_max_size",
                str(self.options.mce_split_max_size),
            ])
        # Profile
        if self.options.profile:
            sim_args.append("-profile")

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

        if wave_type == 'shm':
            waves_db = os.path.join(waves_db, "waves.shm")
            sim_opts += ' -debug_opts verisium_pp '
        elif wave_type == 'vwdb':
            waves_db = os.path.join(waves_db, 'waves')
            sim_opts += ' -debug_opts verisium_pp '
        elif wave_type == 'vcd':
            default_capture = 'hdl_top.dut'
            waves_db = os.path.join(waves_db, "waves.vcd")
        else:
            raise ValueError("{} not allowed".format(self.options.wave_type))

        sim_opts += " " + shlex.join(["-input", wave_tcl_path])
        return {
            'sim_opts': sim_opts,
            'wave_tcl_path': wave_tcl_path,
            'waves_db': waves_db,
            'default_capture': default_capture,
        }

    def get_no_wave_capture_options(self, test_job, nwaves_tcl_path):
        return {
            'sim_opts': " " + shlex.join(["-input", nwaves_tcl_path]),
            'tcl_commands': ["run"],
        }

    def get_wave_artifact_path(self, job_dir, wave_type):
        wave_type = wave_type.lower()
        if wave_type == 'shm':
            return os.path.join(job_dir, 'waves.shm')
        if wave_type == 'vcd':
            return os.path.join(job_dir, 'waves.vcd')
        if wave_type == 'vwdb':
            return os.path.join(job_dir, 'waves.db')
        raise ValueError("Not allowed wave: {}".format(wave_type))

    def setup_coverage_merge(self, vcomp_job):
        # The merge script setup is already done within generate_compile_options for XRUN/IMC
        pass

    def run_report_coverage_merge(self, vcomp_jobs):
        if not self.options.coverage:
            return
        for vcomp in vcomp_jobs.values():
            log.info("Before merge: Vcomp {}.".format(vcomp))
            merge_exec_tcl = os.path.join(vcomp.cov_work_dir, "merge_exec.tcl")
            result = subprocess.run(
                ["runmod", "xrun", "--", "imc", "-exec", merge_exec_tcl, "-verbose"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError("XRUN coverage merge failed:\n{}\n{}".format(result.stdout, result.stderr))

    def get_log_parsing_info(self):
        return {'warning_regex': r"\*W.*"}

    def get_gui_command_options(self):
        raise ValueError("Xcelium supports batch mode only; --gui is allowed only with VCS")

    # --- Method to implement for generating the simulation command ---
    def get_sim_command(self, test_job, sim_opts, vcomp_job_dir, log_path, user_args_list=None):
        """
        Constructs the full simulation command string for XRUN, including logging.
        """
        emu_type = self.options.emulator.upper()
        if emu_type in ('PLDM_SA', 'PLDM_SIM'):
            emu_dpi_lib = os.environ.get("RV_EMU_DPI_LIB", "dv_common/global/libwc_time_dpi.so")
            emu_xmlib_dir = os.environ.get("RV_EMU_XMLIBDIR", "hw_lib")
            cmd_parts = [
                "xrun",
                "-R",
                "-64",
                "-xmfatal",
                "NOTEXP",
                "-xmlibdirname",
                emu_xmlib_dir,
                "-sv_lib",
                emu_dpi_lib,
            ]
        elif emu_type == 'SIM':
            emu_dpi_lib = os.environ.get("RV_EMU_DPI_LIB", "dv_common/global/libwc_time_dpi.so")
            emu_xmlib_dir = os.environ.get("RV_EMU_XMLIBDIR", "sw_lib")
            cmd_parts = [
                "xrun",
                "-R",
                "-64",
                "-xmfatal",
                "NOTEXP",
                "-xmlibdirname",
                emu_xmlib_dir,
                "-sv_lib",
                emu_dpi_lib,
            ]
        else:
            cmd_parts = shlex.split("runmod -t xrun --") + ["-R", "-xmlibdirname", vcomp_job_dir]
            if self.options.gui and " -gui " not in sim_opts:
                cmd_parts.append("-gui")

        if user_args_list:
            cmd_parts.extend(user_args_list)
        cmd_parts.extend(["-l", log_path])
        full_command = shlex.join(cmd_parts)
        if sim_opts:
            full_command += " " + sim_opts

        log.debug(f"Constructed XRUN sim command: {full_command}")
        return full_command

    def get_sim_working_dir(self, test_job):
        """Run each XRUN simulation from its own test job directory."""
        return test_job.job_dir

    def get_pre_sim_commands(self, test_job):
        """No specific pre-simulation commands needed for XRUN directory setup."""
        return []

    def get_post_sim_commands(self, test_job):
        """No specific post-simulation commands needed for XRUN directory cleanup."""
        return []

    def cleanup_shared_runtime_artifacts(self, vcomp_jobs):
        # Only remove simulator scratch files created at the top level of the
        # shared runfiles tree. Never recurse into mirrored source areas such as
        # hw/, external/, odie/, testbench/, tests/, etc., because those
        # directories contain real runfiles and generated filelists needed by
        # the simulation flow.
        cleanup_patterns = [
            "xp_elab.log*",
            "xmsim_*.err",
            "xmsim_sigbus.*",
            "ida_diagnostics.log",
            "lwdgen.log",
            "cdns_dump.log",
            "environment.*",
            "verisium_debug_logs",
            "verisium_debug_logs_backup",
            "waves.shm",
        ]

        cleaned_dirs = set()
        for vcomp_job in vcomp_jobs.values():
            runfiles_dir = getattr(vcomp_job, "bazel_runfiles_main", None)
            if not runfiles_dir or runfiles_dir in cleaned_dirs or not os.path.isdir(runfiles_dir):
                continue

            removed_paths = []
            for pattern in cleanup_patterns:
                for path in glob.glob(os.path.join(runfiles_dir, pattern)):
                    try:
                        if os.path.isdir(path) and not os.path.islink(path):
                            shutil.rmtree(path, ignore_errors=False)
                        else:
                            os.remove(path)
                        removed_paths.append(os.path.basename(path))
                    except FileNotFoundError:
                        continue
                    except OSError as exc:
                        log.warning("Failed to remove XRUN shared runtime artifact %s: %s", path, exc)

            if removed_paths:
                log.info(
                    "Cleaned %d XRUN shared runtime artifact(s) from %s",
                    len(removed_paths),
                    runfiles_dir,
                )
            cleaned_dirs.add(runfiles_dir)
