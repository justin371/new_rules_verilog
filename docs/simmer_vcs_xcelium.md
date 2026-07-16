# Simmer VCS and Xcelium Flow

This repo supports one simulator per `simmer` invocation. Pick the backend with
`--simulator`; do not mix XRUN and VCS tests in the same run.

## Normal commands

Xcelium remains the default:

```bash
simmer -t <bench>:<test>
simmer -t <bench>:<test> --simulator XRUN
```

VCS uses the two-step compile/sim flow:

```bash
simmer -t <bench>:<test> --simulator VCS
```

Do not pass `--vcs-runner` for the normal flow. The runner defaults to:

```text
runmod vcs --
```

Override it only when a project needs a different wrapper:

```bash
RV_VCS_RUNNER="runmod vcs --" simmer -t <bench>:<test> --simulator VCS
simmer -t <bench>:<test> --simulator VCS --vcs-runner "runmod vcs --"
```

## Command cookbook

Quote test selectors so the shell does not expand `*`. Start with discovery when
checking a new target or checkout:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --discovery-only
simmer -t 'sys_tb:smoke_test@1' --simulator XRUN --discovery-only
simmer -t 'sys_tb:*@10' --tag nightly --ntag broken --jobs 8
```

Normal runs and deterministic reruns:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS
simmer -t 'sys_tb:smoke_test@1' --simulator XRUN
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --seed 12345
simmer -t 'sys_tb:*@10' --simulator VCS --python-seed 12345
```

Compile reuse and profiling:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --no-compile
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --no-compile --no-bazel
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --recompile
simmer -t 'sys_tb:*@10' --simulator VCS --simmer-profile --vcs-profile
```

Wave and debug runs:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --waves hdl_top.dut --wave-depth 8
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --wave-tcl ./debug/waves.tcl --waves
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --gui
simmer -t 'sys_tb:smoke_test@1' --simulator XRUN --waves hdl_top.dut --wave-type vwdb
```

Coverage and reports:

```bash
simmer -t 'sys_tb:*@10' --simulator VCS --vcs-cm line+cond+fsm \
  --vcs-cm-cond obs+event --vcs-urg-parallel --report
simmer -t 'sys_tb:*@10' --simulator VCS --vcs-cm tgl \
  --vcs-cm-tgl portsonly --vcs-urg-show-tests --report
simmer -t 'sys_tb:*@10' --simulator XRUN --coverage A --report
```

VCS optimization flows are separate and cannot be combined:

```bash
# ICO shared CDB; no VCS compile-time ICO option is added.
simmer -t 'sys_tb:*@20' --simulator VCS --ico \
  --ico-shared-record /nfs/project/ico/shared_record

# VSO.ai simplified CSO init/ask-all/execute/finalize+merge flow.
simmer -t 'sys_tb:*@100' --simulator VCS --vso --vcs-cm A \
  --vso-dbdir /nfs/project/vso/model

# Add Change-Based Verification tagging for a stress-focused run.
simmer -t 'sys_tb:*@100' --simulator VCS --vso --vso-cbv --vcs-cm line \
  --vso-dbdir /nfs/project/vso/model --vso-phase stress:3

# VSO.ai LCA Coverage Directed Solver, independent of CSO and ICO.
simmer -t 'sys_tb:*@20' --simulator VCS --vso-ccex \
  --vso-ccex-auto-merge-dir /nfs/project/ccex/shared --vso-ccex-rca
```

Xcelium scale, MSIE and project-provided Palladium flows:

```bash
simmer -t 'sys_tb:*@20' --simulator XRUN --mce --mce-sim-count 4
simmer -t 'gate_tb:smoke_test@1' --simulator XRUN --msie-href dut
simmer -t 'gate_tb:smoke_test@1' --simulator XRUN --msie-prim dut \
  --msie-primary-name dut_wc --msie-primary-key XCELIUM-25.03:netlist-r42:sdf_wc
simmer -t 'gate_tb:smoke_test@1' --simulator XRUN --msie-incr dut_wc \
  --msie-primary-key XCELIUM-25.03:netlist-r42:sdf_wc
simmer -t 'emu_tb:smoke_test@1' --simulator XRUN --emulator pldm_sa
simmer -t 'emu_tb:smoke_test@1' --simulator XRUN --emulator pldm_sim
```

