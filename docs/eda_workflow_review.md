# EDA Workflow Review

## Implemented

- Bazel and CI are pinned to 7.7.1; Python dependencies are explicit Bazel deps.
- VCS and Xcelium generate and validate separate compile/runtime arguments.
- DV and RTL one-step unit-test rules remain XRUN-only.
- `rerun.sh`, `run_waves.sh` and log-checker lookup are portable across main and external workspaces.
- VCS coverage uses one `.vdb` path from simulation through URG merge.
- VCS Partition Compile keeps each writable database under its VCOMP directory
  and can reuse an explicitly versioned shared baseline.
- EMU compile outputs are excluded from VCS runfiles and consumed only by Xcelium EMU flow.
- Generated filelists reject `../`; `external/<repo>/...` is intentionally retained.
- Regression history keeps code and functional coverage as separate chart series.

## Opt-in or low-use features

| Feature | Status | Enable only when |
| --- | --- | --- |
| VCS ICO | Supported by `--ico`; off by default | ICO license/setup exists and the shared CDB is on a supported filesystem |
| VSO.ai CSO | Simplified init/ask-all/execute/finalize+merge flow | VSO_HOME, persistent model storage and matching VCS/VSO licenses are configured |
| VSO.ai CCEX | Compile/runtime CCEX with optional RCA and shared learning | Coverage Directed Solver is licensed and shared merge storage is validated |
| Dynamic Test Loading | Supported by `--dtl`; batch only | Compile savings exceed the extra static/dynamic flow complexity |
| Partition Compile shared baseline | Supported by `--vcs-partcomp --vcs-partcomp-sharedlib PATH` | Baseline matches the VCS release, Red Hat platform, sources and compile configuration |
| Fine-Grained Parallelism | Supported by `--fgp N` | Profiling shows runtime CPU scaling and license capacity is available |
| Verdi GUI/reverse debug | Supported for one VCS test | Interactive debug is required; never for throughput regressions |
| Full FSDB probes | Supported | A narrow probe cannot reproduce the issue; high disk cost is accepted |
| Xcelium EMU/Palladium | Project-template driven | `EMU_JINJA2_PATH` and site-specific runtime libraries are validated on Red Hat |

Xcelium EMU runtime assets can be overridden with `RV_EMU_DPI_LIB` and
`RV_EMU_XMLIBDIR`; these site paths intentionally do not appear in VCS modules.

## Kept intentionally

- `SimulatorInterface` remains the explicit seam between simmer and two real EDA adapters. It is broad, but deleting it would spread vendor branching back into simmer.
- `external/<repo>/...` paths remain in generated filelists because they are Bazel's stable runfiles representation. Environment variables are reserved for site tool setup.
- VCS simulations use the two-step `verilog_dv_tb` + `simmer` compile/run flow.

## Needs licensed Red Hat validation

- VCS/Xcelium compile and simulation, URG/IMC merge and FSDB viewer launch.
- VCS ICO shared-CDB initialization and concurrent simv updates against the installed release.
- VSO.ai CSO driver output, bulk status update, model merge and Change-Based Verification.
- VSO.ai CCEX inter-simulation learning, RCA and URG/Verdi CCEX reports.
- ICO non-NFS/CIOL setup; simmer currently automates only the documented NFS shared-record flow.
- DTL with the site's third-party VIP and precompiled-library layout.
- Xcelium EMU templates and hardcoded site runtime assets.
