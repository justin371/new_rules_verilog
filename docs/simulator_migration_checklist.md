# Simulator Migration Checklist

This checklist is for validating the recent XRUN/VCS split after moving back to a Linux environment with working Bazel dependencies.

## What changed

- Simulator selection is now a rule attribute, not just a global runtime choice.
- `XRUN` remains the default simulator.
- `VCS` can be selected explicitly on supported rules with `simulator = "VCS"`.
- Mixed XRUN and VCS test runs are rejected by `simmer.py`.
- Generated filelists are now simulator-specific, but use unified names:
  - `<tb_name>_compile_args.f`
  - `<tb_name>_runtime_args.f`

## Rules to check

Focus on these rule families first:

- `verilog_dv_tb`
- `verilog_dv_test_cfg`
- `verilog_dv_unit_test`
- `verilog_rtl_unit_test`

## Recommended validation flow

1. Confirm the repository still loads:

```bash
bazel query //verilog/private:all
```

2. Regenerate the Stardoc output and confirm the docs stay in sync:

```bash
bazel build //docs:defs_docs
```

3. Run one existing DV test that does not set `simulator`. It should resolve to `XRUN`.

4. Add or select one DV test with `simulator = "VCS"` and run it through the normal `simmer` flow.

5. Confirm the generated filelists for a testbench are the unified names above, and that their contents match the selected simulator only.

6. Run one `verilog_dv_unit_test` with default settings under `XRUN`. VCS is not supported for this single-step rule; use `verilog_dv_tb` plus `simmer --simulator VCS` for the two-step flow.

7. Run one `verilog_rtl_unit_test` with default settings under `XRUN`. VCS is not supported for this single-step rule; use the VCS two-step `simmer` flow instead.

## Failure cases worth testing

These cases should fail fast and clearly:

- A test config requests `simulator = "VCS"` but its associated testbench is `XRUN`.
- A `simmer` invocation selects tests that resolve to different simulators.
- `--simulator` is passed on the command line and conflicts with the test configuration simulator.
- XRUN-only switches are passed to a VCS run.
- VCS-only switches are passed to an XRUN run.

## Things to look for in generated content

- XRUN templates should not emit VCS-only switches.
- VCS templates should not emit XRUN-only switches.
- Xcelium flow should not contain FSDB or EVCD support.
- VCS wave support should remain FSDB-only.
- Unit-test command wrappers should select the proper simulator command.

## Good smoke-test targets

If you want quick confidence before broader regression:

- One default XRUN DV regression target
- One explicit VCS DV regression target
- One DV unit test under XRUN
- One RTL unit test under XRUN

## Notes

- On Windows, this repository may still fail Bazel fetches if `WORKSPACE` uses Linux-only `file:///nfs/...` paths.
- The intended final validation environment for this migration is Linux.
