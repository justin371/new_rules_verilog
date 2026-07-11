import os

from lib import parser_actions


def add_vcs_arguments(parser):
    gvcs = parser.add_argument_group("VCS arguments")
    gvcs.add_argument('--gui', default=False, action='store_true', help='Run a single VCS simulation in the Verdi GUI.')
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
    gvcs.add_argument('--vcs-partcomp-mode',
                      default='adaptive',
                      choices=['adaptive', 'auto', 'low', 'high', 'relax', 'disabled'],
                      help='Select the VCS Partition Compile mode. Defaults to adaptive.')
    gvcs.add_argument('--vcs-partcomp-jobs',
                      default=8,
                      type=int,
                      help='Maximum parallel Partition Compile processes. Defaults to 8.')
    gvcs.add_argument('--vcs-partcomp-dir',
                      default=None,
                      help='Override the writable VCS partition database directory.')
    gvcs.add_argument('--vcs-partcomp-sharedlib',
                      default=None,
                      help='Reuse an existing VCS partition database as a read-only shared library.')
    gvcs.add_argument('--smartlog',
                      dest='smartlog',
                      default=False,
                      action='store_true',
                      help='Enable VCS smartlog (-sml) for batch compile and sim commands.')
    gvcs.add_argument('--vcs-runner',
                      type=str,
                      default=None,
                      help='Override the command prefix used to launch VCS, simv, and Verdi. '
                      'Defaults to RV_VCS_RUNNER or "runmod vcs --".')
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
    gvcs.add_argument('--vcs-xprop-banner', default=False, action='store_true', help='Add VCS runtime -xprop=banner.')
    gvcs.add_argument('--vcs-xprop-report', default=False, action='store_true', help='Add VCS runtime -report=xprop.')
    gvcs.add_argument('--vso',
                      default=False,
                      action='store_true',
                      help='Enable VSO.ai metadata options for VCS compile and sim commands.')
    gvcs.add_argument('--vso-workdir',
                      type=str,
                      default=None,
                      help='Override the VSO.ai workdir used for VCS runtime metadata.')
    gvcs.add_argument('--vso-dbdir',
                      type=str,
                      default=None,
                      help='Override the VSO.ai dbdir used for init/finalize/merge learning state.')
    gvcs.add_argument('--vso-buildname',
                      type=str,
                      default=None,
                      help='Override the VSO.ai buildname used for VCS compile metadata.')
    gvcs.add_argument(
        '--vso-target-metric',
        type=str,
        default=None,
        help='Override the VSO.ai target metric list used during init (for example: line,fsm,tgl,assert).')


def validate_vcs_switches_for_xcelium(options, parser):
    vcs_only_switches = []
    if options.cm:
        vcs_only_switches.append('--cm')
    if options.gui:
        vcs_only_switches.append('--gui')
    if options.vcs_cm_line is not None:
        vcs_only_switches.append('--vcs-cm-line')
    if options.vcs_cm_report is not None:
        vcs_only_switches.append('--vcs-cm-report')
    if options.vcs_cm_hier is not None:
        vcs_only_switches.append('--vcs-cm-hier')
    if options.vcs_profile:
        vcs_only_switches.append('--vcs-profile')
    vcs_only_switches.extend(options.vcs_partcomp_explicit_switches)
    if options.smartlog:
        vcs_only_switches.append('--smartlog')
    if options.vcs_runner is not None:
        vcs_only_switches.append('--vcs-runner')
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
    if options.vso:
        vcs_only_switches.append('--vso')
    if options.vso_workdir is not None:
        vcs_only_switches.append('--vso-workdir')
    if options.vso_dbdir is not None:
        vcs_only_switches.append('--vso-dbdir')
    if options.vso_buildname is not None:
        vcs_only_switches.append('--vso-buildname')
    if options.vso_target_metric is not None:
        vcs_only_switches.append('--vso-target-metric')
    if vcs_only_switches:
        parser.error("The following switches are VCS-only and cannot be used with Xcelium: {}. "
                     "Stopping before Bazel starts.".format(", ".join(vcs_only_switches)))