Result inspection and retention:

```bash
simmer --history
simmer --history 20
simmer -t 'sys_tb:*@10' --simulator VCS --report-dir "$PWD/report-output"
simmer -t 'sys_tb:*@10' --simulator VCS --nt
```

Run `simmer -h` for all options. MSIE stages must use the same target,
`SIMRESULTS`, suffix and primary key. Palladium modes require the project-owned
`EMU_JINJA2_PATH` template and site runtime libraries.

## VCS compile reuse

The default VCS flow automatically reuses unchanged builds:

1. First run builds `<tb>__VCS_VCOMP/simv`.
2. Later runs compare source content, runfiles, compile arguments, tool identity,
   environment and required artifacts against the saved fingerprint.
3. A match bypasses VCS. A miss compiles with Partition Compile by default.

The normal command performs this automatic hit-or-compile decision:

```bash
simmer -t <bench>:<test> --simulator VCS
```

Use `--no-vcs-auto-compile-cache` to always invoke VCS and let Partition Compile
or `-Mupdate` decide what to rebuild. Use `--no-compile` only when an invalid
reuse must fail instead of compiling automatically:

```bash
simmer -t <bench>:<test> --simulator VCS --no-vcs-auto-compile-cache
simmer -t <bench>:<test> --simulator VCS --no-compile
simmer -t <bench>:<test> --simulator VCS --no-compile --no-bazel
```

`--no-compile` validates a fingerprint of tracked/untracked source state,
runfile content, the rendered compile script, compile arguments, external
compile configuration files and the selected tool environment. It fails before
simulation when the existing compile output does not match the current inputs.

Use `--recompile` to force a clean VCS compile. It takes precedence over the
default automatic cache for that invocation.

### `makelib` and VCS reuse

`verilog_rtl_library.makelib` and `verilog_dv_library.makelib` create a named
Xcelium library with `-makelib`/`-endlib`. VCS must not receive those Xcelium
tokens. It receives a companion filelist with the same ordered sources, and
each Bazel library remains a separate `-file` input rather than being flattened
into the testbench filelist.

VCS recompilation isolation comes from `-Mupdate` and Partition Compile, not
from the Xcelium library name. Keep stable RTL/IP in separate Bazel libraries
so their filelist boundaries remain visible to the VCS compile. When automatic
partitioning does not isolate a component well enough, declare its actual cells
or packages in a VCS optconfig file as described below. A `makelib` string is
not sufficient to generate that config because one library may contain several
cells and packages.

### VCS Partition Compile

VCS X-2025.06-SP2-4 uses Partition Compile by default. Simmer applies standard
autopartitioning, allocation-aware compile parallelism and redundant-partition
cleanup, passing the detected job allocation as `N`:

```text
-partcomp
-partcomp_dir=<tb>__VCS_VCOMP/partitionlib
-partcomp=incr_clean
-fastpartcomp=jN
```

`N` comes from the CPUs assigned to the running job, not from an idle-host or
cluster-wide CPU scan. Simmer checks the current host allocation in
`LSB_MCPU_HOSTS`/`LSB_HOSTS`, then Slurm per-task allocation and process CPU
affinity. A multi-host LSF total without per-host evidence falls back to one
worker. Affinity-only and host-count fallbacks are capped at the conservative
default of eight. `--vcs-partcomp-jobs N` always overrides automatic detection.

For an LSF wrapper such as `bs='bsub -I -q syn'`, omitting `-n` normally means
the queue's default allocation, often one slot. Request parallel capacity from
LSF when it is needed:

```bash
bs simmer -t 'sys_tb:smoke_test@1' --simulator VCS
bs -n 8 simmer -t 'sys_tb:smoke_test@1' --simulator VCS
```

The second command selects at most `j8` after LSF grants those slots. It does
not infer permission from the host's current idle CPU count. A diagnostic `j1`
run can set the worker count explicitly:

