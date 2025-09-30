import argparse
import os
from lib import parser_actions

PROJ_DIR = os.environ.get('PROJ_DIR', os.getcwd())
SIM_PLATFORM = os.environ.get('SIM_PLATFORM', 'XRUN')
VCS_LICENSES = os.environ.get('VCS_LICENSES', 0)
XRUN_LICENSES = os.environ.get('XRUN_LICENSES', 0)
COVFILE = PROJ_DIR + os.environ.get('COVFILE', "coverage.ccf")


def add_debug_arguments(parser):
    gdebug = parser.add_argument_group('Debug arguments')
    gdebug.add_argument('--waves',
                        default=None,
                        nargs='*',
                        help=('Enable waveform capture. Optionally pass a list of HDL '
                              'paths to reduce probe scope. Default is tb_top.'))
    gdebug.add_argument('--wave-type',
                        type=str,
                        default='vwdb',
                        choices=['shm', 'fsdb', 'vcd', 'evcd', 'vwdb'],
                        help='Specify the waveform format')
    gdebug.add_argument('--wave-tcl',
                        type=str,
                        default=None,
                        help='Load the local wave.tcl file for waveform. Only used with --wave-tcl + path of wave.tcl')
    gdebug.add_argument('--wave-exclude',
                        type=str,
                        default="x",
                        help=('Exclude the specified object or the specified scope from the probe. '
                              'Only used with --wave.\n'
                              'Examples: \n'
                              '--wave-exclude "a_inst" \n'
                              '--wave-exclude {a_inst b_inst} \n'
                              '--wave-exclude "a_inst*" \n'))

    gdebug.add_argument('--wave-start',
                        type=int,
                        default=0,
                        help='Specify the sim time in ns to start dumping the waveform.')
    gdebug.add_argument('--wave-end',
                        type=int,
                        default=9999999,
                        help='Specify the sim time in ns to end dumping the waveform.')
    gdebug.add_argument('--wave-delta',
                        default=False,
                        action='store_true',
                        help='Capture delta-cycles for SHM waveform types.')
    gdebug.add_argument('--wave-depth',
                        type=int,
                        default=999,
                        help='Probe hirarchical depth. Only used with --waves. Default is all hierarchies')
    gdebug.add_argument('--probe-packed',
                        type=int,
                        default=1024,
                        help='Packed probe depth. Only used with --waves. Default is 1024.')
    gdebug.add_argument('--probe-unpacked',
                        type=int,
                        default=1024,
                        help='Unpacked probe depth. Only used with --waves. Default is 1024.')
    gdebug.add_argument('--gui',
                        default=False,
                        action='store_true',
                        help='run simulation in gui mode for C/DV debug, only applicable with single test')
    gdebug.add_argument('--cdn-vip',
                        default=False,
                        action='store_true',
                        help='add CDNS vip compile options for VCS simulator')
    gdebug.add_argument('--profile',
                        default=False,
                        action='store_true',
                        help='Dump simulation profiling information to file. (Cadence only.)')
    gdebug.add_argument('--verbosity',
                        type=str,
                        default=None,
                        choices=['UVM_NONE', 'UVM_LOW', 'UVM_MEDIUM', 'UVM_HIGH', 'UVM_FULL', 'UVM_DEBUG'],
                        help='Adds run time opt of +UVM_VERBOSITY.')
    gdebug.add_argument('--uvm-set-verbosity',
                        type=str,
                        default=None,
                        nargs="+",
                        help=('call +uvm_set_verbosity=<string> on the simulation to '
                              'enable debug message on a per module\nFormat of <comp>,'
                              '<id>,<verbosity>,<phase>'))
    gdebug.add_argument('--uvm-config-db-trace',
                        default=False,
                        action="store_true",
                        help='add +UVM_CONFIG_DB_TRACE to sim command line for uvm_config_db debugging')
    gdebug.add_argument('--uvm-resource-db-trace',
                        default=False,
                        action="store_true",
                        help='add +UVM_RESOURCE_DB_TRACE to sim command line for uvm_resource_db debugging')
    gdebug.add_argument('--uvm-max-quit-count',
                        type=int,
                        default=10,
                        help='Set UVM_MAX_QUIT_COUNT to the specified value')
    gdebug.add_argument('--skip-parse-sim-log',
                        default=False,
                        action='store_true',
                        help='Skip post-parsing the simulation log for errors')
    gdebug.add_argument('--tool-debug',
                        default=False,
                        action='store_true',
                        help='Set the verbosity of this tool to debug level.')
    gdebug.add_argument('--dir-suffix',
                        type=str,
                        default="",
                        help=("Append suffix to end of directory names to prevent stomping on previous "
                              "results when rerunning. This argument is not cumulative."))
    gdebug.add_argument('--use-color', default=False, action="store_true", help="Use colorcodes in stdout output")
    gdebug.add_argument('--quit-count', default=10, type=int, help="Quit spawning jobs after this many failures.")
    gdebug.add_argument("--allow-no-run",
                        default=False,
                        action='store_true',
                        help='Allow running of tests that have the "no_run" tag set')
    gdebug.add_argument('--file',
                        dest='compile_args_file',
                        type=str,
                        default=None,
                        help=('Load a local file contains the list of source files and compile/elaboration options.'
                              'Only used with --file <path_to_file>'))


