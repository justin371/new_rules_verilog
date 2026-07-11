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

## VCS compile reuse

The default VCS flow is incremental:

1. First run builds `<tb>__VCS_VCOMP/simv`.
2. Later runs reuse the same VCOMP directory.
3. VCS decides what to rebuild through `-Mupdate`, `-Mdir`, and `-Mlib`.

The normal command still enters the VCS compile/elaboration step:

```bash
simmer -t <bench>:<test> --simulator VCS
```

That is intentional. It keeps the build correct while allowing VCS incremental
compile to avoid full rebuilds. Use these only when you intentionally want to
reuse existing outputs without rebuilding:

```bash
simmer -t <bench>:<test> --simulator VCS --no-compile
simmer -t <bench>:<test> --simulator VCS --no-compile --no-bazel
```

Use `--recompile` to force a clean VCS compile.

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

- `bin/args_parse/vcs.py`: VCS coverage, FGP, DTL, VSO.ai, Verdi GUI, SmartLog.
- `bin/args_parse/xcelium.py`: Xcelium coverage, MCE, MSIE, EMU and Xcelium-only probe controls.
- `bin/args_parse/common.py`: simmer scheduling, test selection, shared UVM, shared wave scope/time and result behavior.

Passing a vendor-specific option to the other backend fails before Bazel starts.
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
simmer -t <bench>:<test> --simulator VCS --xprop F
```

VCS wave dumping supports FSDB only.

### FSDB probe and viewer flow

The default FSDB command probes `hdl_top`. Limit scope and time when possible:

```bash
simmer -t <bench>:<test> --simulator VCS \
  --waves hdl_top.dut hdl_top.env \
  --wave-depth 8 --wave-start 1000 --wave-end 50000
```

Successful wave runs create an executable `run_waves.sh` beside `waves.fsdb`.
It launches Verdi directly by default. Sites using LSF can provide a launcher
without editing the generated script:

```bash
SIMMER_WAVE_LAUNCHER="bsub -I -q syn" ./run_waves.sh
```

Use `--wave-tcl <file>` for project-specific FSDB dump/probe commands. Keep the
generated default as the reference for `dump -file`, `dump -add`, timed enable/
disable, flush and close ordering.

## Xcelium defaults

Xcelium behavior is unchanged:

- default simulator remains XRUN
- batch mode only
- waves default to VWDB when `--waves` is used without `--wave-type`
- xprop defaults to FOX through the existing `--xprop F` behavior

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

- Keep the VCS VCOMP directory between runs; `-Mupdate`, `-Mdir` and `-Mlib`
  provide incremental compile reuse.
- Use `--no-compile --no-bazel` only after the existing `simv` has been validated.
- Keep stable third-party IP/VIP in separate Bazel libraries/filelists so a TB
  edit does not rewrite their generated inputs.
- Use `--fgp N` for runtime threading only after profiling; simmer reduces the
  number of concurrent tests to account for those threads.
- Avoid waves, `-debug_access`, VPI and SmartLog in throughput regressions.

DTL (`--dtl`) and VSO.ai (`--vso`) are opt-in advanced flows. They are not
enabled by default because they require feature-specific licenses, setup and
real workload validation.

## Coverage generation and merge

VCS `--cm` writes one `.vdb` per vcomp and generates
`<vcomp>_vcs_cov_merge.sh`. The same configured VCS runner is used for `urg`
and Verdi. Xcelium `--coverage` keeps IMC generation and merge in the Xcelium
adapter. Coverage switches from one backend are rejected by the other.

Run report generation only when the regression database is complete. Keep raw
per-test coverage until the merge succeeds; merged databases and HTML reports
can then be archived while per-test databases are removed according to project
retention policy.

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
- Do not enable waves, coverage, SmartLog, VSO artifacts or `--nt` in routine
  throughput regressions.
- Reuse the VCS VCOMP directory instead of creating a new `--dir-suffix` for
  every run.
- Keep `.simmer_results.json` and compact regression logs; archive only failed
  logs and selected FSDB/coverage artifacts.
- Use `bazel clean` for stale Bazel outputs. Reserve `bazel clean --expunge` for
  deliberate cache removal because the next build will be fully cold.

## Simulation history

Completed simulation runs are recorded in `.simmer_results.json` at the project
root. The file is local run state and is intended for quick lookup of recent
simulation outputs.

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

Runs that only discover tests, compile without running simulation, or fail
before any simulation job starts are not recorded.
