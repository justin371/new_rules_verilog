import os

from lib import parser_actions

PROJ_DIR = os.environ.get('PROJ_DIR', os.getcwd())
SIM_PLATFORM = os.environ.get('SIM_PLATFORM', 'XRUN')
_COVFILE = os.environ.get('COVFILE', "coverage.ccf")
COVFILE = _COVFILE if os.path.isabs(_COVFILE) else os.path.join(PROJ_DIR, _COVFILE)
REPORT_DIR = os.environ.get("SIMMER_REPORT_DIR")


def add_child_argument(container, *args, parent, **kwargs):
    action = container.add_argument(*args, **kwargs)
    action.simmer_parent = parent
    return action


def add_debug_arguments(parser):
    debug_group = parser.add_argument_group(
        'Debug arguments',
        'Waveform and UVM diagnostics shared by both backends. Wave capture increases compile time, runtime, and disk use.'
    )
    debug_group.add_argument(
        '--waves',
        default=None,
        nargs='*',
        help=('Enable waveform capture. Optionally list HDL scopes after the option; with no scopes, '
              'the simulator adapter uses its default top. Quote wildcard scopes so the shell does not expand them.'))
    # The common parser records the requested format; the selected simulator
    # adapter supplies its default and rejects formats it cannot produce.
    add_child_argument(debug_group,
                       '--wave-type',
                       parent='--waves',
                       type=str,
                       default=None,
                       metavar='FORMAT',
                       help=('Select the simulator-specific waveform database format. The selected backend '
                             'applies its default and validates supported formats. Requires --waves.'))
    add_child_argument(debug_group,
                       '--wave-tcl',
                       parent='--waves',
                       type=str,
                       default=None,
                       help=('Use an existing simulator-specific wave/probe Tcl file instead of generated commands. '
                             'The file must exist and is used only when waveform capture is enabled; custom Tcl '
                             'controls scopes, depth, and dump timing, while --wave-type still selects the expected '
                             'artifact format.'))
    add_child_argument(
        debug_group,
        '--wave-start',
        parent='--waves',
        type=int,
        default=0,
        help='Start waveform dumping at this non-negative simulation time in ns (default: 0). Requires --waves.')
    add_child_argument(debug_group,
                       '--wave-end',
                       parent='--waves',
                       type=int,
                       default=99999999,
                       help=('Stop waveform dumping at this simulation time in ns (default: effectively unlimited). '
                             'It must be greater than --wave-start. Requires --waves.'))
    add_child_argument(debug_group,
                       '--wave-depth',
                       parent='--waves',
                       type=int,
                       default=999,
                       help=('Set generated probe hierarchy depth (default: 999, effectively all hierarchy). '
                             'Reduce it to limit waveform size. Requires --waves.'))
    debug_group.add_argument('--verbosity',
                             type=str,
                             default=None,
                             choices=['UVM_NONE', 'UVM_LOW', 'UVM_MEDIUM', 'UVM_HIGH', 'UVM_FULL', 'UVM_DEBUG'],
                             help='Pass +UVM_VERBOSITY=LEVEL to every selected simulation.')
    debug_group.add_argument(
        '--uvm-set-verbosity',
        type=str,
        default=None,
        nargs="+",
        help=('Pass one or more +uvm_set_verbosity settings. Each value must be '
              '<component>,<id>,<verbosity>,<phase>; quote values containing shell metacharacters.'))
    debug_group.add_argument(
        '--uvm-config-db-trace',
        default=False,
        action="store_true",
        help='Pass +UVM_CONFIG_DB_TRACE to log every UVM config_db access; expect significantly larger logs.')
    debug_group.add_argument(
        '--uvm-resource-db-trace',
        default=False,
        action="store_true",
        help='Pass +UVM_RESOURCE_DB_TRACE to log every UVM resource_db access; expect significantly larger logs.')
    debug_group.add_argument('--uvm-max-quit-count',
                             type=int,
                             default=10,
                             help=('Pass +UVM_MAX_QUIT_COUNT=N (default: 10) to stop after N counted UVM errors; '
                                   'use 0 to omit the limit.'))
    debug_group.add_argument(
        '--skip-parse-sim-log',
        default=False,
        action='store_true',
        help=('Do not apply simmer pass/fail regex parsing after simulation. The simulator exit code still applies; '
              'use only when a project log parser is known to misclassify output.'))
    debug_group.add_argument(
        '--tool-debug',
        default=False,
        action='store_true',
        help=
        'Enable simmer internal debug logging, including discovery and scheduler details; does not enable EDA debug.')
    debug_group.add_argument(
        '--dir-suffix',
        type=str,
        default="",
        help=("Append a stable suffix to VCOMP and simulation result directories for side-by-side runs. "
              "Simmer inserts one underscore separator, whether or not the value starts with one. "
              "Reusing the same suffix reuses or overwrites that suffixed run."))
    debug_group.add_argument('--use-color',
                             default=False,
                             action="store_true",
                             help="Enable ANSI colors in simmer terminal output; disable for plain CI logs.")
    debug_group.add_argument('--quit-count',
                             default=10,
                             type=int,
                             help=("Stop launching new jobs after this positive number of failures (default: 10); "
                                   "running jobs finish normally."))
    debug_group.add_argument(
        "--allow-no-run",
        default=False,
        action='store_true',
        help='Include tests tagged no_run. Use only when their external prerequisites have been prepared.')
    debug_group.add_argument(
        '--file',
        dest='compile_args_file',
        type=str,
        default=None,
        help=('Pass an existing local source/compile argument file to the selected simulator before the '
              'Bazel-generated filelist. Paths inside it are interpreted from the EDA runfiles directory.'))


