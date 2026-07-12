# lib/simulators/xcelium.py
import os
import stat
import glob
import hashlib
import json
import shutil
import logging
import shlex
import subprocess
import tempfile

import jinja2

from lib.coverage_data import aggregate_coverage_metrics, parse_coverage_summary
from .base import SimulatorInterface, ValidationErrorParser
from .options import validate_explicit_switches
from .xcelium_options import validate_xcelium_runtime_options

log = logging.getLogger(__name__)

MSIE_MANIFEST = ".msie_primary_manifest.json"


def _sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as filep:
            for chunk in iter(lambda: filep.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _write_json_atomic(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".msie-manifest-", dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as filep:
            json.dump(value, filep, indent=2, sort_keys=True)
            filep.write("\n")
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


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
                emu_env.filters['shell_quote'] = shlex.quote
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

    def validate_resolved_options(self):
        parser = ValidationErrorParser()
        validate_explicit_switches(self.options.vcs_explicit_switches, "VCS", "Xcelium", parser)
        validate_xcelium_runtime_options(self.options, parser)

    def get_scheduler_threads_per_test(self):
        if self.options.mce:
            return self.options.mce_sim_count or (os.cpu_count() or 1)
        return 1

    def coverage_enabled(self):
        return bool(self.options.coverage)

    def get_compile_template_context(self, vcomp_job):
        if not self.options.emulator:
            return {}
        relpath, bazel_target = vcomp_job.bazel_vcomp_target.split(':')
        return {
            'bazel_compile_args_rtl':
            self.get_bazel_emu_compile_args_file(
                vcomp_job.bazel_runfiles_main,
                relpath[2:],
                bazel_target,
            ),
        }

    def get_compile_fingerprint_inputs(self, vcomp_job):
        inputs = super().get_compile_fingerprint_inputs(vcomp_job)
        if self.options.coverage and self.options.covfile_was_explicit:
            inputs["extra_input_paths"].append(self.options.covfile)
        inputs["environment"].update({key: os.environ.get(key, "") for key in ("LM_LICENSE_FILE", "XCELIUMHOME")})
        return inputs

    def get_bazel_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        if self.options.msie_prim:
            return os.path.join(bazel_runfiles_main, relpath, "{}_msie_primary_compile_args.f".format(bazel_target))
        if self.options.msie_incr:
            return os.path.join(bazel_runfiles_main, relpath, "{}_msie_incremental_compile_args.f".format(bazel_target))
        if self.options.emulator == 'pldm_sa':
            return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args_pldm_sa.f".format(bazel_target))
        if self.options.emulator == 'pldm_sim':
            return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args_pldm_ice.f".format(bazel_target))
        return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args.f".format(bazel_target))

    def get_vcomp_job_dir(self, default_job_dir):
        if self.options.msie_href:
            return default_job_dir + "_HREF"
        if self.options.msie_prim:
            return default_job_dir + "_PRIM"
        return default_job_dir

    def _msie_primary_inputs_file(self, vcomp_job):
        relative_path = vcomp_job.tb_options.get("msie_primary_inputs")
        return os.path.join(vcomp_job.bazel_runfiles_main, relative_path) if relative_path else ""

    def _msie_input_digest(self, vcomp_job):
        inputs_path = self._msie_primary_inputs_file(vcomp_job)
        if not os.path.isfile(inputs_path):
            raise RuntimeError("MSIE primary input inventory is missing: {}. Configure both msie_primary_deps and "
                               "msie_incremental_deps on {} and rebuild with Bazel.".format(
                                   inputs_path, vcomp_job.bazel_vcomp_target))

        digest = hashlib.sha256()
        count = 0
        with open(inputs_path, "r", encoding="utf-8") as filep:
            for line in filep:
                kind, _, relative_path = line.rstrip("\n").partition("\t")
                if not relative_path:
                    continue
                path = relative_path if os.path.isabs(relative_path) else os.path.join(
                    vcomp_job.bazel_runfiles_main, relative_path)
                if not os.path.isfile(path):
                    raise RuntimeError("MSIE primary input is missing: {}".format(path))
                digest.update(kind.encode("utf-8"))
                digest.update(b"\0")
                digest.update(relative_path.encode("utf-8"))
                digest.update(b"\0")
                digest.update((_sha256_file(path) or "missing").encode("ascii"))
                digest.update(b"\0")
                count += 1
        return digest.hexdigest(), count

    def _effective_covfile(self, vcomp_job):
        if not self.options.coverage:
            return None
        covfile = self.options.covfile if self.options.covfile_was_explicit else vcomp_job.tb_options.get(
            "xcelium_covfile")
        if not covfile and os.path.isfile(self.options.covfile):
            covfile = self.options.covfile
        if covfile and not os.path.isabs(covfile):
            return os.path.join(vcomp_job.bazel_runfiles_main, covfile)
        return covfile

    def _msie_identity(self, vcomp_job):
        inputs_sha256, input_count = self._msie_input_digest(vcomp_job)
        covfile = self._effective_covfile(vcomp_job)
        return {
            "schema_version": 1,
            "bazel_target": vcomp_job.bazel_vcomp_target,
            "primary_top": vcomp_job.msie_primary_top,
            "primary_name": vcomp_job.msie_primary_name,
            "primary_key": self.options.msie_primary_key,
            "primary_compile_args_sha256": _sha256_file(vcomp_job.msie_primary_compile_args),
            "primary_inputs_sha256": inputs_sha256,
            "primary_input_count": input_count,
            "href_sha256": _sha256_file(vcomp_job.msie_href_file),
            "externs": {
                os.path.basename(path): _sha256_file(path)
                for path in vcomp_job.msie_extern_files
            },
            "coverage": self.options.coverage or "",
            "covfile_sha256": _sha256_file(covfile) if covfile else None,
            "rtl_defines": sorted(self.options.rtl_defines or []),
            "debug": self.options.waves is not None,
            "tool_environment": {
                key: os.environ.get(key, "")
                for key in ("XCELIUMHOME", "SIM_PLATFORM", "LOADEDMODULES")
            },
        }

    def _validate_msie_manifest(self, vcomp_job):
        path = os.path.join(vcomp_job.msie_primary_dir, MSIE_MANIFEST)
        if not os.path.isfile(path):
            raise RuntimeError(
                "MSIE primary manifest is missing: {}. Run --msie-href and --msie-prim for this target first.".format(
                    path))
        with open(path, "r", encoding="utf-8") as filep:
            actual = json.load(filep)
        expected = self._msie_identity(vcomp_job)
        if actual != expected:
            changed = sorted(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key))
            raise RuntimeError("MSIE primary is incompatible with this incremental build; changed identity fields: {}. "
                               "Rebuild href and primary with matching options.".format(", ".join(changed)))

    def prepare_compile_job(self, vcomp_job):
        options = self.options
        if not any(value is not None
                   for value in (options.msie, options.msie_href, options.msie_prim, options.msie_incr)):
            return

        vcomp_job.msie_primary_dir = vcomp_job.base_job_dir + "_PRIM"
        vcomp_job.msie_artifact_dir = vcomp_job.base_job_dir + "_MSIE"
        vcomp_job.msie_href_file = os.path.join(vcomp_job.msie_artifact_dir, "href.txt")
        primary_compile_args = vcomp_job.tb_options.get("msie_primary_compile_args")
        vcomp_job.msie_primary_compile_args = os.path.join(vcomp_job.bazel_runfiles_main,
                                                           primary_compile_args) if primary_compile_args else ""
        selected_compile_args = (
            vcomp_job.tb_options.get("msie_primary_compile_args") if options.msie_prim is not None else
            vcomp_job.tb_options.get("msie_incremental_compile_args") if options.msie_incr is not None else None)
        if selected_compile_args:
            vcomp_job.bazel_compile_args = os.path.join(vcomp_job.bazel_runfiles_main, selected_compile_args)
        os.makedirs(vcomp_job.msie_artifact_dir, exist_ok=True)

        if options.msie_href is not None:
            vcomp_job.msie_primary_top = options.msie_href
            vcomp_job.msie_primary_name = options.msie_href
            if options.no_compile:
                raise RuntimeError("--msie-href cannot be combined with --no-compile")
            for path in [vcomp_job.msie_href_file] + glob.glob(os.path.join(vcomp_job.msie_artifact_dir,
                                                                            "*_externs.v")):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        elif options.msie_prim is not None:
            vcomp_job.msie_primary_top = options.msie_prim
            vcomp_job.msie_primary_name = options.msie_primary_name or options.msie_prim
        elif options.msie_incr is not None:
            vcomp_job.msie_primary_top = options.msie_primary_top or vcomp_job.tb_options["dut_top"]
            vcomp_job.msie_primary_name = options.msie_incr
        else:
            vcomp_job.msie_primary_top = options.msie
            vcomp_job.msie_primary_name = options.msie

        vcomp_job.msie_extern_files = sorted(glob.glob(os.path.join(vcomp_job.msie_artifact_dir, "*_externs.v")))

        if options.msie_prim is not None or options.msie_incr is not None:
            if not os.path.isfile(vcomp_job.bazel_compile_args):
                dependency_attr = "msie_primary_deps" if options.msie_prim is not None else "msie_incremental_deps"
                raise RuntimeError(
                    "MSIE compile filelist is missing: {}. Configure {} on {} and rebuild with Bazel.".format(
                        vcomp_job.bazel_compile_args, dependency_attr, vcomp_job.bazel_vcomp_target))
            if not os.path.isfile(vcomp_job.msie_href_file):
                raise RuntimeError("MSIE href is missing: {}. Run --msie-href first.".format(vcomp_job.msie_href_file))
            vcomp_job.msie_manifest_identity = self._msie_identity(vcomp_job)

        if options.msie_prim is not None and options.no_compile:
            self._validate_msie_manifest(vcomp_job)
        if options.msie_incr is not None:
            self._validate_msie_manifest(vcomp_job)

    def record_compile_artifacts(self, vcomp_job):
        if self.options.msie_href is not None:
            if not os.path.isfile(vcomp_job.msie_href_file):
                raise RuntimeError("XRUN completed without generating {}".format(vcomp_job.msie_href_file))
        elif self.options.msie_prim is not None:
            _write_json_atomic(os.path.join(vcomp_job.msie_primary_dir, MSIE_MANIFEST),
                               vcomp_job.msie_manifest_identity)

    def get_bazel_runtime_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_runtime_args.f".format(bazel_target))

    def get_bazel_emu_compile_args_file(self, bazel_runfiles_main, relpath, bazel_target):
        return os.path.join(bazel_runfiles_main, relpath, "{}_compile_args_pldm_ice.f".format(bazel_target))

    def generate_compile_options(self, vcomp_job):
        opts = {'cov_opts': '', 'xprop_cmd': None, 'additional_defines': []}

        # Coverage
        if self.options.coverage:
            vcomp_job.cov_work_dir = os.path.join(self.rcfg.regression_dir, vcomp_job.name + "__COV_WORK")
            for stale_path in [
                    os.path.join(vcomp_job.cov_work_dir, "scope"),
                    os.path.join(vcomp_job.cov_work_dir, "merged_db"),
                    os.path.join(vcomp_job.cov_work_dir, "imc_report"),
            ]:
                shutil.rmtree(stale_path, ignore_errors=True)
            os.makedirs(vcomp_job.cov_work_dir, exist_ok=True) # Use makedirs
            merge_exec_tcl = os.path.join(vcomp_job.cov_work_dir, "merge_exec.tcl")
            imc_report_tcl = os.path.join(vcomp_job.cov_work_dir, "imc_report.tcl")
            merged_output = os.path.join(vcomp_job.cov_work_dir, "merged_db")
            with open(merge_exec_tcl, 'w') as filep:
                filep.write("merge -initial_model union_all -out {} -overwrite {}".format(
                    merged_output, os.path.join(vcomp_job.cov_work_dir, "scope", "*")))
            report_output = os.path.join(vcomp_job.cov_work_dir, "imc_report")
            code_report = os.path.join(vcomp_job.cov_work_dir, "coverage_code.txt")
            functional_report = os.path.join(vcomp_job.cov_work_dir, "coverage_functional.txt")
            with open(imc_report_tcl, 'w') as filep:
                filep.write("".join([
                    "load {}\n".format(merged_output),
                    "report -summary -metrics all -all -cumulative on -out {}\n".format(code_report),
                    "report -summary -metrics covergroup -type -all -out {}\n".format(functional_report),
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
            cov_args = ["-coverage", self.options.coverage]
            dut_top = getattr(vcomp_job, "tb_options", {}).get("dut_top")
            if dut_top:
                cov_args.extend(["-covdut", dut_top])
            covfile = self._effective_covfile(vcomp_job)
            if covfile:
                cov_args.extend(["-covfile", covfile])
            opts['cov_opts'] = shlex.join(cov_args)
            vcomp_job.coverage_code_report = code_report
            vcomp_job.coverage_functional_report = functional_report
            vcomp_job.coverage_report_tcl = imc_report_tcl
            vcomp_job.coverage_report_dir = report_output
            vcomp_job.merged_coverage_dir = merged_output

            self.rcfg.deferred_messages.append("Launch XRUN coverage with {}".format(merge_sh))

        # XPROP
        if self.options.xprop_was_explicit and self.options.xprop:
            if self.options.xprop == 'F':
                xprop_file = 'fox_xprop.txt'
            else:
                xprop_file = 'cat_xprop.txt'
            xprop_file_path = os.path.join(vcomp_job.bench_dir, xprop_file)
            if os.path.exists(xprop_file_path):
                opts['xprop_cmd'] = '-xfile {} -xverbose'.format(xprop_file_path)
            else:
                opts['xprop_cmd'] = '-xprop {} -xverbose'.format(self.options.xprop)

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
            coverage_name = "{}_sv{}_i{}".format(test_job.name, seed, test_job.iteration)
            sim_args.extend([
                "-covbaserun",
                coverage_name,
            ])
            test_job.coverage_db_path = os.path.join(test_job.vcomper.cov_work_dir, "scope", coverage_name)
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
            'render_template': not self.options.wave_tcl,
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
            cov_work_dir = getattr(vcomp, "cov_work_dir", None)
            if not cov_work_dir:
                log.error("XRUN coverage merge skipped for %s: coverage work directory is unavailable", vcomp)
                continue
            merge_exec_tcl = os.path.join(cov_work_dir, "merge_exec.tcl")
            try:
                result = subprocess.run(
                    ["runmod", "xrun", "--", "imc", "-exec", merge_exec_tcl, "-verbose"],
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                log.error("XRUN coverage merge could not start for %s: %s", vcomp, exc)
                continue
            if result.returncode != 0:
                log.error("XRUN coverage merge failed for %s:\n%s\n%s", vcomp, result.stdout, result.stderr)

    def cleanup_test_coverage(self, test_job):
        path = getattr(test_job, "coverage_db_path", None)
        if path:
            shutil.rmtree(path, ignore_errors=True)

    def collect_coverage_data(self, vcomp_jobs):
        coverage = {}
        if not self.options.coverage:
            return {vcomp.split(":")[-1]: aggregate_coverage_metrics({}) for vcomp in vcomp_jobs}
        for vcomp, job in vcomp_jobs.items():
            report_tcl = getattr(job, "coverage_report_tcl", None)
            merged_coverage_dir = getattr(job, "merged_coverage_dir", None)
            if not report_tcl or not merged_coverage_dir or not os.path.exists(merged_coverage_dir):
                coverage[vcomp.split(":")[-1]] = aggregate_coverage_metrics({})
                continue
            try:
                result = subprocess.run(
                    ["runmod", "xrun", "--", "imc", "-exec", report_tcl, "-verbose"],
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                log.error("IMC report generation could not start for %s: %s", job, exc)
                coverage[vcomp.split(":")[-1]] = aggregate_coverage_metrics({})
                continue
            if result.returncode != 0:
                log.error("IMC report generation failed:\n%s", result.stderr)
                metrics = {}
            else:
                metrics = parse_coverage_summary(job.coverage_code_report)
                functional = parse_coverage_summary(job.coverage_functional_report)
                if "CoverGroup" in functional:
                    metrics["CoverGroup"] = functional["CoverGroup"]
            coverage[vcomp.split(":")[-1]] = aggregate_coverage_metrics(metrics)
        return coverage

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
        if emu_type == 'CLEAN':
            raise RuntimeError("Xcelium emulator clean mode does not run simulations")
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
