# EDA Workflow Review

## Implemented

- Bazel and CI are pinned to 7.7.1; Python dependencies are explicit Bazel deps.
- VCS and Xcelium generate and validate separate compile/runtime arguments.
- DV and RTL unit-test rules generate native XRUN or VCS scripts.
- VCS RTL unit tests support FSDB generation and Verdi launch.
- `rerun.sh`, `run_waves.sh` and log-checker lookup are portable across main and external workspaces.
- VCS coverage uses one `.vdb` path from simulation through URG merge.
- EMU compile outputs are excluded from VCS runfiles and consumed only by Xcelium EMU flow.
- Generated filelists reject `../`; `external/<repo>/...` is intentionally retained.
- Regression history keeps code and functional coverage as separate chart series.

## Opt-in or low-use features

| Feature | Status | Enable only when |
| --- | --- | --- |
| VSO.ai | Supported by `--vso`; off by default | VSO license/setup exists and the regression has measurable coverage goals |
| Dynamic Test Loading | Supported by `--dtl`; batch only | Compile savings exceed the extra static/dynamic flow complexity |
| Fine-Grained Parallelism | Supported by `--fgp N` | Profiling shows runtime CPU scaling and license capacity is available |
| Verdi GUI/reverse debug | Supported for one VCS test | Interactive debug is required; never for throughput regressions |
| Full FSDB probes | Supported | A narrow probe cannot reproduce the issue; high disk cost is accepted |
| Xcelium EMU/Palladium | Project-template driven | `EMU_JINJA2_PATH` and site-specific runtime libraries are validated on Red Hat |

Xcelium EMU runtime assets can be overridden with `RV_EMU_DPI_LIB` and
`RV_EMU_XMLIBDIR`; these site paths intentionally do not appear in VCS modules.

## Kept intentionally

- `SimulatorInterface` remains the explicit seam between simmer and two real EDA adapters. It is broad, but deleting it would spread vendor branching back into simmer.
- `external/<repo>/...` paths remain in generated filelists because they are Bazel's stable runfiles representation. Environment variables are reserved for site tool setup.
- VCS regression testbenches remain a two-step compile/run flow; one-step VCS support is limited to small unit tests.

## Needs licensed Red Hat validation

- VCS/Xcelium compile and simulation, URG/IMC merge and FSDB viewer launch.
- VSO.ai init/ask/tell/finalize against the installed release.
- DTL with the site's third-party VIP and precompiled-library layout.
- Xcelium EMU templates and hardcoded site runtime assets.