def add_test_configuration_arguments(parser):
    gtestc = parser.add_argument_group("Test configuration arguments:")
    gtestc.add_argument('--seed', type=int, default=None, help='Set random seed, only applicable with single test.')
    gtestc.add_argument('--rtl-defines', type=str, default=None, nargs="+", help='Macro defines for RTL compile stage.')
    gtestc.add_argument('--sim-opts',
                        type=str,
                        default=[],
                        nargs="+",
                        help=('Options passed to simulator execution (e.g. --sim-opts "+wdog=1000000" '
                              '"+assert_reinitialization_delay=60000"). Note, these take '
                              'precedence over bazel verilog_dv_test_cfg sim_opts'))
    gtestc.add_argument('--sim-opts-file',
                        type=str,
                        default=None,
                        help='File that contains options to be passed to simv execution')
    gtestc.add_argument('--uvm-set-int',
                        type=str,
                        default=None,
                        nargs="+",
                        help='Sets the +uvm_set_config_int    to the value specified ')
    gtestc.add_argument('--uvm-set-str',
                        type=str,
                        default=None,
                        nargs="+",
                        help='Sets the +uvm_set_config_string to the value specified ')
    gtestc.add_argument('--uvm-set-config-int',
                        type=str,
                        default=None,
                        nargs="+",
                        help=('call +uvm_set_config_int=<int> to the sim command for '
                              'setting variables in the simulation'))
    gtestc.add_argument('--uvm-set-config-string',
                        type=str,
                        default=None,
                        nargs="+",
                        help=('call +uvm_set_config_string=<string> to the sim command '
                              'for setting variables in the simulation'))
    gtestc.add_argument('--xprop',
                        type=str,
                        default='F',
                        action=parser_actions.XpropAction,
                        help=('F=FOX (Forward-Only-X) mode. C=CAT(Compute as Ternary) mode. D=Disable. '
                              'CAT outputs behave exactly like hardware. '
                              'FOX is more pessimistic, and propogates X to the output if X is in the control.'))
    gtestc.add_argument('--timeout',
                        default=12.0,
                        type=float,
                        help="Sets the per-job wallclock timeout for simulation in hours.")

    # FIXME not implemented
    # gtestc.add_argument('--tcl',
    #                     type=str,
    #                     default=None,
    #                     nargs="+",
    #                     help='pass <tcl input file> to Cadence runtime -input <tcl_input_file>, disables -run option to xrun and ignores +debug option')
    # FIXME not implemented
    # gtestc.add_argument('--input',
    #                     type=str,
    #                     default=None,
    #                     nargs="+",
    #                     help='pass <tcl input file> to Cadence runtime -input <tcl_input_file>')
    # FIXME not implemented (also this should be every cfg file?)
    # gtestc.add_argument('--opts-file',
    #                     type=str,
    #                     default=None,
    #                     nargs="+",
    #                     help='file for command line options to simmer')