def add_test_configuration_arguments(parser):
    test_config_group = parser.add_argument_group("Test configuration arguments")
    test_config_group.add_argument(
        '--seed',
        type=int,
        default=None,
        help='Use one exact simulator seed. Allowed only when one test iteration is selected.')
    test_config_group.add_argument(
        '--rtl-defines',
        type=str,
        default=None,
        nargs="+",
        help=('Add compile-time RTL/SystemVerilog defines. Any change invalidates --no-compile reuse; '
              'pass each define as NAME or NAME=VALUE.'))
    test_config_group.add_argument(
        '--sim-opts',
        type=str,
        default=[],
        nargs="+",
        help=('Pass one or more runtime arguments to simv/xrun. These override matching '
              'verilog_dv_test_cfg sim_opts; quote each value, for example --sim-opts "+wdog=1000000".'))
    test_config_group.add_argument(
        '--sim-opts-file',
        type=str,
        default=None,
        help=('Read runtime arguments from an existing text file. Simmer shell-tokenizes each non-comment line '
              'and appends the resulting arguments to simv/xrun.'))
    test_config_group.add_argument(
        '--uvm-set-int',
        type=str,
        default=None,
        nargs="+",
        help='Pass each value as +uvm_set_config_int=<value>; expected format: component,field,integer.')
    test_config_group.add_argument(
        '--uvm-set-str',
        type=str,
        default=None,
        nargs="+",
        help='Pass each value as +uvm_set_config_string=<value>; expected format: component,field,string.')
    test_config_group.add_argument(
        '--uvm-set-config-int',
        type=str,
        default=None,
        nargs="+",
        help=('Pass one or more +uvm_set_config_int=<component>,<field>,<value> runtime settings. '
              'Quote wildcard component paths.'))
    test_config_group.add_argument(
        '--uvm-set-config-string',
        type=str,
        default=None,
        nargs="+",
        help=('Pass one or more +uvm_set_config_string=<component>,<field>,<value> runtime settings. '
              'Quote wildcard component paths and values containing spaces.'))
    test_config_group.add_argument(
        '--xprop',
        type=str,
        default=None,
        action=parser_actions.XpropAction,
        help=('Opt-in X-propagation selector. F=more pessimistic mode, C=ternary-like mode, D=Disable. '
              'On Xcelium, F maps to FOX and C maps to CAT. For VCS, prefer --vcs-xprop; this '
              'shared spelling remains compatible.'))
    test_config_group.add_argument(
        '--timeout',
        default=12.0,
        type=float,
        help=("Set the per-simulation wall-clock timeout in hours (default: 12). Use 0 to disable it; "
              "a test_cfg timeout applies unless this option is explicitly supplied."))


def add_regression_arguments(parser):
    regression_group = parser.add_argument_group("Regression arguments",
                                                 "Scheduler, retention, history, and performance controls.")

    regression_group.add_argument(
        '--python-seed',
        type=str,
        default=None,
        help='Set the deterministic Python seed used to pre-plan per-iteration simulator seeds.')
    regression_group.add_argument(
        '--idle-print-seconds',
        type=int,
        default=60 * 20,
        help=('Print compile/simulation queue state after this positive number of idle seconds (default: 1200). '
              'Use a smaller value when diagnosing stalled jobs.'))
    regression_group.add_argument('--jobs',
                                  type=int,
                                  default=None,
                                  help=('Maximum concurrent compile/simulation jobs. By default simmer uses the '
                                        'LSF/Slurm or process-affinity CPU allocation, applies a conservative '
                                        'fallback cap, and adjusts for VCS FGP or Xcelium MCE threads.'))
    regression_group.add_argument(
        '--simmer-profile',
        default=False,
        action='store_true',
        help=('Print elapsed time for discovery phases, individual external repository events, compile jobs, '
              'simulation jobs, coverage, and report generation.'))
    regression_group.add_argument(
        '--history',
        '--his',
        nargs='?',
        const=10,
        default=None,
        type=int,
        help='Print retained simulation records and exit. With no value show 10; otherwise require a positive count.')
    regression_group.add_argument(
        '--rerun-report',
        metavar='MANIFEST',
        default=None,
        help=('Rerun failed VCS tests recorded by a regression report manifest, merge successful rerun coverage '
              'into its preserved baseline, and publish a new revision report.'))
    regression_group.add_argument(
        '--no-stdout',
        default=False,
        action='store_true',
        help=('Suppress live compile/simulation stdout and keep output in job logs. Multiple discovered jobs '
              'enable this automatically to prevent interleaved terminal output.'))
    regression_group.add_argument(
        '--nt',
        default=False,
        action='store_true',
        help=('Retain passed simulation result directories instead of cleaning them. Use for debug artifacts; '
              'expect higher disk use. Failed test results are retained regardless.'))
    regression_group.add_argument('--category-cfg',
                                  type=str,
                                  nargs='?',
                                  const='',
                                  default=None,
                                  help=('Enable category reporting. Optionally provide a JSON path; with no value, use '
                                        '<proj_dir>/category_config.json.'))


