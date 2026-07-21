# PROJECT KNOWLEDGE BASE

**Reviewed:** 2026-07-17
**Baseline:** `main@2cfca6b`

## OVERVIEW

Bazel 7.7.1 rules and Python 3.12 tooling for Verilog RTL/DV builds, Xcelium/VCS simulation, regression scheduling, coverage, and reports. The repository is WORKSPACE-based; Bzlmod is disabled.

## STRUCTURE

```text
bin/          # simmer CLI, argument parsing, generated-script/report templates
lib/          # reusable regression, scheduling, simulator, coverage, report logic
verilog/      # public rule facade and private RTL/DV Starlark implementations
simulators/   # repository rules that discover installed simulator DPI headers
vendors/      # Bazel-substituted Cadence, Synopsys, and Real Intent templates
tests/        # unittest/Bazel tests plus external-workspace and VCS contract fixtures
examples/     # minimal APB and DPI consumer graphs
docs/         # directly maintained API and simulator workflow documentation
deps/         # pinned public and site-local repository declarations
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add or change a public Verilog rule | `verilog/defs.bzl`, `verilog/private/` | `defs.bzl` is the supported consumer facade |
| Trace a regression run | `bin/simmer.py`, `lib/regression.py`, `lib/job_lib.py` | Discovery -> job DAG -> simulator backend |
| Change CLI flags | `bin/args_parse/` | Common and backend flags are separated |
| Change backend behavior | `lib/simulators/` | `base.py` defines the seam; VCS/Xcelium implement it |
| Change generated commands or reports | `bin/templates/` | Jinja templates; context comes from `simmer.py` and backends |
| Change Bazel rule actions | `verilog/private/{rtl,dv,verilog}.bzl` | Shared providers/path logic belongs in `verilog.bzl`; backend logic belongs in `private/simulators/` |
| Change installed-tool discovery | `simulators/` | Separate from runtime adapters and DV rule backends |
| Validate generated VCS/XRUN contracts | `tests/vcs_filelist_validation/` | Tool stubs inspect scripts, filelists, and runtime behavior |
| Change public docs | `README.md`, `docs/defs.md`, `tests/docs_test.py` | Docs are maintained directly and link/anchor tested |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `main` | function | `bin/simmer.py` | Builds and runs the regression job graph |
| `RegressionConfig` | class | `lib/regression.py` | Bazel discovery, filtering, and cached configuration |
| `JobManager` | class | `lib/job_lib.py` | Dependency-aware threaded scheduler |
| `SimulatorInterface` | class | `lib/simulators/base.py` | Runtime backend contract |
| `VcsSimulator` / `XceliumSimulator` | classes | `lib/simulators/` | Compile, run, waves, coverage, artifact behavior |
| `verilog_*` exports | rules/macros | `verilog/defs.bzl` | Public Starlark API |

## CONVENTIONS

- Python uses YAPF 0.43.0 with `.style.yapf`; tests use stdlib `unittest` and explicit Bazel `py_test` dependencies.
- Starlark formatting and linting run through root Buildifier targets. Keep BUILD data/deps synchronized with Python modules and templates.
- Simulator names are uppercase `XRUN` or `VCS`; `SIM_PLATFORM` selects the CLI default and falls back to XRUN. Each DV target still records its simulator.
- `simmer` accepts one simulator per invocation. Quote selectors containing `*`.
- Large VCS simulation uses `verilog_dv_tb` plus `simmer`; one-step RTL/DV unit tests and RTL lint support XRUN and VCS.
- Public rule/API changes require direct updates to `docs/defs.md`; docs checks verify anchors and links, not full signature equality.
- Licensed simulator behavior is validated on Red Hat with Python 3.12. macOS and license-free CI validate generation only.

## PROJECT-SPECIFIC DON'TS

- Do not mix XRUN/VCS flags, templates, wave formats, or tests in one run.
- Do not hand-maintain MSIE primary/incremental filelists; Bazel and `simmer` generate them.
- Do not use `../` traversal or environment variables for Bazel-owned filelist paths; retain runfiles-relative paths.
- Do not load `verilog/private` from new consumer BUILD files. Existing internal use is compatibility-sensitive.
- Do not assume `//docs:defs_docs` exists: the migration checklist is stale; maintain docs directly.
- Do not treat `env.sh` or `.bazelrc` site wrappers as portable defaults; `runmod` and licensed tools are external.
- Do not treat PLDM as a third simulator backend. Its independent Starlark module emits compatibility inputs for Xcelium emulation.

## COMMANDS

```bash
bazel test --test_output=errors //:buildifier_diff //tests/... //examples/dpi:dpi_c_test
./tests/doc_test.sh
bazel run //bin:simmer -- --help
bazel run //:buildifier_lint
./tests/redhat_smoke.sh  # Red Hat-compatible host only
```

Licensed XRUN/VCS tests run separately on a configured Red Hat EDA host. CI does not run them.
