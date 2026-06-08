import os

from lib import parser_actions


def add_vcs_arguments(parser):
    gvcs = parser.add_argument_group("VCS arguments")
    gvcs.add_argument('--cm',
                      action=parser_actions.CMAction,
                      help=f'Enable Code Coverage for vcs only.\n{parser_actions.CMAction.format_options(indent=0)}')
    gvcs.add_argument('--vcs-cm-line',
                      type=str,
                      default=None,
                      choices=['contassign', 'svtb', 'svtb+svtb_include_lib'],
                      help='Add a VCS compile-time -cm_line coverage detail option.')
    gvcs.add_argument('--vcs-cm-report',
                      type=str,
                      default=None,
                      choices=['svpackages'],
                      help='Add a VCS compile-time -cm_report coverage detail option.')
    gvcs.add_argument('--vcs-cm-hier',
                      type=str,
                      default=None,
                      help='Add a VCS compile-time -cm_hier <file> coverage filter.')
    gvcs.add_argument('--vcs-profile',
                      default=False,
                      action='store_true',
                      help='Enable VCS compile profiling with -pcmakeprof -reportstats.')
    gvcs.add_argument('--dtl',
                      default=False,
                      action='store_true',
                      help='Enable VCS Dynamic Test Loading base/static compile flow.')
    gvcs.add_argument('--fgp',
                      type=int,
                      default=None,
                      help='Enable VCS Fine-Grained Parallelism and set runtime num_threads.')
    gvcs.add_argument('--vcs-xprop-flowctrl',
                      default=False,
                      action='store_true',
                      help='Add VCS compile-time -xprop=flowctrl.')
    gvcs.add_argument('--vcs-xprop-mmsopt',
                      default=False,
                      action='store_true',
                      help='Add VCS compile-time -xprop=mmsopt.')
    gvcs.add_argument('--vcs-xprop-banner',
                      default=False,
                      action='store_true',
                      help='Add VCS runtime -xprop=banner.')
    gvcs.add_argument('--vcs-xprop-report',
                      default=False,
                      action='store_true',
                      help='Add VCS runtime -report=xprop.')


def validate_vcs_switches_for_xcelium(options, parser):
    vcs_only_switches = []
    if options.cm:
        vcs_only_switches.append('--cm')
    if options.vcs_cm_line is not None:
        vcs_only_switches.append('--vcs-cm-line')
    if options.vcs_cm_report is not None:
        vcs_only_switches.append('--vcs-cm-report')
    if options.vcs_cm_hier is not None:
        vcs_only_switches.append('--vcs-cm-hier')
    if options.vcs_profile:
        vcs_only_switches.append('--vcs-profile')
    if options.dtl:
        vcs_only_switches.append('--dtl')
    if options.fgp is not None:
        vcs_only_switches.append('--fgp')
    if options.vcs_xprop_flowctrl:
        vcs_only_switches.append('--vcs-xprop-flowctrl')
    if options.vcs_xprop_mmsopt:
        vcs_only_switches.append('--vcs-xprop-mmsopt')
    if options.vcs_xprop_banner:
        vcs_only_switches.append('--vcs-xprop-banner')
    if options.vcs_xprop_report:
        vcs_only_switches.append('--vcs-xprop-report')
    if vcs_only_switches:
        parser.error(
            "The following switches are VCS-only and cannot be used with Xcelium: {}. "
            "Stopping before Bazel starts.".format(", ".join(vcs_only_switches)))


def validate_vcs_runtime_options(options, parser):
    if any([
        options.vcs_cm_line is not None,
        options.vcs_cm_report is not None,
        options.vcs_cm_hier is not None,
    ]) and not options.cm:
        parser.error(
            "VCS coverage detail switches require '--cm'. "
            "Stopping before Bazel starts.")
    if options.vcs_cm_line is not None and 'line' not in options.cm and 'A' not in options.cm:
        parser.error(
            "--vcs-cm-line requires line coverage in '--cm' (for example '--cm line' or '--cm A'). "
            "Stopping before Bazel starts.")
    if options.vcs_cm_report is not None and 'line' not in options.cm and 'A' not in options.cm:
        parser.error(
            "--vcs-cm-report=svpackages requires line coverage in '--cm' "
            "(for example '--cm line' or '--cm A'). Stopping before Bazel starts.")
    if options.vcs_cm_hier is not None and not os.path.exists(options.vcs_cm_hier):
        parser.error(
            "The specified VCS coverage hierarchy file does not exist: {}. "
            "Stopping before Bazel starts.".format(options.vcs_cm_hier))
    if not options.xprop and any([
        options.vcs_xprop_flowctrl,
        options.vcs_xprop_mmsopt,
        options.vcs_xprop_banner,
        options.vcs_xprop_report,
    ]):
        parser.error(
            "VCS xprop helper switches require XPROP to be enabled. "
            "Do not combine them with '--xprop D'. Stopping before Bazel starts.")
    if options.fgp is not None and options.fgp < 1:
        parser.error("--fgp must be a positive integer thread count. Stopping before Bazel starts.")
    if options.dtl and options.gui:
        parser.error(
            "--dtl currently supports batch/UCLI flow only; --gui is not yet supported. "
            "Stopping before Bazel starts.")
    if options.waves is not None:
        if options.wave_type is None:
            options.wave_type = 'fsdb'
        if options.wave_type != 'fsdb':
            parser.error("VCS supports only --wave-type fsdb. Stopping before Bazel starts.")
        if options.wave_delta:
            parser.error("--wave-delta is supported only for Xcelium SHM waves. Stopping before Bazel starts.")
