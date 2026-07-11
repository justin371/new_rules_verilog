import argparse

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
from .vcs import add_vcs_arguments, validate_vcs_runtime_options, validate_vcs_switches_for_xcelium
from .xcelium import (
    add_xcelium_arguments,
    apply_xcelium_postprocess,
    validate_xcelium_runtime_options,
    validate_xcelium_switches_for_vcs,
)

_RERUN_OMITTED_OPTIONS = {
    '-t',
    '--tests',
    '--tag',
    '--ntag',
    '--seed',
    '--global-tag',
    '--global-ntag',
}


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


def validate_simulator_specific_options(options, parser):
    if options.simulator == 'VCS':
        validate_xcelium_switches_for_vcs(options, parser)
        validate_vcs_runtime_options(options, parser)
        return

    if options.simulator == 'XRUN':
        validate_vcs_switches_for_xcelium(options, parser)
        validate_xcelium_runtime_options(options, parser)


def create_parser():
    parser = argparse.ArgumentParser(
        prog="simmer",
        description=(
            "Discover, compile, run, retain, and report Verilog/SystemVerilog regressions with VCS or XRUN.\n"
            "Preparation: run from a configured project checkout with Bazel 7.7.1, Python 3.12, and the selected "
            "EDA environment sourced. Quote all test globs."),
        epilog=(
            "Start safely with: simmer -t 'bench:test@1' --simulator VCS --discovery-only\n"
            "Then run without --discovery-only. Use --simmer-profile and the per-job logs to diagnose performance."),
        formatter_class=argparse.RawTextHelpFormatter,
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
    if options.history is not None and options.history < 1:
        parser.error("--history must be a positive integer.")
    options.simulator_was_explicit = simulator_explicitly_requested(argv)
    options.xprop_was_explicit = argument_explicitly_requested(argv, '--xprop')
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
            '--emulator',
        ] if argument_explicitly_requested(argv, argument)
    ]
    options.vcs_partcomp_explicit_switches = [
        argument for argument in [
            '--vcs-partcomp-mode',
            '--vcs-partcomp-jobs',
            '--vcs-partcomp-dir',
            '--vcs-partcomp-sharedlib',
        ] if argument_explicitly_requested(argv, argument)
    ]

    options.reproduce_args = reproduction_args(argv)

    options.simulator = (options.simulator if options.simulator_was_explicit else SIM_PLATFORM).upper()
    if options.wave_start < 0:
        parser.error("--wave-start must be non-negative.")
    if options.wave_end != 99999999 and options.wave_end <= options.wave_start:
        parser.error("--wave-end must be greater than --wave-start.")
    validate_simulator_specific_options(options, parser)

    if options.simulator == 'XRUN':
        apply_xcelium_postprocess(options)

    options.proj_dir = PROJ_DIR
    return options