```bash
bs simmer -t 'sys_tb:smoke_test@1' --simulator VCS \
  --vcs-partcomp-mode auto --vcs-partcomp-jobs 1
```

The partition database belongs to one VCOMP directory rather than the shared
Bazel runfiles tree. A normal internal RTL or testbench edit therefore rebuilds
only affected partitions while unchanged third-party PCIe, UCIe, Ethernet,
RISC-V and NoC IP/VIP partitions remain reusable.

The default non-debug database remains `partitionlib`. `--waves` and `--gui`
use sibling `partitionlib_waves` and `partitionlib_gui` databases because their
KDB/debug-access options are not compatible with a non-debug partition build.
Explicit `--vcs-partcomp-dir` and `--vcs-partcomp-sharedlib` paths are used
exactly as supplied, so custom databases must be versioned separately for each
debug, coverage, define and compile-argument configuration.

Use the default local database for one workspace. Profile and tune parallelism
with:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS \
  --vcs-partcomp-jobs 16 --vcs-profile
```

Automatic fingerprint reuse is enabled by default. To measure VCS incremental
behavior even when the fingerprint matches, disable the bypass explicitly:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --no-vcs-auto-compile-cache
```

A matching fingerprint and existing `simv` bypass VCS compilation. A miss
compiles normally, unlike strict `--no-compile`.

Available modes are `auto`, `adaptive`, `low`, `high` and `relax`. Keep `auto`
until profiling shows a reason to tune the partition thresholds or adaptive
scheduler. Use `--no-vcs-partcomp` for the regular `-Mupdate` flow. This opt-out
is also required for the known Y-2026.03 partition frontend regression:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --no-vcs-partcomp --vcs-profile
```

To create a versioned baseline database for multiple workspaces, use a path
owned by that exact VCS release, Red Hat platform and compile configuration:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS \
  --vcs-partcomp \
  --vcs-partcomp-dir "$PWD/.vcs-partitions/X-2025.06-SP2-4/sys_tb-default"
```

Other workspaces can consume it while writing changed partitions to their local
VCOMP database:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS \
  --vcs-partcomp \
  --vcs-partcomp-sharedlib /shared/vcs-partitions/X-2025.06-SP2-4/sys_tb-default
```

The writable `--vcs-partcomp-dir` and read-only
`--vcs-partcomp-sharedlib` must differ. Do not reuse a baseline across VCS
versions, source inventories, defines, coverage/debug modes or compile arguments.
Explicit baseline builds and shared-library consumers write
`.rules_verilog_partcomp.json` into the writable partition directory. A shared
library with that manifest is rejected before VCS starts when its tool
platform, source inventory or compile configuration is incompatible.
Source-content edits with the same inventory remain valid inputs and VCS
recompiles the affected partitions. Existing databases without a manifest
remain usable with a warning so they can be republished incrementally.

For automatic compile reuse or shared baselines, simmer resolves the actual
VCS build with `vcs -full64 -ID`. Sites may set `RV_VCS_TOOL_ID` to a stable
release ID to avoid that probe while retaining version-safe reuse.
Simmer intentionally does not use `-simcopy_opts=mv`, which would make the
source shared database unusable. `--recompile` removes the default local
database because it is under VCOMP, but it does not delete a custom external
directory.

For effective partitioning, keep third-party components in separate Bazel
libraries, wrap testbench code in SystemVerilog packages, avoid `$unit` code and
minimize cross-partition XMRs. Inspect `cmp.log` for `PC_SHARED`, `PC_RECOMPILE`
and the `-pcmakeprof` timing table. Coverage and Verdi require the referenced
partition database to remain available. With `--vcs-profile`, simmer also
stores marker counts, selected partition mode/jobs, compile wall time and cache
reuse state in the compile entry of `.simmer_results.json`.

Start with automatic partitioning. If profiling shows that stable third-party
code shares a partition with frequently changing project code, add a VCS
optconfig file such as:

```text
partition cell PCIE_CONTROLLER;
partition cell UCIE_CONTROLLER;
partition package PCIE_VIP.pcie_vip_pkg;
partition package ETHERNET_VIP.ethernet_vip_pkg;
```

Use the existing testbench compile-argument interface to keep this VCS-specific
configuration with the VCS testbench definition:

```python
filegroup(
    name = "vcs_partitions",
    srcs = ["vcs_partitions.cfg"],
)

