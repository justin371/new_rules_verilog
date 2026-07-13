import os


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
    if sum(mode is not None for mode in msie_modes) > 1:
        parser.error("Use only one of --msie, --msie-href, --msie-prim, or --msie-incr per invocation. "
                     "Stopping before Bazel starts.")
    if options.emulator and (options.mce or any(mode is not None for mode in msie_modes)):
        parser.error("--emulator cannot be combined with MCE or MSIE modes. Stopping before Bazel starts.")
    if options.msie_primary_name and options.msie_prim is None:
        parser.error("--msie-primary-name requires --msie-prim. Stopping before Bazel starts.")
    if options.msie_primary_top and options.msie_incr is None:
        parser.error("--msie-primary-top is used only with --msie-incr. Stopping before Bazel starts.")
    if options.msie_primary_key and options.msie_prim is None and options.msie_incr is None:
        parser.error("--msie-primary-key requires --msie-prim or --msie-incr. Stopping before Bazel starts.")

    if options.msie_href is not None or options.msie_prim is not None or options.emulator == 'clean':
        options.no_run = True
    if not options.xprop_was_explicit:
        options.xprop = 'F'
