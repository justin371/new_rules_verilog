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

Legacy VCS-only names are still accepted for compatibility:

```python
extra_compile_args_vcs
extra_runtime_args_vcs
```

Do not mix the unified and legacy names in the same target.

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

The profile includes discovery, Bazel TB setup, VCS compile, test config builds,
simulation jobs, job directories, and commands. Use it to identify whether time
is going to Bazel setup, VCS compile, runtime simulation, or log checking.

For quiet normal runs, avoid `--tool-debug`; it prints scheduler polling noise.