def add_regression_arguments(parser):
    gregre = parser.add_argument_group("Regression arguments")

    gregre.add_argument('--mce',
                        default=False,
                        action='store_true',
                        help='Multicore license enable for XRUN. Only used for Gatesim!')
    gregre.add_argument('--mce-build-count',
                        type=int,
                        default=4,
                        help=("Number of threads to be used for mce elaboration. "
                              "0 means a full range, used with --mce"))
    gregre.add_argument('--mce-build-cfg',
                        type=str,
                        default='single-socket',
                        choices=['single-socket', 'all-cores'],
                        help="The number of cores to be used for build, used with --mce")
    gregre.add_argument('--mce-sim-count',
                        type=int,
                        default=4,
                        help=("Number of threads to be used for mce simulation. "
                              "0 means a full range, used with --mce"))
    gregre.add_argument('--mce-sim-cfg',
                        type=str,
                        default='single-socket',
                        choices=['single-socket', 'single-threaded', 'partial-socket', 'all-cores'],
                        help="The number of cores to be used for sim, used with --mce")
    gregre.add_argument('--coverage',
                        action=parser_actions.CovAction,
                        help=f'Enable Code Coverage for xcelium only.\n{parser_actions.CovAction.format_options(indent=0)}')
    gregre.add_argument('--cm',
                        action=parser_actions.CMAction,
                        help=f'Enable Code Coverage for vcs only.\n{parser_actions.CMAction.format_options(indent=0)}')
    gregre.add_argument('--covfile', default=COVFILE, help='Path to Coverage configuration file')
    gregre.add_argument('--junit-dump',
                        type=str,
                        default=None,
                        help=("Dump a junit xml file with test results. "
                              "For use with CI systems like Jenkins or Azure Pipelines."))
    gregre.add_argument('--python-seed',
                        type=str,
                        default=None,
                        help='Set base seed in python for random seed generation.')
    gregre.add_argument('--idle-print-seconds',
                        type=int,
                        default=60 * 20,
                        help=('Print the state of the queues every few minutes if nothing has finished.\n'
                              'Helpful for debugging hanging tests.\n'))
    gregre.add_argument('--no-stdout',
                        default=False,
                        action='store_true',
                        help=('By default, when running a single test, the vcomp and sim stdout will '
                              'print to screen.\nThis option suppresses the stdout (useful when running '
                              ' a long test with high verbosity.\nIf multiple vcomps or tests are '
                              'discovered, this flag is automatically thrown.\n'))
    gregre.add_argument('--parallel-max',
                        type=int,
                        default=0,
                        help=('The maximum number of jobs to launch in parallel.\n'
                              'Default is the number of sim licenses'))
    gregre.add_argument('--parallel-interval',
                        type=int,
                        default=3,
                        help=('The interval between polling jobs when launch in parallel.\n'
                              'This is balance between the polling thread consuming too much '
                              'CPU by frequent polling vs license optimization by not wasting '
                              'time by being stuck in a polling loop.\nExpected that very short '
                              'sims should set this to a low number, longer sims can deal with '
                              'less frequent polling.\n'))
    gregre.add_argument('--nt',
                        default=False,
                        action='store_true',
                        help=('By default simmer will clean up simulation results when the tests '
                              'pass. This flag prevents that cleanup.'))
    gregre.add_argument('--msie',
                        type=str,
                        default=None,
                        nargs='?',
                        const='tb_top',
                        help='Incremental compile single_step(auto) mode\n'
                        'Need user create incr_pkg.sv in benches/tb_name/tests \n'
                        'incr_pkg.svh is used to include tests. eg: \n'
                        'module incr_pkg;\n'
                        '  import uvm_pkg::*;\n'
                        '  `include"base_test.svh"\n'
                        '  `include"sw_test.svh"\n'
                        'endmodule\n')
    gregre.add_argument('--msie-href',
                        type=str,
                        nargs='?',
                        const='tb_top',
                        default=None,
                        help='Gen href in benches/tb_name/hdl/href.txt \n'
                        'Need define prim top, default is tb_top'
                        'eg. --msie-href pcpu')
    gregre.add_argument('--msie-prim',
                        type=str,
                        nargs='?',
                        const='tb_top',
                        default=None,
                        help='Compile prim lib, need define prim top, default is tb_top')
    gregre.add_argument('--msie-incr',
                        type=str,
                        nargs='?',
                        default=None,
                        help='Compile incr, need define prim top, default is tb_top')
    gregre.add_argument('--category-cfg',
                        type=str, 
                        nargs='?',
                        default=None,
                        help="Path to category configuration JSON file (default: proj_dir/category_config.json)")