verilog_dv_tb(
    name = "sys_tb",
    simulator = "VCS",
    deps = top_deps,
    extra_compile_args = [
        "+optconfigfile+$(location :vcs_partitions)",
    ],
    extra_runfiles = [":vcs_partitions"],
)
```

Manual partitions are a tuning step, not a default requirement. Keep each large
third-party component separate rather than combining all vendor IP/VIP into one
partition, so one vendor update does not rebuild the rest.

## `verilog_dv_tb` attributes

Each `verilog_dv_tb` target should support exactly one simulator. Use
`simulator` to select the backend, and keep the public attribute names unified:

```python
verilog_dv_tb(
    name = "sys_tb",
    simulator = "VCS",
    deps = top_deps,
    defines = tb_defines,
    extra_compile_args = tb_compile_args,
    extra_runtime_args = tb_runtime_args,
    extra_runfiles = tb_runfiles,
)
```

For an Xcelium version of the same TB, create a separate target:

```python
verilog_dv_tb(
    name = "sys_tb_xrun",
    simulator = "XRUN",
    deps = top_deps,
    extra_compile_args = xrun_compile_args,
    extra_runtime_args = xrun_runtime_args,
)
```

## Argument ownership

Simulator arguments are defined and validated in their own modules:

- `bin/args_parse/vcs.py`: VCS coverage, FGP, DTL, ICO, VSO.ai, CCEX, Verdi GUI, SmartLog.
- `bin/args_parse/xcelium.py`: Xcelium coverage, MCE, MSIE, EMU and Xcelium-only probe controls.
- `bin/args_parse/common.py`: simmer scheduling, test selection, shared UVM, shared wave scope/time and result behavior.

Passing a vendor-specific option to the other backend fails after test-config
discovery resolves the backend and before simulator compile/run starts.
Use `extra_compile_args` only for compile/elaboration flags and
`extra_runtime_args` only for runtime flags. CLI `--sim-opts` overrides matching
test-config simulation options.

## Compatibility removals

The following unused or ambiguous interfaces were removed before this workflow
was merged:

- `verilog_test`; use `verilog_dv_unit_test` or `verilog_rtl_unit_test`.
- `extra_compile_args_vcs`; use `extra_compile_args` on a VCS testbench.
- `extra_runtime_args_vcs`; use `extra_runtime_args` on a VCS testbench.
- the unused CDC `run_template`; use `bash_template`.

Gate-simulation modes now default to the list owned by rules_verilog. Projects
that need different corners pass `gatesim_modes` explicitly to
`verilog_dv_test_cfg`; they no longer provide `@//deps:gatesim_modes_list.bzl`.

## VCS defaults

VCS compile filelists use `-file`. Runtime `simv` invocations use `-f`.

Batch VCS defaults are kept light:

- no default `-debug_access`
- no default `+vpi`
- no default xprop
- no default smartlog
- `-fastpartcomp=j8`

Enable debug features explicitly:

```bash
simmer -t <bench>:<test> --simulator VCS --waves
simmer -t <bench>:<test> --simulator VCS --gui
simmer -t <bench>:<test> --simulator VCS --smartlog
simmer -t <bench>:<test> --simulator VCS --vcs-xprop F
```

`--xprop` remains a compatibility spelling for VCS. Use `--vcs-xprop` in new
VCS commands so simulator-specific controls stay grouped in `simmer -h`.

VCS wave dumping supports FSDB only.

### FSDB probe and viewer flow

The default FSDB command probes `hdl_top`. Limit scope and time when possible:

```bash
simmer -t <bench>:<test> --simulator VCS \
  --waves hdl_top.dut hdl_top.env \
  --wave-depth 8 --wave-start 1000 --wave-end 50000
```

Successful wave runs create an executable `run_waves.sh` beside `waves.fsdb`.
It launches the standard Verdi FSDB viewer with `verdi -ssf`; it does not force
the Apex/VERDI-ULTRA or LCA feature tiers. Sites using LSF can provide a
launcher without editing the generated script:

