#!/usr/bin/env python

################################################################################
# standard lib imports
import argparse
from copy import deepcopy
import datetime
from hashlib import sha1
import os
import sys
from tempfile import TemporaryFile
import random
import re
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
from lib.job_lib import Job, JobStatus
from lib import cmn_logging
from lib import job_lib
from lib import regression
from lib import rv_utils

log = None

# Use the absolute path to locate the 'templates' directory
file_loader = jinja2.FileSystemLoader(searchpath=os.path.join(dir_path, 'templates'))
env = jinja2.Environment(loader=file_loader)

XRUN_COMPILE_TEMPLATE = env.get_template('xrun_compile_template.sh.j2')
VCS_COMPILE_TEMPLATE = env.get_template('vcs_compile_template.sh.j2')
SIM_TEMPLATE = env.get_template('sim_template.sh.j2')
WAVE_CMD_TEMPLATE = env.get_template('wave_cmd_template.tcl.j2')
RERUN_TEMPLATE = env.get_template('rerun_template.sh.j2')
BUGGER_TEMPLATE = env.get_template('bugger_template.sh.j2')
# For publishing test results to azure pipeline or jenkins
JUNIT_TEMPLATE = env.get_template('junit_tempalte.j2')


class VCompJob(Job):
    # All found vcomp names to prevent collisions
    all_names = {}

    def __init__(self, rcfg, bazel_vcomp_target):
        self.bazel_vcomp_target = bazel_vcomp_target
        name = os.path.basename(self.bazel_vcomp_target.split(":")[1])
        if name in self.__class__.all_names:
            log.critical("Found duplicate dv_tb name in %s and %s", self.bazel_vcomp_target,
                         self.__class__.all_names[name].bazel_vcomp_target)
        else:
            self.__class__.all_names[name] = self

        super(VCompJob, self).__init__(rcfg, name)

        self.bench_dir = os.path.join(self.rcfg.proj_dir, self.bazel_vcomp_target.split(':')[0][2:])

        job_dir = "{}__VCOMP{}".format(self.name, self.rcfg.options.dir_suffix)
        self.job_dir = os.path.join(self.rcfg.regression_dir, job_dir)
        if options.msie_prim:
            self.job_dir = self.job_dir + "_PRIM"
        self.log_path = os.path.join(self.job_dir, "cmp.log")

        self.main_cmdline = None

    def pre_run(self):
        super(VCompJob, self).pre_run()

        enable_debug_access = 0
        if options.waves is not None:
            enable_debug_access = 1
        if options.gui:
            enable_debug_access = 2
        enable_cdnvip = 0
        if options.vip:
            enable_cdnvip = 1

        cov_opts = ''
        if options.coverage:
            if options.simulator.upper() == 'XRUN':
                self.cov_work_dir = os.path.join(self.rcfg.regression_dir, self.name + "__COV_WORK")
                os.system("mkdir -p {}".format(self.cov_work_dir))
                merge_exec_tcl = os.path.join(self.cov_work_dir, "merge_exec.tcl")
                merged_output = os.path.join(self.cov_work_dir, "merged_db")
                with open(merge_exec_tcl, 'w') as filep:
                    filep.write("merge -initial_model union_all -out {} -overwrite {}".format(
                        merged_output, os.path.join(self.cov_work_dir, "scope", "*")))
                merge_sh = os.path.join(self.cov_work_dir, "merge.sh")
                with open(merge_sh, 'w') as filep:
                    filep.write("".join([
                        "#!/usr/bin/env bash\n", "runmod xrun -- imc -exec {} -verbose\n".format(merge_exec_tcl),
                        "runmod xrun -- imc -load {}\n".format(merged_output)
                    ]))
                st = os.stat(merge_sh)
                os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)
                cov_opts += ' -coverage {} '.format(options.coverage)

                cmd = "bazel build {} --aspects @rules_verilog//verilog/private:dv.bzl%verilog_dv_tb_ccf_aspect".format(
                    self.bazel_vcomp_target)
                log.debug(" > %s", cmd)

                with TemporaryFile() as stdout_fp, TemporaryFile() as stderr_fp:
                    p = subprocess.Popen(cmd, stdout=stdout_fp, stderr=stderr_fp, shell=True)
                    p.wait()
                    stdout_fp.seek(0)
                    stderr_fp.seek(0)
                    stdout = stdout_fp.read()
                    stderr = stderr_fp.read()
                    if p.returncode:
                        log.critical("bazel coverage ccf mapping failed:\n%s", stderr.decode('ascii'))

                    text = stderr.decode('ascii')
                    try:
                        covfiles = eval(re.search("verilog_dv_tb_ccf\((.*)\)", text).group(1))
                        cov_opts += " ".join([' -covfile {} '.format(ccf) for ccf in covfiles])
                    except (AttributeError):
                        pass # No ccf file declared (bazel query results empty)

                self.rcfg.deferred_messages.append("Launch coverage with {}".format(merge_sh))

        if options.cm:
            if options.simulator.upper() == 'VCS':
                self.cov_work_dir = os.path.join(self.rcfg.regression_dir, self.name + "__COV_WORK_VCS")
                cov_opts += ' -cm_dir {} '.format(self.cov_work_dir)
                if 'A' in options.cm or 'U' in options.cm:
                    cov_opts += ' -cm line+cond+fsm+tgl+assert+branch '
                else:
                    cov_opts += ' -cm {} '.format(options.cm)

                merge_sh = os.path.join(self.rcfg.regression_dir, "vcs_cov_merge.sh")
                with open(merge_sh, 'w') as filep:
                    filep.write("".join([
                        "#!/usr/bin/env bash\n", "#runmod vcs -- urg -full64 -flex_merge union -dir {}.vdb -report {}.vdb/cov_report -dbname {}/merged_cov.vdb\n".format(self.cov_work_dir,self.cov_work_dir,self.rcfg.regression_dir),
                        "#runmod vcs -- verdi -cov -covdir {}/merged_cov.vdb\n".format(self.rcfg.regression_dir),
                        "runmod vcs -- verdi -cov -covdir {}.vdb\n".format(self.cov_work_dir)
                    ]))
                st = os.stat(merge_sh)
                os.chmod(merge_sh, st.st_mode | stat.S_IEXEC)

        additional_defines = []
        additional_vcs_defines = []
        if options.simulator.upper() == 'VCS':
            additional_defines.extend(additional_vcs_defines)
        if options.rtl_defines is not None:
            additional_defines.extend(options.rtl_defines)

        log.debug("workdir = %s", self.job_dir)

        if options.lmstat:
            os.system("lmstat -a > lmstat.out")
        else:
            log.debug("Skipping lmstat -a")

        os.system("env > {}".format(os.path.join(self.job_dir, 'env.out')))
        os.system("hostname > {}".format(os.path.join(self.job_dir, 'hostname.out')))

        if options.msie_prim:
            if not os.path.exists(self.job_dir):
                os.mkdir(self.job_dir)
        if options.recompile:
            log.info("Removing vcomp library %s due to --recompile flag", self.job_dir)
            os.system("rm -rf {0}; mkdir -p {0}".format(self.job_dir))

        relpath, bazel_target = self.bazel_vcomp_target.split(':')
        relpath = relpath[2:] # Remove leading //

        # Find bazel-bin
        # FIXME this is repeated elsewhere, make it a lib function
        p = subprocess.Popen("bazel info", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()
        assert p.returncode == 0
        stdout, stderr = p.communicate()
        bazel_bin = re.search(r"bazel-bin: (.*)", stdout.decode('ascii')).group(1)
        # This is a gross assumption, but I can't see an easier way to find this in bazel
        self.bazel_runfiles_main = os.path.join(bazel_bin, relpath, "{}.runfiles".format(bazel_target), "_main")

        for ta in options.tests:
            tb_name = ta.btiglob.split(":")[0]
        if options.msie_prim:
            self.bazel_compile_args = os.path.join("{}/{}/msie/{}_prim.f".format(options.proj_dir, relpath, tb_name))
        elif options.msie_incr:
            self.bazel_compile_args = os.path.join(options.proj_dir, relpath,
                                                   "{}/{}/msie/{}_incr.f".format(options.proj_dir, relpath, tb_name))
        else:
            self.bazel_compile_args = os.path.join(
                self.bazel_runfiles_main, relpath, "{}_compile_args_{}.f".format(bazel_target,
                                                                                 options.simulator.lower()))
        self.bazel_runtime_args = os.path.join(self.bazel_runfiles_main, relpath,
                                               "{}_runtime_args_{}.f".format(bazel_target,
                                                                             options.simulator.lower()))
        self.compile_warning_waivers_path = os.path.join(self.bazel_runfiles_main, relpath,
                                                         "{}_compile_warning_waivers".format(bazel_target))
        xprop_cmd = None
        if options.mce or options.msie or options.msie_prim or options.msie_href:
            #XPROP is not supported if mce or msie
            options.xprop = None
        if options.xprop:
            if options.simulator.upper() == 'VCS':
                xprop_file = os.path.join(self.bench_dir, 'vcs_xprop.cfg')
                xprop_cmd = "-xprop={}".format(xprop_file)
            if options.simulator.upper() == 'XRUN':
                if options.xprop == 'F':
                    xprop_file = 'fox_xprop.txt'
                else:
                    xprop_file = 'cat_xprop.txt'
                xprop_file = os.path.join(self.bench_dir, xprop_file)
                xprop_cmd = '-xfile {} -xverbose'.format(xprop_file)

        vcomp_sh_path = os.path.join(self.job_dir, "vcomp.sh")

        with open(vcomp_sh_path, 'w') as filep:
            if options.simulator.upper() == 'XRUN':
                filep.write(
                    XRUN_COMPILE_TEMPLATE.render(
                        VCOMP_DIR=self.job_dir,
                        cov_opts=cov_opts,
                        bazel_runfiles_main=self.bazel_runfiles_main,
                        bazel_compile_args=self.bazel_compile_args,
                        enable_debug_access=enable_debug_access,
                        xprop_cmd=xprop_cmd,
                        relpath=relpath,
                        tb_name=tb_name,
                        additional_defines=additional_defines,
                        options=options,
                    ))
            if options.simulator.upper() == 'VCS':
                filep.write(
                    VCS_COMPILE_TEMPLATE.render(
                        VCOMP_DIR=self.job_dir,
                        cov_opts=cov_opts,
                        bazel_runfiles_main=self.bazel_runfiles_main,
                        bazel_compile_args=self.bazel_compile_args,
                        enable_debug_access=enable_debug_access,
                        enable_cdnvip=enable_cdnvip,
                        xprop_cmd=xprop_cmd,
                        additional_defines=additional_defines,
                        options=options,
                    ))

        log.debug("bazel_runfiles_main: %s", self.bazel_runfiles_main)

        if self.rcfg.options.no_compile:
            self.main_cmdline = "echo \"Bypassing {} due to --no-compile\"".format(self)
        else:
            self.main_cmdline = "bash {}".format(vcomp_sh_path)

        log.debug(" > %s", self.main_cmdline)

    def post_run(self):
        if self.job_lib.returncode == 0:
            log_level = log.info
            self.jobstatus = JobStatus.PASSED
        else:
            log_level = log.error
            self.jobstatus = JobStatus.FAILED

        with open(self.compile_warning_waivers_path, 'r') as compile_warning_waivers_p:
            warning_waivers = compile_warning_waivers_p.read()
            warning_waivers = eval(warning_waivers)

        # Promote warnings to errors
        with open(os.path.join(self.log_path), 'r') as logp:
            text = logp.read()
            warnings = re.findall(r"\*W.*", text)
            for warning in warnings:
                waived = False
                for ww in warning_waivers:
                    if ww.search(warning):
                        waived = True
                        break
                if not waived:
                    self.jobstatus = JobStatus.FAILED
                    log.error("%s failed due to unwaived warning: %s", self, warning)

        # Don't want to set completed yet
        super(VCompJob, self).post_run()

        log_level("%s vcomp %s in %s", self.name, self.jobstatus, self.job_dir)

    def __repr__(self):
        return 'Vcomp("{}")'.format(self.bazel_vcomp_target)


class TestJob(Job):

    LOG_NAME = 'stdout.log'

    class RegexWrap():

        def __init__(self):
            self.match = None

        def search(self, regex, line):
            self.match = re.search(regex, line)
            return self.match

    def __init__(self, rcfg, target, vcomper, icfg, btcj):
        self.target = target
        name = target.split(":")[1]

        self.icfg = icfg
        self.iteration = icfg.spawn_count
        self.icfg.inc(self)
        self.btcj = btcj

        super(TestJob, self).__init__(rcfg, name)
        self.rcfg = rcfg
        self.vcomper = vcomper
        self.sim_opts = None
        if vcomper:
            self.add_dependency(vcomper)
        # Else expected to be added later when vcomper is set
        self._log_path = None

    def clone(self):
        c = TestJob(self.rcfg, self.target, self.vcomper, self.icfg, self.btcj)
        c.sim_opts = deepcopy(self.sim_opts)
        c.suppress_output = self.suppress_output
        return c

    def __repr__(self):
        try:
            return self.rcfg.format_test_name(self.vcomper.name, self.name, self.iteration)
        except AttributeError:
            return self.rcfg.format_test_name("<???>", self.name, self.iteration)

    def _flatten_test_cfg(self, path):
        flattened = []
        with open(path) as filep:
            rw = self.RegexWrap()
            for line in filep.readlines():
                if rw.search(r"^<INCLUDE>(.*)", line):
                    include = rw.match.group(1).strip()
                    include = os.path.join(os.path.dirname(path), include)
                    flattened.append("# Jumping into {}\n".format(include))
                    flattened.extend(self._flatten_test_cfg(include))
                    flattened.append("# Popping back from {}\n".format(include))
                else:
                    flattened.append(line)
        return flattened

    def pre_run(self):
        log.debug("Preparing test: %s:%s", self.vcomper.name, self.name)

        options = self.rcfg.options
        vcomp_dir = self.vcomper.job_dir

        sim_opts = ""

        seed = options.seed
        if seed is None:
            seed = random.randint(0, 1 << (32 - 1)) # xrun is treating the seed as a signed integer
            # When coverage is generated, it appends the signed version of the seed into the directory name
            # This causes a mismatch between our directory hierarchy and theirs
            # While it doesn't break anything, it is not intuitive to track
            # Thus, only using positive seeds
        if options.simulator.upper() == 'VCS':
            sim_opts += " +ntb_random_seed=%0d " % seed
            self.test_name_seed = "{}_seed{}".format(self.name,seed) # gen test_name_seed for sim.sh
            # or you can use +ntb_random_seed_automatic for vcs
        elif options.simulator.upper() == 'XRUN':
            sim_opts += " -svseed %d " % seed

        # Using the timestamp as the name uniquifier is causing issues when trying to spawn many jobs at once
        # strdate = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
        # simname = "%s__%s__%s" % (self.vcomper.name, self.name, strdate)
        simname = "%s__%s__%d%s" % (self.vcomper.name, self.name, seed, self.rcfg.options.dir_suffix)
        self.job_dir = os.path.join(self.rcfg.regression_dir, simname)
        self._log_path = os.path.join(self.job_dir, self.LOG_NAME)

        super(TestJob, self).pre_run()

        sockets = []
        dynamic_args = self.btcj.dynamic_args()
        for socket_name, socket_command in dynamic_args['sockets'].items():
            # While it would be nice to have the socket live in the job_dir,
            # Unfortunately, the paths are frequently too long resulting in:
            #  OSError: AF_UNIX path too long
            # As such, we'll use that name as the unique value to create hash
            socket_file = os.path.join(self.job_dir, "{}.socket".format(socket_name))
            socket_file = os.path.join("/tmp", sha1(socket_file.encode('ascii')).hexdigest())
            sim_opts += " +SOCKET__{}={}".format(socket_name, socket_file)
            socket_command = socket_command.format(socket_file=socket_file)
            sockets.append((socket_name, socket_command, socket_file))

        if options.coverage:
            if options.simulator.upper() == 'XRUN':
                sim_opts += ' -covoverwrite '
                sim_opts += ' -covworkdir {} '.format(self.vcomper.cov_work_dir)
                sim_opts += ' -covbaserun {} '.format(self.name)
                if 'A' in options.coverage or 'U' in options.coverage:
                    sim_opts += ' +SVFCOV=1 '
        if options.cm:
            if options.simulator.upper() == 'VCS':
                if 'A' in options.cm or 'U' in options.cm:
                    sim_opts += ' -cm line+cond+fsm+tgl+assert+branch '
                else:
                    sim_opts += ' -cm {} '.format(options.cm)
                sim_opts += ' -cm_name {}_sv{} '.format(self.name,seed)

        sim_opts += " +UVM_TESTNAME={uvm_testname} ".format(uvm_testname=dynamic_args['uvm_testname'], )
        # extract license tag for resources in LSF

        # The simmer CLI allows sim_opts to not specify a value, e.g "--sim-opts +UVM_CONFIG_DB_TRACE"
        # However, the simmer code that merges CLI sim_opts and verilog_dv_test_cfg sim_opts requires them to have the same formatting
        # Therefore, we need to map the CLI sim_opts to have a value defined for every +arg and use an '=' in formatting
        if options.sim_opts:
            cli_sim_opts = [so.split("=", maxsplit=1) for so in options.sim_opts]
            for cso in cli_sim_opts:
                if len(cso) == 0:
                    raise ValueError("Unexpected split, 0 items")
                elif len(cso) == 1:
                    cso.append("")
                elif len(cso) == 2:
                    cso[0] = cso[0] + "="
                else:
                    raise ValueError("Unexpected split, more than 2 items")
            cli_sim_opts = dict(cli_sim_opts)
        else:
            cli_sim_opts = {}

        bazel_test_cfg_sim_args = dynamic_args['sim_opts']
        # bazel_test_cfg_sim_args is a dictionary, but the key may have equal sign in it to be joined
        bazel_test_cfg_sim_args.update(cli_sim_opts) # Apply the CLI sim_opts on top of the bazel sim_opts
        bazel_test_cfg_sim_args = ["".join(btcsa) for btcsa in bazel_test_cfg_sim_args.items()]
        sim_opts += ' ' + (' '.join(bazel_test_cfg_sim_args)).replace('\"', ' ')

        pre_run = dynamic_args['pre_run']

        default_capture = 'tb_top'
        waves_db = self.job_dir
        if options.wave_tcl:
            if os.path.exists(options.wave_tcl):
                waves_tcl = options.wave_tcl
            else:
                raise ValueError("{} not exists".format(options.wave_tcl))
        else:
            waves_tcl = os.path.join(self.job_dir, "waves.tcl")

        if options.waves is not None:
            if options.wave_type == 'shm':
                waves_db = os.path.join(waves_db, "waves.shm")
                sim_opts += ' -debug_opts verisium_pp '
            elif options.wave_type == 'vwdb':
                waves_db = os.path.join(waves_db, 'waves.vwdb')
                #sim_opts += ' +vwdb+strength '
            elif options.wave_type == 'vcd':
                default_capture = 'tb_top.dut'
                waves_db = os.path.join(waves_db, "waves.vcd")
            elif options.wave_type == 'evcd':
                default_capture = 'tb_top.dut'
                waves_db = os.path.join(waves_db, "waves.evcd")
            elif options.wave_type == 'fsdb':
                waves_db = os.path.join(waves_db, "waves.fsdb")
                verdi_pli = os.path.join(os.environ['VERDI_HOME'], 'share/PLI/IUS/LINUX64/boot',
                                         'debpli.so:novas_pli_boot')
                sim_opts += " -loadpli1 {} ".format(verdi_pli)
                sim_opts += " +UVM_VERDI_TRACE=UVM_AWARE+HIER+RAL+TLM+COMPWAVE "
                sim_opts += " +fsdb+delta +fsdb+force +fsdb+functions +fsdb+struct=on "
                sim_opts += " +fsdb+parameter=on +fsdb+sva_status +fsdb+sva_success "
                sim_opts += " +fsdb+autoflush "
            else:
                raise ValueError("{} not allowed".format(options.wave_type))

            if options.simulator.upper() == 'VCS':
                sim_opts += " -ucli -do {} ".format(waves_tcl)
            elif options.simulator.upper() == 'XRUN':
                sim_opts += " -input {} ".format(waves_tcl)
            options.probes = options.waves if options.waves != [] else [default_capture]
            if options.wave_delta is True:
                options.delta = "-event"
            if not options.wave_tcl:
                with open(waves_tcl, 'w') as filep:
                    tmp = locals()
                    del tmp['self']
                    tmp['job'] = self
                    filep.write(WAVE_CMD_TEMPLATE.render(**tmp))
        else:
            nwaves_tcl = os.path.join(self.job_dir, "nwaves.tcl")
            if options.simulator.upper() == 'VCS':
                sim_opts += " -ucli -do {} ".format(nwaves_tcl)
                # Populate tcl_commands based on options.gui condition
                tcl_commands = ["config reversedebug on", "run"] if options.gui else ["run"]
            elif options.simulator.upper() == 'XRUN':
                sim_opts += " -input {} ".format(nwaves_tcl)
                tcl_commands = [
                    "run"
                ]
            with open(nwaves_tcl, 'w') as filep:
                filep.write("\n".join(tcl_commands))

        if options.uvm_set_int:
            sim_opts += ' +uvm_set_config_int=' + ' +uvm_set_config_int='.join(options.uvm_set_int)
        if options.uvm_set_str:
            sim_opts += ' +uvm_set_config_string=' + ' +uvm_set_config_string='.join(options.uvm_set_str)
        if options.sim_opts_file:
            fh = open(options.sim_opts_file, 'r')
            for line in fh:
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
            sim_opts += " -gui "
            if options.simulator.upper() == 'XRUN':
                sim_opts += " -R "
        if options.mce:
            sim_opts += " -mce "
            sim_opts += " -mce_pie "
            sim_opts += " -mce_newperf "
            sim_opts += " -mce_parallel_probing 0 "
            sim_opts += " -mce_sim_cpu_configuration {} ".format(options.mce_sim_cfg)
            sim_opts += " -mce_sim_thread_count {} ".format(options.mce_sim_count)
        if options.profile:
            sim_opts += " -profile "

        sim_opts += " -f {} ".format(self.vcomper.bazel_runtime_args)

        self.sim_opts = sim_opts
        log.debug("processJob: submit jobs")

        # try:
        #     self.timeout = found_options['timeout']
        # except KeyError:
        #     pass

        options = self.rcfg.options
        sim_opts = self.sim_opts

        if not os.path.exists(self.job_dir):
            os.mkdir(self.job_dir)

        gui = '' # pylint: disable=possibly-unused-variable
        if options.gui:
            gui = "-gui"

        testscript = os.path.join(self.job_dir, "sim.sh")
        with open(testscript, 'w') as filep:
            tmp = locals()
            del tmp['self']
            tmp['job'] = self
            filep.write(SIM_TEMPLATE.render(**tmp))
        os.system("chmod 777 %s" % testscript)
        log.debug('Created %s', testscript)

        rerun_script = os.path.join(self.job_dir, "rerun.sh")
        with open(rerun_script, 'w') as filep:
            tmp = locals()
            del tmp['self']
            tmp['job'] = self
            cmd_line_sim_opts = ""
            if options.sim_opts_file:
                fh = open(options.sim_opts_file, 'r')
                for line in fh:
                    cmd_line_sim_opts += ' ' + line.strip()
            if options.sim_opts:
                cmd_line_sim_opts += ' ' + (' '.join(options.sim_opts)).replace('\"', ' ')
            if cmd_line_sim_opts:
                cmd_line_sim_opts = "--sim-opts \"{}\"".format(cmd_line_sim_opts.lstrip())
            tmp['cmd_line_sim_opts'] = cmd_line_sim_opts
            filep.write(RERUN_TEMPLATE.render(**tmp))
        os.system("chmod 777 %s" % rerun_script)
        log.debug('Created %s', rerun_script)

        bugger_reproduce_script = os.path.join(self.job_dir, "bugger_reproduce.sh")
        with open(bugger_reproduce_script, 'w') as filep:
            tmp = locals()
            del tmp['self']
            tmp['job'] = self
            filep.write(BUGGER_TEMPLATE.render(**tmp))
        os.system("chmod 777 %s" % bugger_reproduce_script)
        log.debug('Created %s', bugger_reproduce_script)

        # Create a symlink back the vcomp directory for easy reference
        os.system("ln -snf %s %s" % (self.vcomper.job_dir, os.path.join(self.job_dir, '.vcomp')))

        if not self.rcfg.tidy:
            os.system("ln -snf %s .last_sim" % self.job_dir)
            log.debug("created link to sim dir as '.last_sim'")

        self.main_cmdline = '/usr/bin/bash %s' % (testscript)

    def post_run(self):
        super(TestJob, self).post_run()
        # Parse file for duration
        net_time_str, cps_str = self._get_stats_from_log_file()
        total_time_str = self._get_total_time_str()
        time_stats_str = "({} cps / {} net_time / {} total_time)".format(cps_str, net_time_str, total_time_str)
        if self.job_lib.returncode != 0:
            os.system("ln -snf %s .last_fail" % self.job_dir)
            log.debug("created link to sim dir as '.last_fail'")
            log.error(
                "%s %s",
                self.rcfg.table_format(self.vcomper.name,
                                       self.name + ' ' + str(self.iteration),
                                       "FAILED {}".format(time_stats_str),
                                       indent=''), self._log_path)
            self.jobstatus = JobStatus.FAILED
            with open(os.path.join(self.job_dir, "{}.err".format(self.LOG_NAME))) as errors:
                self.error_message = errors.read()
        else:
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
        if options.waves is not None:
            wave_path = self.job_dir
            if options.wave_type == 'shm':
                wave_path = os.path.join(wave_path, 'waves.shm')
            elif options.wave_type == 'vcd':
                wave_path = os.path.join(wave_path, 'waves.vcd')
            elif options.wave_type == 'evcd':
                wave_path = os.path.join(wave_path, 'waves.evcd')
            elif options.wave_type == 'vwdb':
                wave_path = os.path.join(wave_path, 'waves.vwdb.db')
            elif options.wave_type == 'fsdb':
                wave_path = os.path.join(wave_path, 'waves.fsdb')
            else:
                raise ValueError("Not allowed wave: {}".format(options.wave_type))

            if os.path.exists(wave_path):
                log.info("Waves available: {}".format(wave_path))
                os.system("chmod -R 755 {}".format(wave_path))
            else:
                log.error("Dumped waves, but waves file doesn't exist.")

        sys.stdout.flush()

        if self.rcfg.tidy and self.jobstatus.successful:
            log.debug("tidy=%s removing %s", self.rcfg.tidy, self.job_dir)
            os.system("rm -rf {}".format(self.job_dir))
            if os.path.exists(".last_sim"):
                os.system("rm .last_sim")

        # If iteration count hasnt been hit yet, add another copy onto the run list
        if self.icfg.spawn_count <= self.icfg.target:
            c = self.clone()
            self.job_lib.manager.add_job(c)

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
                    return match.group('duration'), match.group('cps')
        return '???', '???'

    @property
    def log_path(self):
        if self.jobstatus.completed:
            return self._log_path
        else:
            return "<incomplete>"


def main(rcfg):
    """
    Parameters
    ----------
    rcfg : RegressionConfig
         The main configuration knob for the regression
    """
    uname = os.uname()
    rcfg.log.info("Running on %s", uname[1])

    vcomp_jobs = {}
    btcj_jobs = []
    btbj_jobs = []

    bazel_shutdown_job = job_lib.BazelShutdownJob(rcfg)

    for vcomp, test_list in rcfg.all_vcomp.items():
        vcomper = VCompJob(rcfg, vcomp)
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

            t = TestJob(rcfg, test, vcomper=vcomper, icfg=icfg, btcj=btcj)
            tests.append(t)

            t.add_dependency(btcj)

            for _ in range(1, min(icfg.target, rcfg.options.parallel_max)):
                tclone = t.clone()
                tests.append(tclone)
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
        if options.seed is not None:
            rcfg.log.critical("--seed can only be used if a single test is run")

    try:
        jm_opts = {
            'parallel_max': options.parallel_max,
            'parallel_interval': options.parallel_interval,
            'idle_print_seconds': options.idle_print_seconds,
            'quit_count': options.quit_count
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

    rv_utils.print_summary(rcfg, vcomp_jobs, icfgs, jm)

    failures = {}
    for bench, (icfgs, test_list) in rcfg.all_vcomp.items():
        failures[bench] = sum([not j.jobstatus.successful for icfg in icfgs for j in icfg.jobs])

    if options.junit_dump:
        with open(options.junit_dump, 'w') as junit_f:
            junit_f.write(JUNIT_TEMPLATE.render(failures=failures, benches=rcfg.all_vcomp))
            log.info("Wrote junit results to %s", options.junit_dump)

    for message in rcfg.deferred_messages:
        log.info(message)

    rcfg.log.exit_if_warnings_or_errors("Previous errors")


if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    verbosity = cmn_logging.DEBUG if options.tool_debug else cmn_logging.INFO
    log = cmn_logging.build_logger("sim", level=verbosity, use_color=options.use_color, filehandler="simmer.log")
    rcfg = regression.RegressionConfig(options, log)
    main(rcfg)
