from lib import parser_actions


def add_vcs_arguments(parser):
    gvcs = parser.add_argument_group(
        "VCS arguments",
        "VCS-only controls. Source the VCS/Verdi environment first. Option semantics follow the Y-2026.03 User Guide; "
        "licensed execution still requires Red Hat site validation. Explicit VCS options are rejected for XRUN.")
    gvcs.add_argument(
        '--gui',
        default=False,
        action='store_true',
        help=('Compile one selected test with Verdi debug access and launch simv in the Verdi GUI.\n'
              'Preparation: select exactly one VCS test and ensure a Verdi license/display is available.'))
    gvcs.add_argument('--cm',
                      action=parser_actions.CMAction,
                      help=(f'Enable VCS compile/runtime coverage and generate the URG/Verdi merge flow.\n'
                            f'Use A for all supported metrics or join individual metrics with +.\n'
                            f'{parser_actions.CMAction.format_options(indent=0)}'))
    gvcs.add_argument('--vcs-cm-line',
                      type=str,
                      default=None,
                      choices=['contassign', 'svtb', 'svtb+svtb_include_lib'],
                      help=('Pass -cm_line MODE to VCS. Requires --cm line or --cm A; use svtb modes only when '
                            'testbench line coverage is intentionally included.'))
    gvcs.add_argument('--vcs-cm-report',
                      action='append',
                      default=None,
                      choices=['svpackages', 'noinitial'],
                      help=('Pass one -cm_report mode to VCS; repeat for both. svpackages includes SystemVerilog '
                            'packages and requires line coverage. noinitial excludes initial blocks from line, '
                            'condition, and branch coverage.'))
    gvcs.add_argument('--vcs-cm-cond',
                      type=str,
                      default=None,
                      help=('Pass a plus-separated -cm_cond mode list, for example obs+event as recommended for '
                            'observable conditions and sensitivity lists. Requires --cm cond or --cm A.'))
    gvcs.add_argument('--vcs-cm-tgl',
                      type=str,
                      default=None,
                      help=('Pass a plus-separated -cm_tgl mode list, for example portsonly or mda. Requires '
                            '--cm tgl or --cm A; portsonly reduces toggle coverage cost to design ports.'))
    gvcs.add_argument('--vcs-cm-hier',
                      type=str,
                      default=None,
                      help=('Pass an existing -cm_hier configuration file to VCS. Requires --cm; the path is '
                            'validated before Bazel starts and overrides the testbench vcs_cm_hier setting.'))
    gvcs.add_argument('--vcs-profile',
                      default=False,
                      action='store_true',
                      help=('Add -pcmakeprof -reportstats and write phase/partition timing statistics to cmp.log. '
                            'Use this when comparing scratch, incremental, or Partition Compile performance.'))
    gvcs.add_argument('--vcs-urg-parallel',
                      default=False,
                      action='store_true',
                      help=('Add -parallel to the generated URG coverage merge. Enable only after measuring local '
                            'CPU and memory use or configuring the site grid options outside simmer.'))
    gvcs.add_argument('--vcs-urg-show-tests',
                      default=False,
                      action='store_true',
                      help=('Add -show tests to the generated URG merge so the merged VDB retains test-to-cover '
                            'correlation for grading and debug. This increases merged database size.'))
    gvcs.add_argument(
        '--vcs-partcomp-mode',
        default='adaptive',
        choices=['adaptive', 'auto', 'low', 'high', 'relax', 'disabled'],
        help=('Select VCS Partition Compile behavior (default: adaptive).\n'
              'adaptive: schedule partitions using current load; auto: standard autopartitioning;\n'
              'low: more/smaller partitions; high: fewer/larger partitions;\n'
              'relax: relax a poorly balanced high-threshold result; disabled: use regular -Mupdate only.'))
    gvcs.add_argument('--vcs-partcomp-jobs',
                      default=8,
                      type=int,
                      help=('Maximum parallel partition compile processes passed as -fastpartcomp=jN (default: 8). '
                            'Choose no more than the CPU/license capacity available to each concurrent VCOMP job.'))
    gvcs.add_argument('--vcs-partcomp-dir',
                      default=None,
                      help=('Override the writable -partcomp_dir. The default is '
                            '<regression>/<tb>__VCS_VCOMP/partitionlib and is removed by --recompile. '
                            'Use a versioned external path only when intentionally publishing a baseline.'))
    gvcs.add_argument('--vcs-partcomp-sharedlib',
                      default=None,
                      help=('Reuse an existing partition database through -partcomp_sharedlib. The directory must '
                            'already exist, must differ from --vcs-partcomp-dir, and must match the VCS version, '
                            'Red Hat platform, sources, defines, coverage/debug mode, and compile arguments.'))
    gvcs.add_argument('--smartlog',
                      dest='smartlog',
                      default=False,
                      action='store_true',
                      help=('Enable VCS SmartLog (-sml) for compile and simulation. Use for Verdi log correlation; '
                            'leave disabled in throughput regressions unless the debug metadata is needed.'))
    gvcs.add_argument('--vcs-runner',
                      type=str,
                      default=None,
                      help=('Override the command prefix used for VCS, simv, URG, and Verdi. Resolution order is '
                            'this option, RV_VCS_RUNNER, then "runmod vcs --". The value is shell-tokenized.'))
    gvcs.add_argument('--dtl',
                      default=False,
                      action='store_true',
                      help=('Enable the batch-only VCS Dynamic Test Loading static/base compile flow. It requires '
                            'Partition Compile, owns <VCOMP>/dtl_static, and cannot be combined with --gui or custom '
                            'Partition Compile mode/directories.'))
    gvcs.add_argument('--fgp',
                      type=int,
                      default=None,
                      help=('Enable VCS Fine-Grained Parallelism at compile time and pass -fgp=num_threads:N '
                            'at runtime. N must be positive; simmer reduces concurrent test jobs to account for it.'))
    gvcs.add_argument('--vcs-xprop-flowctrl',
                      default=False,
                      action='store_true',
                      help='Add VCS -xprop=flowctrl. Requires --xprop F or --xprop C; use only after xprop profiling.')
    gvcs.add_argument('--vcs-xprop-mmsopt',
                      default=False,
                      action='store_true',
                      help='Add VCS -xprop=mmsopt. Requires --xprop F or --xprop C; use only after xprop profiling.')
    gvcs.add_argument('--vcs-xprop-banner',
                      default=False,
                      action='store_true',
                      help='Add runtime -xprop=banner. Requires --xprop F or --xprop C.')
    gvcs.add_argument('--vcs-xprop-report',
                      default=False,
                      action='store_true',
                      help='Add runtime -report=xprop. Requires --xprop F or --xprop C.')
    gvcs.add_argument('--ico',
                      default=False,
                      action='store_true',
                      help=('Enable VCS ICO shared-regression mode: initialize a shared CDB with crg and pass the '
                            'recommended ICO auto-configuration runtime options to each simv.'))
    gvcs.add_argument('--ico-workdir',
                      type=str,
                      default=None,
                      help=('Override the VCS ICO local work directory. Requires --ico; default is '
                            '<regression>/ico_artifacts/workdir.'))
    gvcs.add_argument('--ico-shared-record',
                      type=str,
                      default=None,
                      help=('Override the VCS ICO shared CDB directory. Requires --ico; default is '
                            '<regression>/ico_artifacts/shared_record. An initialized CDB is reused.'))
    gvcs.add_argument('--vso',
                      default=False,
                      action='store_true',
                      help=('Enable the VSO.ai CSO three-step flow: compile each build with -vso cso, run driver '
                            'init/ask-all, execute selected tests with run IDs, then finalize/merge with bulk status.'))
    gvcs.add_argument('--vso-workdir',
                      type=str,
                      default=None,
                      help=('Override the VSO.ai per-regression workdir. Requires --vso; default is '
                            '<regression>/vso_artifacts/workdir. All VSO steps and simv jobs must access it.'))
    gvcs.add_argument('--vso-dbdir',
                      type=str,
                      default=None,
                      help=('Select the persistent VSO.ai learning dbdir. Requires --vso; default is an empty '
                            '<regression>/vso_artifacts/dbdir suitable for a Day0 run.'))
    gvcs.add_argument('--vso-buildname',
                      type=str,
                      default=None,
                      help=('Override the VSO.ai build name for a single selected VCS build. Requires --vso; '
                            'otherwise each VCOMP job name is used as its unique build name.'))
    gvcs.add_argument('--vso-target-metric',
                      type=str,
                      default=None,
                      help=('Set the comma-separated VSO.ai target metrics: all, assert, cond, fsm, group, line, '
                            'or tgl. Requires --vso; otherwise metrics are derived from --cm.'))
    gvcs.add_argument('--vso-phase',
                      action='append',
                      default=None,
                      help=('Pass one VSO.ai init phase selection, such as stress, stress:3, acceleration, or '
                            'exploration. Repeat the option for multiple phases. Requires --vso.'))
    gvcs.add_argument('--vso-cbv',
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
    gvcs.add_argument('--vso-ccex-rca',
                      default=False,
                      action='store_true',
                      help=('Enable Coverage Directed Solver static root-cause analysis with -ccex_opts rca. '
                            'Requires --vso-ccex; inspect results with an URG or Verdi CCEX report.'))
    gvcs.add_argument('--vso-ccex-auto-merge-dir',
                      type=str,
                      default=None,
                      help=('Enable inter-simulation Coverage Directed Solver learning through the given shared '
                            'directory. Requires --vso-ccex and storage visible to every simv job.'))
