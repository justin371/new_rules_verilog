import argparse

from lib import parser_actions

from .common import add_child_argument


def _partcomp_jobs(value):
    if str(value).lower() == 'auto':
        return 'auto'
    try:
        jobs = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected 'auto' or a positive integer") from exc
    return jobs


def add_vcs_arguments(parser):
    gvcs = parser.add_argument_group(
        "VCS arguments",
        "VCS-only controls. Source the VCS/Verdi environment first. Option semantics follow the installed VCS release; "
        "licensed execution still requires Red Hat site validation. Explicit VCS options are rejected for XRUN.")
    gvcs.add_argument(
        '--gui',
        default=False,
        action='store_true',
        help=('Compile one selected test with full Verdi debug access, SmartLog, and UVM transaction recording, '
              'then launch simv in the Verdi GUI.\n'
              'Preparation: select exactly one VCS test and ensure a Verdi license/display is available.'))
    gvcs.add_argument('--vcs-cm',
                      dest='cm',
                      action=parser_actions.CMAction,
                      help=(f'Enable VCS compile/runtime coverage and generate the URG/Verdi merge flow.\n'
                            f'Use A for all supported metrics or join individual metrics with +.\n'
                            f'{parser_actions.CMAction.format_options(indent=0)}'))
    add_child_argument(gvcs,
                       '--vcs-cm-line',
                       parent='--vcs-cm',
                       type=str,
                       default=None,
                       choices=['contassign', 'svtb', 'svtb+svtb_include_lib'],
                       help=('Pass -cm_line MODE to VCS. Requires --vcs-cm line or --vcs-cm A; use svtb modes only '
                             'when testbench line coverage is intentionally included.'))
    add_child_argument(gvcs,
                       '--vcs-cm-report',
                       parent='--vcs-cm',
                       action='append',
                       default=None,
                       choices=['svpackages', 'noinitial'],
                       help=('Pass one -cm_report mode to VCS; repeat for both. svpackages includes SystemVerilog '
                             'packages and requires line coverage. noinitial excludes initial blocks from line, '
                             'condition, and branch coverage.'))
    add_child_argument(gvcs,
                       '--vcs-cm-cond',
                       parent='--vcs-cm',
                       type=str,
                       default=None,
                       help=('Pass a plus-separated -cm_cond mode list, for example obs+event as recommended for '
                             'observable conditions and sensitivity lists. Requires --vcs-cm cond or --vcs-cm A.'))
    add_child_argument(gvcs,
                       '--vcs-cm-tgl',
                       parent='--vcs-cm',
                       type=str,
                       default=None,
                       help=('Pass a plus-separated -cm_tgl mode list, for example portsonly or mda. Requires '
                             '--vcs-cm tgl or --vcs-cm A; portsonly reduces toggle coverage cost to design ports.'))
    add_child_argument(gvcs,
                       '--vcs-cm-hier',
                       parent='--vcs-cm',
                       type=str,
                       default=None,
                       help=('Pass an existing -cm_hier configuration file to VCS. Requires --vcs-cm; the path is '
                             'validated before Bazel starts and overrides the testbench vcs_cm_hier setting.'))
    add_child_argument(gvcs,
                       '--vcs-urg-parallel',
                       parent='--vcs-cm',
                       default=False,
                       action='store_true',
                       help=('Add -parallel to the generated URG coverage merge. Enable only after measuring local '
                             'CPU and memory use or configuring the site grid options outside simmer.'))
    add_child_argument(gvcs,
                       '--vcs-urg-show-tests',
                       parent='--vcs-cm',
                       default=False,
                       action='store_true',
                       help=('Add -show tests to the generated URG merge so the merged VDB retains test-to-cover '
                             'correlation for grading and debug. This increases merged database size.'))
    add_child_argument(gvcs,
                       '--cm',
                       parent='--vcs-cm',
                       dest='cm',
                       default=argparse.SUPPRESS,
                       action=parser_actions.CMAction,
                       help='Compatibility alias for --vcs-cm.')
    gvcs.add_argument('--vcs-profile',
                      default=False,
                      action='store_true',
                      help=('Add -pcmakeprof -reportstats and write phase/partition timing statistics to cmp.log. '
                            'Use this when comparing scratch, incremental, or Partition Compile performance.'))
    partcomp_control = gvcs.add_mutually_exclusive_group()
    partcomp_control.add_argument(
        '--vcs-partcomp',
        dest='vcs_partcomp',
        action='store_true',
        help=('Keep VCS Partition Compile enabled (default). The --vcs-partcomp-* options tune the enabled flow; '
              'use --no-vcs-partcomp for unsupported VCS releases or diagnostics.'))
    partcomp_control.add_argument('--no-vcs-partcomp',
                                  dest='vcs_partcomp',
                                  action='store_false',
                                  help=('Disable VCS Partition Compile and use regular -Mupdate only. Use this for '
                                        'unsupported VCS releases or direct incremental-compile comparisons.'))
    gvcs.set_defaults(vcs_partcomp=True)
    add_child_argument(gvcs,
                       '--vcs-partcomp-mode',
                       parent='--vcs-partcomp',
                       default='auto',
                       choices=['adaptive', 'auto', 'low', 'high', 'relax'],
                       help=('Select VCS Partition Compile behavior while it is enabled (default: auto).\n'
                             'adaptive: schedule partitions using current load; auto: standard autopartitioning;\n'
                             'low: more/smaller partitions; high: fewer/larger partitions;\n'
                             'relax: relax a poorly balanced high-threshold result.'))
    add_child_argument(gvcs,
                       '--vcs-partcomp-jobs',
                       parent='--vcs-partcomp',
                       default='auto',
                       type=_partcomp_jobs,
                       help=('Maximum parallel partition compile processes passed as -fastpartcomp=jN (default: auto). '
                             'auto uses CPUs allocated to this job by LSF/Slurm or process affinity; it never scans '
                             'cluster idle CPUs. Cannot be combined with --no-vcs-partcomp.'))
    add_child_argument(gvcs,
                       '--vcs-partcomp-dir',
                       parent='--vcs-partcomp',
                       default=None,
                       help=('Override the writable -partcomp_dir. The default is '
                             '<regression>/<tb>__VCS_VCOMP/partitionlib and is removed by --recompile. '
                             'Use a versioned external path only when intentionally publishing a baseline. '
                             'Cannot be combined with --no-vcs-partcomp.'))
    add_child_argument(gvcs,
                       '--vcs-partcomp-sharedlib',
                       parent='--vcs-partcomp',
                       default=None,
                       help=('Reuse an existing partition database through -partcomp_sharedlib. The directory must '
                             'already exist, must differ from --vcs-partcomp-dir, and must match the VCS version, '
                             'Red Hat platform, source inventory, defines, coverage/debug mode, and compile arguments. '
                             'Cannot be combined with --no-vcs-partcomp.'))
    compile_cache_control = gvcs.add_mutually_exclusive_group()
    compile_cache_control.add_argument(
        '--vcs-auto-compile-cache',
        dest='vcs_auto_compile_cache',
        action='store_true',
        help=('Keep automatic VCS compile reuse enabled (default). A matching fingerprint and simv bypass VCS; a '
              'miss compiles normally. --recompile and --no-compile take precedence for their invocation.'))
    compile_cache_control.add_argument(
        '--no-vcs-auto-compile-cache',
        dest='vcs_auto_compile_cache',
        action='store_false',
        help=('Disable automatic compile bypass and always invoke VCS, allowing -Mupdate or Partition Compile to '
              'decide what to rebuild. Use this for incremental compiler diagnostics.'))
    gvcs.set_defaults(vcs_auto_compile_cache=True)
    gvcs.add_argument('--smartlog',
                      dest='smartlog',
                      default=False,
                      action='store_true',
                      help=('Enable VCS SmartLog (-sml) for compile and simulation. Use for Verdi log correlation; '
                            'wave capture does not enable it automatically. Leave disabled in throughput regressions '
                            'unless the debug metadata is needed.'))
    gvcs.add_argument('--vcs-runner',
                      type=str,
                      default=None,
                      help=('Override the command prefix used for VCS, simv, URG, and Verdi. Resolution order is '
                            'this option, RV_VCS_RUNNER, then "runmod vcs --". The value is shell-tokenized.'))
    gvcs.add_argument('--dtl',
                      default=False,
                      action='store_true',
                      help=('Enable the batch-only VCS Dynamic Test Loading static/base compile flow. It uses the '
                            'default Partition Compile flow, owns <VCOMP>/dtl_static, and cannot be combined with '
                            '--no-vcs-partcomp, --gui, or custom Partition Compile mode/directories.'))
    gvcs.add_argument('--fgp',
                      type=int,
                      default=None,
                      help=('Enable VCS Fine-Grained Parallelism at compile time and pass -fgp=num_threads:N '
                            'at runtime. N must be positive; simmer reduces concurrent test jobs to account for it.'))
    gvcs.add_argument('--vcs-xprop',
                      dest='xprop',
                      default=argparse.SUPPRESS,
                      action=parser_actions.XpropAction,
                      help=('Enable VCS X-propagation. F uses xmerge and C uses tmerge when no bench config exists; '
                            'D disables it. The shared --xprop spelling remains available for compatibility.'))
    add_child_argument(gvcs,
                       '--vcs-xprop-flowctrl',
                       parent='--vcs-xprop',
                       default=False,
                       action='store_true',
                       help=('Add VCS -xprop=flowctrl. Requires --vcs-xprop F or --vcs-xprop C; use only after '
                             'xprop profiling.'))
    add_child_argument(gvcs,
                       '--vcs-xprop-mmsopt',
                       parent='--vcs-xprop',
                       default=False,
                       action='store_true',
                       help=('Add VCS -xprop=mmsopt. Requires --vcs-xprop F or --vcs-xprop C; use only after '
                             'xprop profiling.'))
    add_child_argument(gvcs,
                       '--vcs-xprop-banner',
                       parent='--vcs-xprop',
                       default=False,
                       action='store_true',
                       help='Add runtime -xprop=banner. Requires --vcs-xprop F or --vcs-xprop C.')
    add_child_argument(gvcs,
                       '--vcs-xprop-report',
                       parent='--vcs-xprop',
                       default=False,
                       action='store_true',
                       help='Add runtime -report=xprop. Requires --vcs-xprop F or --vcs-xprop C.')
    gvcs.add_argument('--ico',
                      default=False,
                      action='store_true',
                      help=('Enable VCS ICO shared-regression mode: initialize a shared CDB with crg and pass the '
                            'recommended ICO auto-configuration runtime options to each simv.'))
    add_child_argument(gvcs,
                       '--ico-workdir',
                       parent='--ico',
                       type=str,
                       default=None,
                       help=('Override the VCS ICO local work directory. Requires --ico; default is '
                             '<regression>/ico_artifacts/workdir.'))
    add_child_argument(gvcs,
                       '--ico-shared-record',
                       parent='--ico',
                       type=str,
                       default=None,
                       help=('Override the VCS ICO shared CDB directory. Requires --ico; default is '
                             '<regression>/ico_artifacts/shared_record. An initialized CDB is reused.'))
    gvcs.add_argument('--vso',
                      default=False,
                      action='store_true',
                      help=('Enable the VSO.ai CSO three-step flow: compile each build with -vso cso, run driver '
                            'init/ask-all, execute selected tests with run IDs, then finalize/merge with bulk status.'))
    add_child_argument(gvcs,
                       '--vso-workdir',
                       parent='--vso',
                       type=str,
                       default=None,
                       help=('Override the VSO.ai per-regression workdir. Requires --vso; default is '
                             '<regression>/vso_artifacts/workdir. All VSO steps and simv jobs must access it.'))
    add_child_argument(gvcs,
                       '--vso-dbdir',
                       parent='--vso',
                       type=str,
                       default=None,
                       help=('Select the persistent VSO.ai learning dbdir. Requires --vso; default is an empty '
                             '<regression>/vso_artifacts/dbdir suitable for a Day0 run.'))
    add_child_argument(gvcs,
                       '--vso-buildname',
                       parent='--vso',
                       type=str,
                       default=None,
                       help=('Override the VSO.ai build name for a single selected VCS build. Requires --vso; '
                             'otherwise each VCOMP job name is used as its unique build name.'))
    add_child_argument(gvcs,
                       '--vso-target-metric',
                       parent='--vso',
                       type=str,
                       default=None,
                       help=('Set the comma-separated VSO.ai target metrics: all, assert, cond, fsm, group, line, '
                             'or tgl. Requires --vso; otherwise metrics are derived from --vcs-cm.'))
    add_child_argument(gvcs,
                       '--vso-phase',
                       parent='--vso',
                       action='append',
                       default=None,
                       help=('Pass one VSO.ai init phase selection, such as stress, stress:3, acceleration, or '
                             'exploration. Repeat the option for multiple phases. Requires --vso.'))
    add_child_argument(gvcs,
                       '--vso-cbv',
                       parent='--vso',
                       default=False,
                       action='store_true',
                       help=('Enable VSO.ai Change-Based Verification compile tagging by passing the CSO workdir '
                             'to VCS. Requires --vso and Day0 line coverage or port-only toggle coverage.'))
    gvcs.add_argument('--vso-ccex',
                      default=False,
                      action='store_true',
                      help=('Enable the VSO.ai LCA Coverage Directed Solver by passing -vso ccex at VCS compile '
                            'and simv runtime. Put extra compile options in --file and runtime -ccex_opts values '
                            'in --sim-opts-file.'))
    add_child_argument(gvcs,
                       '--vso-ccex-rca',
                       parent='--vso-ccex',
                       default=False,
                       action='store_true',
                       help=('Enable Coverage Directed Solver static root-cause analysis with -ccex_opts rca. '
                             'Requires --vso-ccex; inspect results with an URG or Verdi CCEX report.'))
    add_child_argument(gvcs,
                       '--vso-ccex-auto-merge-dir',
                       parent='--vso-ccex',
                       type=str,
                       default=None,
                       help=('Enable inter-simulation Coverage Directed Solver learning through the given shared '
                             'directory. Requires --vso-ccex and storage visible to every simv job.'))
