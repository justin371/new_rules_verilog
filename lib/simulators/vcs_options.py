import os


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