def validate_vcs_runtime_options(options, parser):
    if any([
            options.vcs_cm_line is not None,
            options.vcs_cm_report is not None,
            options.vcs_cm_hier is not None,
    ]) and not options.cm:
        parser.error("VCS coverage detail switches require '--cm'. "
                     "Stopping before Bazel starts.")
    if options.vcs_cm_line is not None and 'line' not in options.cm and 'A' not in options.cm:
        parser.error("--vcs-cm-line requires line coverage in '--cm' (for example '--cm line' or '--cm A'). "
                     "Stopping before Bazel starts.")
    if options.vcs_cm_report is not None and 'line' not in options.cm and 'A' not in options.cm:
        parser.error("--vcs-cm-report=svpackages requires line coverage in '--cm' "
                     "(for example '--cm line' or '--cm A'). Stopping before Bazel starts.")
    if options.vcs_cm_hier is not None and not os.path.exists(options.vcs_cm_hier):
        parser.error("The specified VCS coverage hierarchy file does not exist: {}. "
                     "Stopping before Bazel starts.".format(options.vcs_cm_hier))
    if not options.xprop and any([
            options.vcs_xprop_flowctrl,
            options.vcs_xprop_mmsopt,
            options.vcs_xprop_banner,
            options.vcs_xprop_report,
    ]):
        parser.error("VCS xprop helper switches require XPROP to be enabled. "
                     "Do not combine them with '--xprop D'. Stopping before Bazel starts.")
    if options.fgp is not None and options.fgp < 1:
        parser.error("--fgp must be a positive integer thread count. Stopping before Bazel starts.")
    if options.vcs_runner is not None and not options.vcs_runner.strip():
        parser.error("--vcs-runner must not be empty. Stopping before Bazel starts.")
    if options.vcs_partcomp_jobs < 1:
        parser.error("--vcs-partcomp-jobs must be a positive integer. Stopping before Bazel starts.")
    if options.vcs_partcomp_dir is not None and not options.vcs_partcomp_dir.strip():
        parser.error("--vcs-partcomp-dir must not be empty. Stopping before Bazel starts.")
    if options.vcs_partcomp_sharedlib is not None and not options.vcs_partcomp_sharedlib.strip():
        parser.error("--vcs-partcomp-sharedlib must not be empty. Stopping before Bazel starts.")
    if options.vcs_partcomp_mode == 'disabled' and any([
            options.vcs_partcomp_jobs != 8,
            options.vcs_partcomp_dir is not None,
            options.vcs_partcomp_sharedlib is not None,
    ]):
        parser.error("Partition Compile details require an enabled '--vcs-partcomp-mode'. "
                     "Stopping before Bazel starts.")
    if options.vcs_partcomp_sharedlib is not None:
        sharedlib = os.path.abspath(options.vcs_partcomp_sharedlib)
        if not os.path.isdir(sharedlib):
            parser.error("The VCS Partition Compile shared library does not exist: {}. "
                         "Stopping before Bazel starts.".format(sharedlib))
        if options.vcs_partcomp_dir is not None and sharedlib == os.path.abspath(options.vcs_partcomp_dir):
            parser.error("--vcs-partcomp-dir and --vcs-partcomp-sharedlib must use different directories. "
                         "Stopping before Bazel starts.")
    if options.dtl and options.vcs_partcomp_mode == 'disabled':
        parser.error("--dtl requires VCS Partition Compile. Stopping before Bazel starts.")
    if options.dtl and any([
            options.vcs_partcomp_mode != 'adaptive',
            options.vcs_partcomp_dir is not None,
            options.vcs_partcomp_sharedlib is not None,
    ]):
        parser.error("--dtl owns its partition flow; do not combine it with custom VCS Partition Compile settings. "
                     "Stopping before Bazel starts.")
    if any([
            options.vso_workdir is not None,
            options.vso_dbdir is not None,
            options.vso_buildname is not None,
            options.vso_target_metric is not None,
    ]) and not options.vso:
        parser.error("VSO.ai detail switches require '--vso'. "
                     "Stopping before Bazel starts.")
    if options.vso_workdir is not None and not options.vso_workdir.strip():
        parser.error("--vso-workdir must not be empty. Stopping before Bazel starts.")
    if options.vso_dbdir is not None and not options.vso_dbdir.strip():
        parser.error("--vso-dbdir must not be empty. Stopping before Bazel starts.")
    if options.vso_buildname is not None and not options.vso_buildname.strip():
        parser.error("--vso-buildname must not be empty. Stopping before Bazel starts.")
    if options.vso_target_metric is not None and not options.vso_target_metric.strip():
        parser.error("--vso-target-metric must not be empty. Stopping before Bazel starts.")
    if options.vso and options.vso_target_metric is None and not options.cm:
        parser.error("VSO.ai init requires coverage targeting information. "
                     "Please pass '--cm ...' or '--vso-target-metric ...'. Stopping before Bazel starts.")
    if options.vso and options.vso_target_metric is None and options.cm is not None:
        supported_vso_metrics = {'line', 'fsm', 'tgl', 'assert', 'A'}
        if not any(token in supported_vso_metrics for token in options.cm.split('+')):
            parser.error("Could not derive a VSO.ai target metric from '--cm {}'. "
                         "Please pass '--vso-target-metric ...' explicitly. Stopping before Bazel starts.".format(
                             options.cm))
    if options.dtl and options.gui:
        parser.error("--dtl currently supports batch/UCLI flow only; --gui is not yet supported. "
                     "Stopping before Bazel starts.")
    if options.waves is not None:
        if options.wave_type is None:
            options.wave_type = 'fsdb'
        if options.wave_type != 'fsdb':
            parser.error("VCS supports only --wave-type fsdb. Stopping before Bazel starts.")
