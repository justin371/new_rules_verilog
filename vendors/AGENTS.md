# VENDOR TEMPLATE KNOWLEDGE

## OVERVIEW

Public, overrideable Bazel templates for Cadence Xcelium/HAL/Jasper, Synopsys VCS/Verdi, and Real Intent Ascent lint flows.

## SIMULATOR MATRIX

| Directory | Contract |
|-----------|----------|
| `cadence/` | `-define`, `-f`, integrated xrun; HAL lint and Jasper CDC |
| `synopsys/` | `+define+`, `-file`, compile to `simv`, UCLI/FSDB/Verdi |
| `real_intent/` | Ascent lint shell/Tcl pair; template label identity affects rule behavior |

## CONVENTIONS

- These files use literal placeholders such as `{FLISTS}` and `{PRE_FLIST_ARGS}` expanded by Starlark actions, not Jinja.
- Keep each rule's run template, command template, lint parser, rule file, and wrapper command as a coherent vendor bundle.
- Preserve shell strict mode, quoting, arrays, line continuations, cleanup, and original simulator exit status.
- Preserve vendor-specific timebases: Cadence DV uses 1ps/1ps, Synopsys DV uses 1ns/1ps, and RTL unit tests use 100fs/100fs.
- Keep VCS compile/run separation and Xcelium integrated execution distinct.
- Update the owning `BUILD` exports and generated-contract tests with template changes.

## ANTI-PATTERNS

- Do not normalize Cadence and Synopsys flag syntax or wave formats.
- Do not execute `cadence/verilog_rtl_lint_cmds.tcl.template`; HAL deliberately has no command script.
- Do not convert the Synopsys lint `.tcl` file to Tcl; it is intentionally a VCS argument file.
- Do not rename the Real Intent run-template label without tracing the special-case behavior in `verilog/private/rtl.bzl`.
- Do not add `-partcomp` to the Synopsys DV compile template; partition compile is managed elsewhere.
- Do not reflow `{PRE_FLIST_ARGS}` placeholder lines; embedded continuations are part of the generated shell contract.

## CHECKS

```bash
bazel test //tests/vcs_filelist_validation:vcs_runtime_contract_test
bazel test //:buildifier_diff
```