```bash
SIMMER_WAVE_LAUNCHER="bsub -I -q syn" ./run_waves.sh
```

The generated UCLI script uses the file ID returned by `dump -file`, so it does
not assume `FSDB0` when another dump file is already open. The default
`--wave-depth 999` maps to UCLI `-depth 0`, which is the documented unlimited
hierarchy depth; explicit smaller depths are preserved.

VCS FSDB waves enable glitch and force information by default. Simmer passes
`+fsdb+glitch=0` and `+fsdb+force` to `simv`; generated UCLI also runs
`dump -glitch on` on the actual FSDB file ID. The generated `dump -add` keeps
`-fsdb_opt +packedmda+struct+parameter` because those object-selection options
are separate from glitch and force capture. Do not add `dump -forceEvent`: it
is a VPD command, while FSDB force/release/deposit data comes from
`+fsdb+force`.

Use `--wave-tcl <file>` for project-specific FSDB dump/probe commands. The
[editable VCS FSDB example](examples/vcs_fsdb_dump.tcl) shows per-scope depth,
timed enable/disable, glitch capture, flush and close ordering. A custom Tcl
file owns scopes, depths, timing, and `dump -glitch on`; keep its output at
`$::env(SIMRESULTS)/waves.fsdb` so simmer can find it and generate
`run_waves.sh`.

## Xcelium defaults

Xcelium batch defaults are:

- default simulator remains XRUN
- batch mode only
- waves default to VWDB when `--waves` is used without `--wave-type`
- xprop is opt-in; `--xprop F` uses a bench `fox_xprop.txt` when present and
  otherwise uses Xcelium's direct FOX mode

### Xcelium MSIE gatesim

Use multi-step MSIE when a stable gate netlist dominates elaboration time and
the testbench/tests change frequently. The complete model remains in `deps` for
the href stage; the two partitions are declared independently:

```python
verilog_dv_tb(
    name = "gate_tb_sdf_wc",
    simulator = "XRUN",
    deps = gate_netlist_deps + testbench_deps,
    dut_top = "dut",
    msie_primary_deps = gate_netlist_deps,
    msie_incremental_deps = testbench_deps,
    msie_primary_extra_compile_args = [
        "-sdf_cmd_file $(location :sdf_wc_cmd)",
    ],
    msie_primary_extra_runfiles = [":sdf_wc_cmd"],
)
```

Keep SDF/corner arguments in the partition where annotation occurs. Put only
truly common Xcelium compile arguments in `extra_compile_args`; use
`msie_primary_extra_compile_args` and `msie_incremental_extra_compile_args` for
partition-specific flags. The matching `*_extra_runfiles` attributes make
`$(location ...)` inputs available without coupling the two partitions.

Use one immutable key per Xcelium release, netlist release and gatesim corner.
All three commands must select the same Bazel target, `SIMRESULTS` root and
`--dir-suffix`:

```bash
export SIMRESULTS=/nfs/regression
MSIE_KEY='XCELIUM-25.03:netlist-r42:sdf_wc'
COMMON="-t gate_tb_sdf_wc:smoke_test@1 --simulator XRUN --dir-suffix _sdf_wc"

simmer $COMMON --msie-href dut
simmer $COMMON --msie-prim dut \
  --msie-primary-name dut_sdf_wc --msie-primary-key "$MSIE_KEY"
simmer $COMMON --msie-incr dut_sdf_wc --msie-primary-key "$MSIE_KEY"
```

`--msie-href` uses the complete Bazel filelist and writes generated artifacts
outside the source tree. `--msie-prim` uses only `msie_primary_deps` and stops
after creating the primary snapshot. `--msie-incr` uses only
`msie_incremental_deps`, validates the primary manifest, elaborates the final
snapshot and runs the selected tests.

The directories are intentionally isolated:

```text
<tb>__XRUN_VCOMP_HREF/       href analysis library
<tb>__XRUN_VCOMP_MSIE/       href.txt and generated *_externs.v
<tb>__XRUN_VCOMP_PRIM/       primary snapshot and compatibility manifest
<tb>__XRUN_VCOMP/            incremental/final snapshot
```