def add_flow_control_arguments(parser):
    flow_control_group = parser.add_argument_group("Flow control arguments",
                                                   "Control which build, compile, run, and report phases execute.")
    flow_control_group.add_argument('--no-run',
                                    default=False,
                                    action="store_true",
                                    help='Run Bazel and simulator compilation only; do not launch simulation jobs.')
    flow_control_group.add_argument(
        '--no-compile',
        default=False,
        action="store_true",
        help=('Skip simulator compilation and reuse the existing VCOMP executable/database. Simmer validates the '
              'compile fingerprint and required artifacts before launching simulations.'))
    flow_control_group.add_argument(
        '--recompile',
        default=False,
        action="store_true",
        help=(
            'Delete the selected simulator VCOMP directory before compiling. For VCS this removes simv, csrc, '
            'and the default local partition database; custom external partcomp/sharedlib directories are preserved.'))
    flow_control_group.add_argument(
        '--discovery-only',
        default=False,
        action='store_true',
        help='Run Bazel query/test discovery and print the selected plan without compiling or simulating.')
    flow_control_group.add_argument(
        '--no-bazel',
        default=False,
        action='store_true',
        help=('Skip Bazel build and reuse existing bazel-bin/runfiles outputs. Use only when BUILD files, generated '
              'filelists, source dependencies, and rule inputs are unchanged; commonly paired with --no-compile.'))
    report_toggle_group = flow_control_group.add_mutually_exclusive_group()
    report_toggle_group.add_argument(
        '--report',
        dest='report',
        default=None,
        action='store_true',
        help=('Generate/update the retained static HTML regression dashboard after coverage processing. By default, '
              'reports are generated only when more than one simulation is planned.'))
    report_toggle_group.add_argument('--no-report',
                                     dest='report',
                                     action='store_false',
                                     help='Disable HTML report generation for this regression.')
    flow_control_group.add_argument('--report-dir',
                                    default=REPORT_DIR,
                                    help=('Set the dashboard output root. Default comes from SIMMER_REPORT_DIR or '
                                          '<regression-dir>/regression_results; entry page: '
                                          'regression_report/index.html.'))


def add_basic_arguments(parser):
    parser.add_argument(
        '-t',
        '--tests',
        dest='tests',
        default=[],
        action=parser_actions.TestAction,
        help=(
            'Select tests using a quoted bench:test glob; append @N for N iterations. Quote every selector so the shell '
            'does not expand * before simmer receives it. Repeat -t to combine selections.\n'
            'From a bench directory, a test-only glob is accepted: simmer -t "*".\n'
            'From elsewhere: simmer -t "sys_tb:*quick*@5" -t "vector_add_tb:*@1".'))

    parser.add_argument(
        '--tag',
        type=str,
        action=parser_actions.TagAction,
        help='Require this tag for the nearest preceding -t selector. Repeat after each selector that needs it.')
    parser.add_argument(
        '--ntag',
        type=str,
        action=parser_actions.TagAction,
        help='Exclude this tag from the nearest preceding -t selector. Repeat after each selector that needs it.')

    parser.add_argument(
        '--global-tag',
        default=set(),
        action=parser_actions.GlobalTagAction,
        help='Require this tag for every -t selector. Repeat the option to require additional global tags.')
    parser.add_argument(
        '--global-ntag',
        default=set(),
        action=parser_actions.GlobalTagAction,
        help='Exclude this tag from every -t selector. Repeat the option for additional global exclusions.')
    parser.add_argument('--simulator',
                        type=str,
                        default='XRUN',
                        choices=['VCS', 'XRUN'],
                        help=('Select VCS or XRUN when test cfg metadata does not already determine the backend. '
                              'Without an explicit option, SIM_PLATFORM is used (fallback: XRUN). A mismatch with '
                              'selected test cfg rules is rejected before Bazel starts.'))


def argument_explicitly_requested(argv, argument_name):
    return any(arg == argument_name or arg.startswith(argument_name + '=') for arg in argv)


def simulator_explicitly_requested(argv):
    return argument_explicitly_requested(argv, '--simulator')
