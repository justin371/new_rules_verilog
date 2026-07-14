import os


def validate_vcs_runtime_options(options, parser):
    if any([
            options.vcs_cm_line is not None,
            options.vcs_cm_report is not None,
            options.vcs_cm_cond is not None,
            options.vcs_cm_tgl is not None,
            options.vcs_cm_hier is not None,
            options.vcs_urg_parallel,
            options.vcs_urg_show_tests,
    ]) and not options.cm:
        parser.error("VCS coverage detail switches require '--cm'. "
                     "Stopping before Bazel starts.")
    if options.vcs_cm_line is not None and 'line' not in options.cm and 'A' not in options.cm:
        parser.error("--vcs-cm-line requires line coverage in '--cm' (for example '--cm line' or '--cm A'). "
                     "Stopping before Bazel starts.")
    if options.vcs_cm_report is not None:
        if 'svpackages' in options.vcs_cm_report and 'line' not in options.cm and 'A' not in options.cm:
            parser.error("--vcs-cm-report=svpackages requires line coverage. Stopping before Bazel starts.")
        if ('noinitial' in options.vcs_cm_report and 'A' not in options.cm
                and not any(metric in options.cm for metric in ('line', 'cond', 'branch'))):
            parser.error("--vcs-cm-report=noinitial requires line, cond, or branch coverage. "
                         "Stopping before Bazel starts.")
    if options.vcs_cm_cond is not None:
        supported = {'basic', 'std', 'full', 'allops', 'event', 'for', 'tf', 'obs'}
        modes = set(options.vcs_cm_cond.split('+'))
        if not modes or not modes.issubset(supported):
            parser.error("--vcs-cm-cond contains an unsupported mode. Stopping before Bazel starts.")
        if 'cond' not in options.cm and 'A' not in options.cm:
            parser.error("--vcs-cm-cond requires condition coverage. Stopping before Bazel starts.")
    if options.vcs_cm_tgl is not None:
        supported = {'fullintf', 'mda', 'modportarr', 'signalsort', 'portsonly', 'unencrypted_signals'}
        modes = set(options.vcs_cm_tgl.split('+'))
        if not modes or not modes.issubset(supported):
            parser.error("--vcs-cm-tgl contains an unsupported mode. Stopping before Bazel starts.")
        if 'modportarr' in modes and 'fullintf' not in modes:
            parser.error("--vcs-cm-tgl modportarr must be combined with fullintf. Stopping before Bazel starts.")
        if 'tgl' not in options.cm and 'A' not in options.cm:
            parser.error("--vcs-cm-tgl requires toggle coverage. Stopping before Bazel starts.")
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
    if options.vcs_partcomp_jobs != 'auto' and options.vcs_partcomp_jobs < 1:
        parser.error("--vcs-partcomp-jobs must be a positive integer. Stopping before Bazel starts.")
    if options.vcs_partcomp_dir is not None and not options.vcs_partcomp_dir.strip():
        parser.error("--vcs-partcomp-dir must not be empty. Stopping before Bazel starts.")
    if options.vcs_partcomp_sharedlib is not None and not options.vcs_partcomp_sharedlib.strip():
        parser.error("--vcs-partcomp-sharedlib must not be empty. Stopping before Bazel starts.")
    if options.vcs_partcomp_mode == 'disabled' and any([
            options.vcs_partcomp_jobs != 'auto',
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
    if options.vcs_auto_compile_cache and options.no_compile:
        parser.error("--vcs-auto-compile-cache cannot be combined with --no-compile. "
                     "Stopping before Bazel starts.")
    if options.vcs_auto_compile_cache and options.recompile:
        parser.error("--vcs-auto-compile-cache cannot be combined with --recompile. "
                     "Stopping before Bazel starts.")
    if options.dtl and options.vcs_partcomp_mode == 'disabled':
        parser.error("--dtl requires VCS Partition Compile. Stopping before Bazel starts.")
    if options.dtl and any([
            options.vcs_partcomp_mode != 'auto',
            options.vcs_partcomp_dir is not None,
            options.vcs_partcomp_sharedlib is not None,
    ]):
        parser.error("--dtl owns its partition flow; do not combine it with custom VCS Partition Compile settings. "
                     "Stopping before Bazel starts.")
    if any([
            options.ico_workdir is not None,
            options.ico_shared_record is not None,
    ]) and not options.ico:
        parser.error("VCS ICO detail switches require '--ico'. "
                     "Stopping before Bazel starts.")
    if options.ico_workdir is not None and not options.ico_workdir.strip():
        parser.error("--ico-workdir must not be empty. Stopping before Bazel starts.")
    if options.ico_shared_record is not None and not options.ico_shared_record.strip():
        parser.error("--ico-shared-record must not be empty. Stopping before Bazel starts.")
    if sum(bool(value) for value in (options.ico, options.vso, options.vso_ccex)) > 1:
        parser.error("--ico, --vso, and --vso-ccex are separate flows and cannot be combined. "
                     "Stopping before Bazel starts.")
    if any([
            options.vso_workdir is not None,
            options.vso_dbdir is not None,
            options.vso_buildname is not None,
            options.vso_target_metric is not None,
            options.vso_phase is not None,
            options.vso_cbv,
    ]) and not options.vso:
        parser.error("VSO.ai CSO detail switches require '--vso'. Stopping before Bazel starts.")
    for name, value in (
        ("--vso-workdir", options.vso_workdir),
        ("--vso-dbdir", options.vso_dbdir),
        ("--vso-buildname", options.vso_buildname),
        ("--vso-target-metric", options.vso_target_metric),
    ):
        if value is not None and not value.strip():
            parser.error("{} must not be empty. Stopping before Bazel starts.".format(name))
    if options.vso_phase is not None and any(not phase.strip() for phase in options.vso_phase):
        parser.error("--vso-phase must not be empty. Stopping before Bazel starts.")
    if options.vso_target_metric is not None:
        metrics = set(options.vso_target_metric.split(','))
        supported = {'all', 'assert', 'cond', 'fsm', 'group', 'line', 'tgl'}
        if not metrics or not metrics.issubset(supported):
            parser.error("--vso-target-metric accepts comma-separated all, assert, cond, fsm, group, line, or tgl. "
                         "Stopping before Bazel starts.")
    if options.vso and options.vso_target_metric is None and not options.cm:
        parser.error("VSO.ai init requires --cm or --vso-target-metric. Stopping before Bazel starts.")
    if options.vso and options.vso_target_metric is None and options.cm == 'branch':
        parser.error("VSO.ai cannot derive a supported target metric from --cm branch; pass --vso-target-metric. "
                     "Stopping before Bazel starts.")
    if options.vso_cbv:
        line_enabled = options.cm and ('line' in options.cm or 'A' in options.cm)
        port_toggle_enabled = (options.cm and ('tgl' in options.cm or 'A' in options.cm)
                               and options.vcs_cm_tgl == 'portsonly')
        if not line_enabled and not port_toggle_enabled:
            parser.error("--vso-cbv requires --cm line or --cm tgl --vcs-cm-tgl portsonly for the Day0 model. "
                         "Stopping before Bazel starts.")
    if any([options.vso_ccex_rca, options.vso_ccex_auto_merge_dir is not None]) and not options.vso_ccex:
        parser.error("VSO.ai CCEX detail switches require '--vso-ccex'. Stopping before Bazel starts.")
    if options.vso_ccex_auto_merge_dir is not None and not options.vso_ccex_auto_merge_dir.strip():
        parser.error("--vso-ccex-auto-merge-dir must not be empty. Stopping before Bazel starts.")
    if options.dtl and options.gui:
        parser.error("--dtl currently supports batch/UCLI flow only; --gui is not yet supported. "
                     "Stopping before Bazel starts.")
    if options.waves is not None:
        if options.wave_type is None:
            options.wave_type = 'fsdb'
        if options.wave_type != 'fsdb':
            parser.error("VCS supports only --wave-type fsdb. Stopping before Bazel starts.")
