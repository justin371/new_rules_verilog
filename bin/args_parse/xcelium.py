import os

from lib import parser_actions

from .common import COVFILE


def add_xcelium_arguments(parser):
    gxrun = parser.add_argument_group("Xcelium arguments")
    gxrun.add_argument('--wave-delta',
                       default=False,
                       action='store_true',
                       help='Capture delta cycles for Xcelium SHM waves.')
    gxrun.add_argument('--probe-packed',
                       type=int,
                       default=128,
                       help='Maximum packed-array probe depth for Xcelium waves.')
    gxrun.add_argument('--probe-unpacked',
                       type=int,
                       default=128,
                       help='Maximum unpacked-array probe depth for Xcelium waves.')
    gxrun.add_argument('--profile',
                       default=False,
                       action='store_true',
                       help='Dump simulation profiling information to file. (Cadence only.)')
    gxrun.add_argument('--mce',
                       default=False,
                       action='store_true',
                       help='Multicore license enable for XRUN. Only used for Gatesim!')
    gxrun.add_argument('--mce-build-count',
                       type=int,
                       default=4,
                       help=("Number of threads to be used for mce elaboration. "
                             "0 means a full range, used with --mce"))
    gxrun.add_argument('--mce-build-cfg',
                       type=str,
                       default='single-socket',
                       choices=['single-socket', 'all-cores'],
                       help="The number of cores to be used for build, used with --mce")
    gxrun.add_argument('--mce-sim-count',
                       type=int,
                       default=4,
                       help=("Number of threads to be used for mce simulation. "
                             "0 means a full range, used with --mce"))
    gxrun.add_argument('--mce-sim-cfg',
                       type=str,
                       default='single-socket',
                       choices=['single-socket', 'single-threaded', 'partial-socket', 'all-cores'],
                       help="The number of cores to be used for sim, used with --mce")
    gxrun.add_argument('--mce-split-max-size',
                       type=int,
                       default=500000,
                       help=("Size of spilt to be used for mce sim. "
                             "used with --mce"))
    gxrun.add_argument(
        '--coverage',
        action=parser_actions.CovAction,
        help=f'Enable Code Coverage for xcelium only.\n{parser_actions.CovAction.format_options(indent=0)}')
    gxrun.add_argument('--covfile', default=COVFILE, help='Path to Coverage configuration file')
    gxrun.add_argument('--msie',
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
    gxrun.add_argument('--msie-href',
                       type=str,
                       nargs='?',
                       const='tb_top',
                       default=None,
                       help='Gen href in benches/tb_name/hdl/href.txt \n'
                       'Need define prim top, default is tb_top'
                       'eg. --msie-href pcpu')
    gxrun.add_argument('--msie-prim',
                       type=str,
                       nargs='?',
                       const='tb_top',
                       default=None,
                       help='Compile prim lib, need define prim top, default is tb_top')
    gxrun.add_argument('--msie-incr',
                       type=str,
                       nargs='?',
                       default=None,
                       help='Compile incr, need define prim top, default is tb_top')
    gxrun.add_argument(
        '--emulator',
        type=str,
        default='',
        choices=['pldm_sa', 'pldm_sim', 'sim', 'clean'],
        help=
        ('Declares the platform to use for compile and emulation.\n'
         'pldm_sa: clean the database, run palladium synthesis, tb compilation, then run the cases\n'
         'pldm_sim: kept the synthesis database, run palladium tb compilation, then run the cases\n'
         'sim: without palladium synthesis, compile the emualtion env with simulator, then run the cases with simulator\n'
         'clean: clean the synthesis database\n'))


def validate_xcelium_switches_for_vcs(options, parser):
    xcelium_only_switches = []
    if options.profile:
        xcelium_only_switches.append('--profile')
    if options.wave_delta:
        xcelium_only_switches.append('--wave-delta')
    if options.probe_packed != 128:
        xcelium_only_switches.append('--probe-packed')
    if options.probe_unpacked != 128:
        xcelium_only_switches.append('--probe-unpacked')
    if options.mce:
        xcelium_only_switches.append('--mce')
    if options.mce_build_count != 4:
        xcelium_only_switches.append('--mce-build-count')
    if options.mce_build_cfg != 'single-socket':
        xcelium_only_switches.append('--mce-build-cfg')
    if options.mce_sim_count != 4:
        xcelium_only_switches.append('--mce-sim-count')
    if options.mce_sim_cfg != 'single-socket':
        xcelium_only_switches.append('--mce-sim-cfg')
    if options.mce_split_max_size != 500000:
        xcelium_only_switches.append('--mce-split-max-size')
    if options.coverage:
        xcelium_only_switches.append('--coverage')
    if options.covfile_was_explicit:
        xcelium_only_switches.append('--covfile')
    if options.msie is not None:
        xcelium_only_switches.append('--msie')
    if options.msie_href is not None:
        xcelium_only_switches.append('--msie-href')
    if options.msie_prim is not None:
        xcelium_only_switches.append('--msie-prim')
    if options.msie_incr is not None:
        xcelium_only_switches.append('--msie-incr')
    if options.emulator:
        xcelium_only_switches.append('--emulator')
    if xcelium_only_switches:
        parser.error("The following switches are Xcelium-only and cannot be used with VCS: {}. "
                     "Stopping before Bazel starts.".format(", ".join(xcelium_only_switches)))


def validate_xcelium_runtime_options(options, parser):
    if options.gui:
        parser.error("Xcelium supports batch mode only; --gui is allowed only with VCS. Stopping before Bazel starts.")
    if options.waves is not None:
        if options.wave_type is None:
            options.wave_type = 'vwdb'
        if options.wave_type not in ['shm', 'vcd', 'vwdb']:
            parser.error("Xcelium supports only --wave-type shm, vcd, or vwdb. Stopping before Bazel starts.")
    if options.covfile_was_explicit and not options.coverage:
        parser.error("--covfile requires --coverage. Stopping before Bazel starts.")
    if options.coverage and options.covfile_was_explicit and not os.path.isfile(options.covfile):
        parser.error("The specified Xcelium coverage configuration file does not exist: {}. "
                     "Stopping before Bazel starts.".format(options.covfile))
    if options.mce_detail_was_explicit and not options.mce:
        parser.error("Xcelium MCE detail switches require --mce. Stopping before Bazel starts.")
    if options.mce_build_count < 0 or options.mce_sim_count < 0:
        parser.error("Xcelium MCE thread counts must be non-negative. Stopping before Bazel starts.")
    if options.mce_split_max_size <= 0:
        parser.error("--mce-split-max-size must be positive. Stopping before Bazel starts.")
    msie_modes = [options.msie, options.msie_href, options.msie_prim, options.msie_incr]
    if sum(mode is not None for mode in msie_modes) > 1:
        parser.error("Use only one of --msie, --msie-href, --msie-prim, or --msie-incr per invocation. "
                     "Stopping before Bazel starts.")
    if options.emulator and (options.mce or any(mode is not None for mode in msie_modes)):
        parser.error("--emulator cannot be combined with MCE or MSIE modes. Stopping before Bazel starts.")


def apply_xcelium_postprocess(options):
    if options.msie_href is not None:
        options.no_run = True
    if options.msie_prim is not None:
        options.no_run = True