The manifest covers the Bazel target, primary top/name, explicit key, generated
primary filelist, primary source inventory, href/externs, coverage/covfile,
CLI defines, debug mode and Xcelium environment. A mismatch stops before XRUN
and names the changed fields. For netlists outside the checkout, encode their
immutable release in `--msie-primary-key`.

Coverage and compile-time debug settings must match on the primary and
incremental commands. In particular, functional coverage cannot be added only
at the incremental stage. If the netlist, SDF, href permissions, coverage or
tool release changes, rerun href and rebuild the primary; add `--recompile` to
the primary command when a clean library is required.

For single-step automatic partitioning, configure the complete model in `deps`
and run `simmer ... --simulator XRUN --msie dut`. Single-step mode does not use
the multi-step deps or a hardcoded `incr_pkg` top.

## Performance profiling

Use `--simmer-profile` to print phase and job timings after the summary:

```bash
simmer -t <bench>:<test> --simulator VCS --simmer-profile
```

The profile includes discovery, each Bazel command, Bazel external-repository
events, TB setup, VCS compile, test config builds, simulation jobs, job
directories, and commands. Repository rows are shown as `external_repo: NAME`
at the finest granularity Bazel records. A cached repository has no fetch or
repository-rule event, so it does not appear in that invocation.

Generated unit-test scripts print the failed command, line and exit code before
they close. For a script launched in a temporary terminal, keep the window open
after failure with:

```bash
SIMMER_KEEP_TERMINAL=1 ./rtl_unit_test
```

For quiet normal runs, avoid `--tool-debug`; it prints scheduler polling noise.

### Large IP/VIP builds

- Keep the VCS VCOMP directory between runs; Partition Compile and `-Mupdate`
  reuse unchanged third-party partitions and incremental compile outputs.
- Use `--no-compile --no-bazel` only after the existing `simv` has been validated.
- Keep stable third-party IP/VIP in separate Bazel libraries/filelists so a TB
  edit does not rewrite their generated inputs.
- Use `--fgp N` for runtime threading only after profiling; simmer reduces the
  number of concurrent tests to account for those threads.
- Avoid waves, `-debug_access`, VPI and SmartLog in throughput regressions.

DTL (`--dtl`) and VCS ICO (`--ico`) are opt-in advanced flows. DTL requires the
default Partition Compile flow. ICO does not change VCS compilation. Simmer
initializes a shared CDB with `crg -dir <shared_record> -shared init` and passes the recommended
`+ntb_solver_bias_mode_auto_config=2`, shared-record, work-directory, UVM test-type
and test-name options to each `simv`. Existing initialized CDBs are reused.

VSO.ai CSO (`--vso`) is separate from ICO. Simmer implements the documented
simplified three-step flow: VCS compiles with `-vso cso` and unique build names,
the driver runs init plus ask-all, selected `simv` runs receive `workdir` and
`run_id`, and finalize/merge receives the bulk status CSV. `--vso-phase` exposes
the documented stress, acceleration and exploration selection. `--vso-cbv`
adds the compile-time workdir tag required by Change-Based Verification and
requires line or port-only toggle learning in the Day0 model.

VSO.ai LCA Coverage Directed Solver (`--vso-ccex`) is a third independent flow.
It adds `-vso ccex` at compile and runtime. `--vso-ccex-rca` enables static RCA;
`--vso-ccex-auto-merge-dir` enables inter-simulation learning through shared
storage. Advanced `-ccex_opts` can be supplied through `--sim-opts-file` only
for runtime, or through `--file` for compile/elaboration, after checking the
installed release documentation.

These flows are not enabled by default because they require feature-specific
licenses, setup and real workload validation.

## Coverage generation and merge

VCS `--vcs-cm` writes one `.vdb` per vcomp and generates
`<vcomp>_vcs_cov_merge.sh`. The same configured VCS runner is used for `urg`
and Verdi. Xcelium `--coverage` keeps IMC generation and merge in the Xcelium
adapter. Coverage switches from one backend are rejected by the other.
The historical VCS spelling `--cm` remains a compatibility alias.

