import os

from lib import parser_actions

PROJ_DIR = os.environ.get('PROJ_DIR', os.getcwd())
SIM_PLATFORM = os.environ.get('SIM_PLATFORM', 'XRUN')
_COVFILE = os.environ.get('COVFILE', "coverage.ccf")
COVFILE = _COVFILE if os.path.isabs(_COVFILE) else os.path.join(PROJ_DIR, _COVFILE)


def add_debug_arguments(parser):
    gdebug = parser.add_argument_group('Debug arguments')
    gdebug.add_argument('--waves',
                        default=None,
                        nargs='*',
                        help=('Enable waveform capture. Optionally pass a list of HDL '
                              'paths to reduce probe scope. Default is tb_top.'))
    gdebug.add_argument('--wave-type',
                        type=str,
                        default=None,
                        choices=['shm', 'fsdb', 'vcd', 'vwdb'],
                        help='Specify the waveform format. Supported values depend on the simulator.')
    gdebug.add_argument('--wave-tcl',
                        type=str,
                        default=None,
                        help='Load the local wave.tcl file for waveform. Only used with --wave-tcl + path of wave.tcl')
    gdebug.add_argument('--wave-start',
                        type=int,
                        default=0,
                        help='Specify the sim time in ns to start dumping the waveform.')
    gdebug.add_argument('--wave-end',
                        type=int,
                        default=99999999,
                        help='Specify the sim time in ns to end dumping the waveform.')
    gdebug.add_argument('--wave-depth',
                        type=int,
                        default=999,
                        help='Probe hirarchical depth. Only used with --waves. Default is all hierarchies')
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
                        help=('Shared X-propagation selector. F=more pessimistic mode, C=ternary-like mode, D=Disable. '
                              'On Xcelium, F maps to FOX and C maps to CAT. '
                              'On VCS, F falls back to -xprop=xmerge and C falls back to -xprop=tmerge '
                              'when no VCS xprop config file is present.'))
    gtestc.add_argument('--timeout',
                        default=12.0,
                        type=float,
                        help="Sets the per-job wallclock timeout for simulation in hours.")


def add_regression_arguments(parser):
    gregre = parser.add_argument_group("Regression arguments")

    gregre.add_argument('--python-seed',
                        type=str,
                        default=None,
                        help='Set base seed in python for random seed generation.')
    gregre.add_argument('--idle-print-seconds',
                        type=int,
                        default=60 * 20,
                        help=('Print the state of the queues every few minutes if nothing has finished.\n'
                              'Helpful for debugging hanging tests.\n'))
    gregre.add_argument('--jobs',
                        type=int,
                        default=None,
                        help=('Maximum concurrent compile/simulation jobs. Defaults to the host CPU count, '
                              'adjusted for VCS FGP or Xcelium MCE threads.'))
    gregre.add_argument('--simmer-profile',
                        default=False,
                        action='store_true',
                        help='Print simmer phase/job runtime details for performance tuning.')
    gregre.add_argument('--history',
                        '--his',
                        nargs='?',
                        const=10,
                        default=None,
                        type=int,
                        help='Print recent simmer simulation records. Defaults to 10 entries.')
    gregre.add_argument('--no-stdout',
                        default=False,
                        action='store_true',
                        help=('By default, when running a single test, the vcomp and sim stdout will '
                              'print to screen.\nThis option suppresses the stdout (useful when running '
                              ' a long test with high verbosity.\nIf multiple vcomps or tests are '
                              'discovered, this flag is automatically thrown.\n'))
    gregre.add_argument('--nt',
                        default=False,
                        action='store_true',
                        help=('By default simmer will clean up simulation results when the tests '
                              'pass. This flag prevents that cleanup.'))
    gregre.add_argument('--category-cfg',
                        type=str,
                        nargs='?',
                        const='',
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
    gflowc.add_argument('--report', default=False, action='store_true', help='report regression result, default is No')


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
    parser.add_argument('--simulator',
                        type=str,
                        default='XRUN',
                        choices=['VCS', 'XRUN'],
                        help=('Override the simulator for the selected tests. '
                              'If the selected test cfg rules resolve to a different simulator, '
                              'simmer will report an error before Bazel starts.'))


def argument_explicitly_requested(argv, argument_name):
    return any(arg == argument_name or arg.startswith(argument_name + '=') for arg in argv)


def simulator_explicitly_requested(argv):
    return argument_explicitly_requested(argv, '--simulator')
