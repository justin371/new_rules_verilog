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
                      type=str,
                      default=None,
                      choices=['svpackages'],
                      help=('Pass -cm_report svpackages to VCS so package coverage appears in reports. '
                            'Requires --cm line or --cm A.'))
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
    gvcs.add_argument('--vso',
                      default=False,
                      action='store_true',
                      help=('Enable the VSO.ai init/ask/tell/finalize workflow. Preparation: source VSO_HOME, provide '
                            'the required licenses, and select coverage with --cm or --vso-target-metric.'))
    gvcs.add_argument('--vso-workdir',
                      type=str,
                      default=None,
                      help=('Override the VSO.ai work directory. Requires --vso; default is '
                            '<regression>/vso_artifacts/workdir.'))
    gvcs.add_argument('--vso-dbdir',
                      type=str,
                      default=None,
                      help=('Override the VSO.ai learning database directory. Requires --vso; default is '
                            '<regression>/vso_artifacts/dbdir. Preserve it when reusing learned state.'))
    gvcs.add_argument('--vso-buildname',
                      type=str,
                      default=None,
                      help='Override the VSO.ai build name. Requires --vso; default is the VCOMP job name.')
    gvcs.add_argument(
        '--vso-target-metric',
        type=str,
        default=None,
        help=('Set the comma-separated VSO.ai optimization metrics used during init, for example '
              'line,fsm,tgl,assert. Requires --vso; otherwise simmer derives supported metrics from --cm.'))
