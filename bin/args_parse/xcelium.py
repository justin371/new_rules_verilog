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
        help=('Enable XRUN Multicore Engine for compile and simulation. Requires MCE licenses; xprop is ignored and '
              'MSIE or emulator modes are rejected.'))
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
    gxrun.add_argument(
        '--msie',
        metavar='PRIMARY_TOP',
        help=('Enable XRUN single-step MSIE for the named stable primary top. Preparation: configure the complete '
              'testbench in verilog_dv_tb.deps; XRUN partitions that command automatically. This mode does not use '
              'the multi-step primary/incremental deps; xprop is ignored and MCE or emulator modes are rejected.'))
    gxrun.add_argument(
        '--msie-href',
        metavar='PRIMARY_TOP',
        help=('Run the first multi-step MSIE stage for the named stable DUT/netlist top, generate href and externs '
              'under <tb>__XRUN_VCOMP_MSIE, then stop. Preparation: configure the complete model in '
              'verilog_dv_tb.deps. Run this before --msie-prim; xprop is ignored and other MSIE modes, MCE, or '
              'emulator are rejected.'))
    gxrun.add_argument(
        '--msie-prim',
        metavar='PRIMARY_TOP',
        help=('Run the second multi-step MSIE stage for the named stable DUT/netlist top, then stop. Preparation: '
              'configure verilog_dv_tb.msie_primary_deps and complete --msie-href for the same target first. The '
              'snapshot name defaults to PRIMARY_TOP and can be changed with --msie-primary-name.'))
    gxrun.add_argument(
        '--msie-incr',
        type=str,
        metavar='PRIMARY_SNAPSHOT',
        default=None,
        help=('Run the final multi-step MSIE stage and simulations against PRIMARY_SNAPSHOT. Preparation: configure '
              'verilog_dv_tb.msie_incremental_deps and complete matching href/primary stages in the same regression '
              'directory. Simmer validates the primary manifest before XRUN starts.'))
    gxrun.add_argument(
        '--msie-primary-name',
        metavar='SNAPSHOT',
        help=('Name the snapshot created by --msie-prim independently from its HDL top. Use the same value as the '
              'later --msie-incr argument; for example, top dut with snapshot dut_sdf_wc.'))
    gxrun.add_argument(
        '--msie-primary-top',
        metavar='PRIMARY_TOP',
        help=('Override the primary HDL top expected by --msie-incr. The default is the selected verilog_dv_tb '
              'dut_top value; set this only when the primary build used a different top.'))
    gxrun.add_argument(
        '--msie-primary-key',
        metavar='KEY',
        default='',
        help=('Add an immutable site key to the primary compatibility manifest for --msie-prim/--msie-incr. Include '
              'the Xcelium release, netlist release and gatesim corner when those identities are not encoded by the '
              'Bazel target, for example XCELIUM-25.03:netlist-r42:sdf_wc.'))
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