VCS coverage tuning follows the Y-2026.03 Command Reference and Coverage Guide.
Use `--vcs-cm-cond obs+event` for observability-based condition coverage plus
sensitivity-list events. Use `--vcs-cm-tgl portsonly` to reduce toggle cost, or
another documented mode when full signal coverage is required. Repeat
`--vcs-cm-report` for `svpackages` and `noinitial`. URG merge can opt into
`--vcs-urg-parallel` and `--vcs-urg-show-tests`; the latter retains test
correlation but increases VDB size.

Run report generation only when the regression database is complete. Keep raw
per-test coverage until the merge succeeds; merged databases and HTML reports
can then be archived while per-test databases are removed according to project
retention policy.

Each run clears stale test coverage before execution. Failed-test databases are
removed before merge, so the dashboard represents successful tests from the
current regression rather than accumulated leftovers. Missing metrics are
reported as `N/A`.

Dashboard aggregation matches OpenTitan's DVSim 1.34.1 rule. Code Coverage is
the mean of available Line/Statement, Branch, Condition/Expression, Toggle and
FSM values; Block is excluded. Total Coverage is then the mean of available
Code Coverage, Assertion Coverage and Functional CoverGroup Coverage values.
Missing components do not contribute to the denominator. Simulator-provided
`SCORE`/`Overall` remains available as the raw `cov_vendor_score` history field
and does not replace either calculated average.

## Filelist paths

Generated filelists use Bazel runfiles-root-relative paths. Main-workspace files
look like `hw/...`; external repositories look like `external/<repo>/...`.
`../` upward traversal is rejected by tests.

Do not replace generated paths with environment variables. Runfiles-relative
paths are hermetic, visible to Bazel and stable under the per-test
`bazel_runfiles_main` symlink. Environment-variable expansion differs across
EDA tools and nested filelist readers. Environment variables remain appropriate
for site launchers and installed tool roots, not source paths owned by Bazel.

## Rerun scripts

Each test generates an executable `rerun.sh` with the full Bazel test target,
seed and original simulator options. Run it directly from any directory. Set
`SIMMER_BIN=/path/to/simmer` only when `simmer` is not on `PATH`.

## Saving disk space

- Discovery metadata is cached under `.simmer/cache/` and can be deleted at any
  time. `--no-bazel` accepts it only while BUILD, `.bzl`, MODULE/WORKSPACE and
  Bazel configuration files remain older than the cache.
- Passing tests are removed by default. `--nt` intentionally retains them.
- Do not enable waves, coverage, SmartLog, ICO artifacts or `--nt` in routine
  throughput regressions.
- Reuse the VCS VCOMP directory instead of creating a new `--dir-suffix` for
  every run.
- Keep `.simmer_results.json` and compact regression logs; archive only failed
  logs and selected FSDB/coverage artifacts.
- Use `bazel clean` for stale Bazel outputs. Reserve `bazel clean --expunge` for
  deliberate cache removal because the next build will be fully cold.

## Simulation history

Normal simulation invocations are recorded in `.simmer_results.json` at the
project root, including compile and launch failures that prevent a test from
starting. The file is local run state and is intended for quick lookup of recent
outputs.

Print the most recent 10 runs:

```bash
simmer --history
simmer --his
```

Print a custom number of runs:

```bash
simmer --history 20
simmer --his 20
```

Each entry includes the original `simmer` command, compile log, and result log.
For a single test with wave dumping enabled, the history also shows the
generated `run_waves.sh` path. For multi-test regressions, the result path is
the regression log rather than every individual case log.

Example:

```text
[1] 2026-07-09 15:03:04  FAILED  87/100 pass, 13 fail
cmd:     simmer -t sys_tb:*@10
compile: /sim/sys_tb/cmp.log
result:  /sim/regression.log
```

Status words and pass/fail labels are colorized when output goes to a terminal.
Use `--use-color` to force color output:

```bash
simmer --use-color --history
```

Discovery-only and explicit compile-only invocations are not recorded. For a
started test, `duration_s` is the main simulator command time and
`wall_duration_s` is the complete test job time; a failure before the simulator
starts leaves `duration_s` unset.