def add_flow_control_arguments(parser):
    gflowc = parser.add_argument_group("Flow control arguments:")
    gflowc.add_argument('--lmstat',
                        default=False,
                        action="store_true",
                        help='run the lmstat -a command before submitting')
    gflowc.add_argument('--no-run',
                        default=False,
                        action="store_true",
                        help='compile testcase but do not submit job for execution')
    gflowc.add_argument('--no-compile',
                        default=False,
                        action="store_true",
                        help='skip compile phase and submit job for execution')
    gflowc.add_argument('--recompile',
                        default=False,
                        action="store_true",
                        help='delete the inca/xcelium compiled directory and various log files to')
    gflowc.add_argument('--discovery-only',
                        default=False,
                        action='store_true',
                        help='Perform test discovery, but do not compile or simulate')
    gflowc.add_argument('--no-bazel',
                        default=False,
                        action='store_true',
                        help='skip bazel build, can not use if any BUILD changes')
    gflowc.add_argument('--report',
                        default=False,
                        action='store_true',
                        help='report regression result, default is No')


def add_basic_arguments(parser):
    parser.add_argument(
        '-t',
        '--tests',
        dest='tests',
        default=[],
        action=parser_actions.TestAction,
        help=
        ('Test names to run. This option has some smarts depending on tool invocation directory.\n'
         'If you run in a "bench" directory, just specify a single "glob" of tests that you want to run.\n'
         'E.g. in hw/dv/benches/sys_tb to run all tests in sys_tb:\n'
         '  > simmer -t *\n'
         'If you run at a higher level, or elsewhere in the checkout, you can specify two globs separated by a colon:\n'
         ' bench_glob:test_glob\n'
         'This will glob for bench names, then test names within each bench.\n'
         'E.g. running all tests in all benches:\n'
         ' > simmer -t *:*\n'
         'You can throw this option multiple times to build up specific lists. For example,\n'
         'if we follow naming conventions, you can run all register and interrupt tests:\n'
         ' > simmer -t *:intr* -t *:reg_walk\n'
         'You could also run only specific benches to create different layers:\n'
         ' > simmer -t sys_tb:*quick* -t vector_add_tb:*\n'
         'Finally, the number of iterations may also be specified by an optional "@"\n'
         'The following runs each mosaic test 5 times, which only running the vector_add tests once\n'
         ' > simmer -t sys_tb:*quick*@5 -t vector_add_tb:*@1\n'))

    parser.add_argument('--tag',
                        type=str,
                        action=parser_actions.TagAction,
                        help='Only include tests that match this tag. Must specify indepently for each test glob')
    parser.add_argument('--ntag',
                        type=str,
                        action=parser_actions.TagAction,
                        help='Exclude tests that match this tag. Must specify indepently for each test glob')

    parser.add_argument('--global-tag',
                        default=set(),
                        action=parser_actions.GlobalTagAction,
                        help='Only include tests that match this tag. Affects all test globs')
    parser.add_argument('--global-ntag',
                        default=set(),
                        action=parser_actions.GlobalTagAction,
                        help='Exclude tests that match this tag. Affects all test globs')
    parser.add_argument('--emulator',
                        type=str,
                        default='',
                        choices=['pldm_sa', 'pldm_sim', 'sim', 'clean'],
                        help=
                        ('Declares the platform to use for compile and emulation.\n'
                        'pldm_sa: clean the database, run palladium synthesis, tb compilation, then run the cases\n'
                        'pldm_sim: kept the synthesis database, run palladium tb compilation, then run the cases\n'
                        'sim: without palladium synthesis, compile the emualtion env with simulator, then run the cases with simulator\n'
                        'clean: clean the synthesis database\n'))
    parser.add_argument('--simulator',
                        type=str,
                        default='XRUN',
                        choices=['VCS', 'XRUN'],
                        help='Declares the platform to use for compile and simulation.')


