# VERILOG RULE KNOWLEDGE

## OVERVIEW

Public Starlark facade plus RTL/DV rule implementations, providers, normalized filelists, and simulator-specific action metadata.

## STRUCTURE

```text
defs.bzl                  # supported consumer-facing exports
private/verilog.bzl       # shared providers, paths, inventories, tool settings
private/rtl.bzl           # RTL libraries, packages, shells, unit/lint/CDC rules
private/dv.bzl            # DV libraries, testbenches, test configs, unit tests
private/simulators/       # action metadata for VCS, Xcelium, and PLDM
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add/change public rule | `defs.bzl` | Alias implementation; update docs directly |
| Shared source/runfiles model | `private/verilog.bzl` | `VerilogInfo`, depsets, normalized short paths |
| RTL action behavior | `private/rtl.bzl` | Vendor template bundles must stay coherent |
| DV simulator dispatch | `private/dv.bzl` | Uppercase XRUN/VCS, TB/test-cfg consistency |
| Backend-generated metadata | `private/simulators/` | Used during Bazel analysis/action generation; `simmer` consumes the outputs |

## CONVENTIONS

- Consumers load only `//verilog:defs.bzl`; keep public names there and implementation helpers private by convention.
- Preserve stable, sorted file inventories and normalized `external/...` short paths; avoid `../` traversal.
- Expand `$location` arguments with matching `extra_runfiles` and `ctx.expand_location`.
- Simulator-specific defaults and validation belong in the matching backend path.
- VCS simulation is the two-step `verilog_dv_tb` plus `simmer` flow. One-step RTL/DV unit-test rules are XRUN-only; lint supports XRUN and VCS.
- Keep PLDM in its independent module, but treat its outputs as Xcelium emulation compatibility data rather than a third runtime backend.
- Update `docs/defs.md` and docs tests for public exports, attributes, defaults, or descriptions.
- Keep dependency declarations as providers/depsets and return complete `DefaultInfo` runfiles.

## ANTI-PATTERNS

- Do not tighten `verilog/private` visibility casually; existing Python discovery and tests consume private aspects/files.
- Do not put packages or shells in `verilog_rtl_library`; use `verilog_rtl_pkg` and `verilog_rtl_shell`.
- Do not set internal `is_pkg`/`is_shell_of`, use deprecated `sim_args`, or combine legacy `ccf` with `xcelium_covfile`.
- Do not glob DPI shared libraries into `srcs`; use the `dpi` attribute.
- Do not remove compatibility outputs or dormant checks without updating contract tests and consumers.

## CHECKS

```bash
bazel test //:buildifier_diff
bazel query //verilog/private:all
./tests/doc_test.sh
```
