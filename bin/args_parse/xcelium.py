import os

from lib import parser_actions

from .common import COVFILE


def add_xcelium_arguments(parser):
    gxrun = parser.add_argument_group(
        "Xcelium arguments",
        "XRUN-only controls. Source the Cadence environment first. Explicit XRUN options are rejected when the selected backend is VCS."
    )
    gxrun.add_argument(
        '--wave-delta',
        default=False,
        action='store_true',
        help='Include delta-cycle activity in generated XRUN SHM waveform probes. Requires --waves --wave-type shm.')
    gxrun.add_argument(
        '--probe-packed',
        type=int,
        default=128,
        help='Set the XRUN probe limit for packed arrays (default: 128). Used only with generated waveform probes.')
    gxrun.add_argument(
        '--probe-unpacked',
        type=int,
        default=128,
        help='Set the XRUN probe limit for unpacked arrays (default: 128). Used only with generated waveform probes.')
    gxrun.add_argument(
        '--profile',
        default=False,
        action='store_true',
        help='Pass -profile to XRUN simulation and retain the Cadence profiling output in the test result directory.')
    gxrun.add_argument(
        '--mce',
        default=False,
        action='store_true',
        help=('Enable XRUN Multicore Engine for compile and simulation. Requires MCE licenses and cannot be '
              'combined with --xprop, MSIE, or --emulator.'))
    gxrun.add_argument('--mce-build-count',
                       type=int,
                       default=4,
                       help=('Set XRUN MCE build thread count (default: 4; 0 lets XRUN use the configuration range). '
                             'Requires --mce.'))
    gxrun.add_argument('--mce-build-cfg',
                       type=str,
                       default='single-socket',
                       choices=['single-socket', 'all-cores'],
                       help='Select the XRUN MCE build CPU topology (default: single-socket). Requires --mce.')
    gxrun.add_argument(
        '--mce-sim-count',
        type=int,
        default=4,
        help=('Set XRUN MCE simulation thread count (default: 4; 0 lets XRUN use the configuration range). '
              'Requires --mce; simmer adjusts job concurrency for this count.'))
    gxrun.add_argument('--mce-sim-cfg',
                       type=str,
                       default='single-socket',
                       choices=['single-socket', 'single-threaded', 'partial-socket', 'all-cores'],
                       help='Select the XRUN MCE simulation CPU topology (default: single-socket). Requires --mce.')
    gxrun.add_argument('--mce-split-max-size',
                       type=int,
                       default=500000,
                       help='Set the positive XRUN MCE partition split-size limit (default: 500000). Requires --mce.')
    gxrun.add_argument('--coverage',
                       action=parser_actions.CovAction,
                       help=(f'Enable XRUN coverage collection and generate the IMC merge/report flow.\n'
                             f'Use A for all metrics or join metrics with a colon, for example B:E:F:T:U.\n'
                             f'{parser_actions.CovAction.format_options(indent=0)}'))
    gxrun.add_argument(
        '--covfile',
        default=COVFILE,
        help=('Pass an existing Xcelium coverage configuration file. An explicitly supplied path requires '
              '--coverage and is validated before Bazel starts; otherwise the testbench xcelium_covfile is preferred.'))
    gxrun.add_argument('--msie',
                       type=str,
                       default=None,
                       nargs='?',
                       const='tb_top',
                       help=('Enable XRUN MSIE single-step automatic mode; optional value is the primary top '
                             '(default: tb_top). Preparation: provide the generated MSIE filelists and an incr_pkg.sv '
                             'that packages changing tests. Cannot be combined with --xprop, --mce, or --emulator.'))
    gxrun.add_argument('--msie-href',
                       type=str,
                       nargs='?',
                       const='tb_top',
                       default=None,
                       help=('Generate the XRUN MSIE hierarchy-reference file for the optional primary top '
                             '(default: tb_top), then stop before simulation. Run this before --msie-prim; '
                             'cannot be combined with other MSIE modes, --xprop, --mce, or --emulator.'))
    gxrun.add_argument('--msie-prim',
                       type=str,
                       nargs='?',
                       const='tb_top',
                       default=None,
                       help=('Build the XRUN MSIE primary snapshot for the optional primary top (default: tb_top), '
                             'then stop before simulation. Requires the href/filelist generated for this bench; '
                             'cannot be combined with other MSIE modes, --xprop, --mce, or --emulator.'))
    gxrun.add_argument(
        '--msie-incr',
        type=str,
        default=None,
        help=('Build the XRUN MSIE incremental partition against the named primary snapshot. '
              'Preparation: complete --msie-href and --msie-prim for the same source/configuration first. '
              'Cannot be combined with other MSIE modes, --xprop, --mce, or --emulator.'))
    gxrun.add_argument(
        '--emulator',
        type=str,
        default='',
        choices=['pldm_sa', 'pldm_sim', 'sim', 'clean'],
        help=
        ('Select the project-provided Xcelium/Palladium template flow. Requires EMU_JINJA2_PATH and site runtime libraries.\n'
         'pldm_sa: clean the database, run Palladium synthesis and TB compile, then run tests.\n'
         'pldm_sim: reuse synthesis output, compile the Palladium TB, then run tests.\n'
         'sim: compile and run the emulation environment with XRUN without Palladium synthesis.\n'
         'clean: run the project clean flow. Emulator modes cannot be combined with MCE or MSIE.'))


def validate_xcelium_switches_for_vcs(options, parser):
    xcelium_only_switches = options.xcelium_explicit_switches
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
    if options.wave_delta and (options.waves is None or options.wave_type != 'shm'):
        parser.error("--wave-delta requires '--waves --wave-type shm'. Stopping before Bazel starts.")
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
    if options.xprop and (options.mce or any(mode is not None for mode in msie_modes)):
        parser.error("--xprop cannot be combined with Xcelium MCE or MSIE modes. Stopping before Bazel starts.")
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