def parse_args(argv):
    """
    simmer configuration is handled through a series of command
    line arguments and a handful of environment variables

    historically, simmer has been dependant on an environment
    variable PROJ_DIR.  to remove this scrict dependency, simmer
    will now check if env(PROJ_DIR) is defined, and if not,
    will use the current working directory

    simmer defaults to using Xcelium for model compiles and
    simulations.  however, the user and/or project can define
    an environement varible SIM_PLATFORM to effectively change
    the default.  the use of --vcs or --xrun on the command line
    will always take precedence over env(SIM_PLATFORM)

    simmer does require either env(VCS_LICENSES) or env(XRUN_LICENSES)
    to be defined and have a non-zero value.  these indicate how many
    licenses are available for compile and simulation jobs
    """

    parser = argparse.ArgumentParser(description="Runs simulations!", formatter_class=argparse.RawTextHelpFormatter)

    # Call the above-defined functions to add arguments to the parser
    add_debug_arguments(parser)
    add_test_configuration_arguments(parser)
    add_regression_arguments(parser)
    add_flow_control_arguments(parser)
    add_basic_arguments(parser)

    options = parser.parse_args(argv)

    # Remove tests from arg parsing for later single test reproduciblity
    skip_list = ['-t', '--tag', '--ntag', '--seed', '--global-tag', '--global-ntag']
    skip_list.append(str(options.seed))
    for test in options.tests:
        skip_list.append(test.btiglob)
        for tag in test.tag:
            skip_list.append(tag)
        for ntag in test.ntag:
            skip_list.append(ntag)
    reproduce_args = [arg for arg in argv if arg not in skip_list]
    setattr(options, 'reproduce_args', reproduce_args)
    SIM_LICENSES = 0
    if options.simulator.upper() == 'VCS' or (SIM_PLATFORM.upper() == 'VCS' and options.simulator.upper() != 'XRUN'):
        options.simulator = 'VCS'
        if options.waves is not None:
            if options.wave_type is None:
                options.wave_type = 'fsdb'
            if options.wave_type == 'shm':
                print('-E- SHM waveform capture format not supported by VCS!')
                sys.exit(99)
        SIM_LICENSES = int(VCS_LICENSES)
    if options.simulator.upper() == 'XRUN' or (SIM_PLATFORM.upper() == 'XRUN' and options.simulator.upper() != 'VCS'):
        options.simulator = 'XRUN'
        if options.waves is not None:
            if options.wave_type is None:
                options.wave_type = 'shm'
        SIM_LICENSES = XRUN_LICENSES
    if SIM_LICENSES == 0:
        print('-E- parse_args: No licenses available!')
        sys.exit(99)
    if options.parallel_max == 0:
        options.parallel_max = int(SIM_LICENSES)
    else:
        if options.parallel_max > int(SIM_LICENSES):
            print('-E- parse_args: --parallel-max is greater than available licenses')
            sys.exit(99)
    if options.msie_href is not None:
        options.no_run = True
    if options.msie_prim is not None:
        options.no_run = True

    options.proj_dir = PROJ_DIR
    return options
