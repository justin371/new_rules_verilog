import argparse
import textwrap

from .common import (
    PROJ_DIR,
    SIM_PLATFORM,
    add_basic_arguments,
    add_debug_arguments,
    add_flow_control_arguments,
    add_regression_arguments,
    add_test_configuration_arguments,
    argument_explicitly_requested,
    simulator_explicitly_requested,
)
from .vcs import add_vcs_arguments
from .xcelium import (
    add_xcelium_arguments, )

_RERUN_OMITTED_OPTIONS = {
    '-t',
    '--tests',
    '--tag',
    '--ntag',
    '--seed',
    '--global-tag',
    '--global-ntag',
}

_HELP_WIDTH = 150


class SimmerHelpFormatter(argparse.HelpFormatter):

    def __init__(self, prog):
        super().__init__(prog, width=_HELP_WIDTH)

    @staticmethod
    def _wrap_line(line, width):
        if not line.strip():
            return ['']
        leading_space = line[:len(line) - len(line.lstrip())]
        wrapped = textwrap.wrap(
            line.strip(),
            width=max(1, width - len(leading_space)),
            break_long_words=False,
            break_on_hyphens=False,
        )
        return [leading_space + part for part in wrapped]

    def _split_lines(self, text, width):
        return [line for source_line in text.splitlines() for line in self._wrap_line(source_line, width)]

    def _fill_text(self, text, width, indent):
        return '\n'.join(indent + line for source_line in text.splitlines()
                         for line in self._wrap_line(source_line, width))

    def _format_action(self, action):
        if not getattr(action, 'simmer_parent', None):
            return super()._format_action(action)
        self._current_indent += 2
        try:
            return super()._format_action(action)
        finally:
            self._current_indent -= 2


def reproduction_args(argv):
    """Keep original options except selectors replaced by rerun.sh."""
    result = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        option_name = argument.split('=', 1)[0]
        if option_name in _RERUN_OMITTED_OPTIONS:
            index += 1 if '=' in argument else 2
            continue
        if argument.startswith('-t') and not argument.startswith('--'):
            index += 1
            continue
        result.append(argument)
        index += 1
    return result


def create_parser():
    parser = argparse.ArgumentParser(
        prog="simmer",
        description=(
            "Discover, compile, run, retain, and report Verilog/SystemVerilog regressions with VCS or XRUN.\n"
            "Preparation: run from a configured project checkout with Bazel 7.7.1, Python 3.12, and the selected "
            "EDA environment sourced. Quote all test globs."),
        epilog=
        ("Start safely with: simmer -t 'bench:test@1' --simulator VCS --discovery-only\n"
         "Then run without --discovery-only. Use --simmer-profile and the per-job logs to diagnose performance.\n"
         "XRUN gatesim MSIE, after configuring verilog_dv_tb MSIE deps, uses the same target/SIMRESULTS/suffix:\n"
         "  simmer -t 'gate_tb:test@1' --simulator XRUN --msie-href dut\n"
         "  simmer -t 'gate_tb:test@1' --simulator XRUN --msie-prim dut --msie-primary-name dut_wc --msie-primary-key KEY\n"
         "  simmer -t 'gate_tb:test@1' --simulator XRUN --msie-incr dut_wc --msie-primary-key KEY"),
        formatter_class=SimmerHelpFormatter,
        allow_abbrev=False,
    )

    add_debug_arguments(parser)
    add_test_configuration_arguments(parser)
    add_xcelium_arguments(parser)
    add_vcs_arguments(parser)
    add_regression_arguments(parser)
    add_flow_control_arguments(parser)
    add_basic_arguments(parser)
    return parser


def parse_args(argv):
    """Parse and validate simmer command-line options."""
    parser = create_parser()

    options = parser.parse_args(argv)
    if options.jobs is not None and options.jobs < 1:
        parser.error("--jobs must be a positive integer.")
    if options.quit_count < 1:
        parser.error("--quit-count must be a positive integer.")
    if options.uvm_max_quit_count < 0:
        parser.error("--uvm-max-quit-count must be non-negative (0 disables the limit).")
    if options.idle_print_seconds < 1:
        parser.error("--idle-print-seconds must be a positive integer.")
    if options.history is not None and options.history < 1:
        parser.error("--history must be a positive integer.")
    if options.timeout < 0:
        parser.error("--timeout must be non-negative (0 disables the timeout).")
    options.simulator_was_explicit = simulator_explicitly_requested(argv)
    options.xprop_was_explicit = any(
        argument_explicitly_requested(argv, argument) for argument in ('--xprop', '--vcs-xprop'))
    options.timeout_was_explicit = argument_explicitly_requested(argv, '--timeout')
    options.covfile_was_explicit = argument_explicitly_requested(argv, '--covfile')
    options.mce_detail_was_explicit = any(
        argument_explicitly_requested(argv, argument) for argument in [
            '--mce-build-count',
            '--mce-build-cfg',
            '--mce-sim-count',
            '--mce-sim-cfg',
            '--mce-split-max-size',
        ])
    options.xcelium_explicit_switches = [
        argument for argument in [
            '--wave-delta',
            '--probe-packed',
            '--probe-unpacked',
            '--profile',
            '--mce',
            '--mce-build-count',
            '--mce-build-cfg',
            '--mce-sim-count',
            '--mce-sim-cfg',
            '--mce-split-max-size',
            '--coverage',
            '--covfile',
            '--msie',
            '--msie-href',
            '--msie-prim',
            '--msie-incr',
            '--msie-primary-name',
            '--msie-primary-top',
            '--msie-primary-key',
            '--emulator',
        ] if argument_explicitly_requested(argv, argument)
    ]
    options.vcs_explicit_switches = [
        argument for argument in [
            '--vcs-cm',
            '--cm',
            '--gui',
            '--vcs-cm-line',
            '--vcs-cm-report',
            '--vcs-cm-cond',
            '--vcs-cm-tgl',
            '--vcs-cm-hier',
            '--vcs-profile',
            '--vcs-urg-parallel',
            '--vcs-urg-show-tests',
            '--vcs-partcomp',
            '--no-vcs-partcomp',
            '--vcs-partcomp-mode',
            '--vcs-partcomp-jobs',
            '--vcs-partcomp-dir',
            '--vcs-partcomp-sharedlib',
            '--vcs-auto-compile-cache',
            '--no-vcs-auto-compile-cache',
            '--smartlog',
            '--vcs-runner',
            '--dtl',
            '--fgp',
            '--vcs-xprop',
            '--vcs-xprop-flowctrl',
            '--vcs-xprop-mmsopt',
            '--vcs-xprop-banner',
            '--vcs-xprop-report',
            '--ico',
            '--ico-workdir',
            '--ico-shared-record',
            '--vso',
            '--vso-workdir',
            '--vso-dbdir',
            '--vso-buildname',
            '--vso-target-metric',
            '--vso-phase',
            '--vso-cbv',
            '--vso-ccex',
            '--vso-ccex-rca',
            '--vso-ccex-auto-merge-dir',
        ] if argument_explicitly_requested(argv, argument)
    ]

    options.reproduce_args = reproduction_args(argv)

    options.simulator = (options.simulator if options.simulator_was_explicit else SIM_PLATFORM).upper()
    wave_detail_switches = [
        '--wave-type',
        '--wave-tcl',
        '--wave-start',
        '--wave-end',
        '--wave-depth',
    ]
    requested_wave_details = [
        argument for argument in wave_detail_switches if argument_explicitly_requested(argv, argument)
    ]
    if options.waves is None and requested_wave_details:
        parser.error("{} require --waves.".format(", ".join(requested_wave_details)))
    if options.wave_start < 0:
        parser.error("--wave-start must be non-negative.")
    if options.wave_end <= options.wave_start:
        parser.error("--wave-end must be greater than --wave-start.")
    if options.wave_depth <= 0:
        parser.error("--wave-depth must be positive.")
    options.proj_dir = PROJ_DIR
    return options
