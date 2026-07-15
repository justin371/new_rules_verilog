# Verilog rules for Bazel

This repository pins Bazel 7.7.1 in `.bazelversion`. The final supported host is
Red Hat Linux with Python 3.12; macOS checks are useful for rule generation but
do not replace licensed VCS/Xcelium runs on Red Hat.

## Setup
                                                                                                  
Add the following to your `WORKSPACE` file:

```skylark
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

RULES_VERILOG_COMMIT = "<40-character commit SHA>"

http_archive(
    name = "rules_verilog",
    urls = ["https://github.com/justin371/new_rules_verilog/archive/{}.tar.gz".format(RULES_VERILOG_COMMIT)],
    sha256 = "<sha256 of the archive>",
    strip_prefix = "new_rules_verilog-{}".format(RULES_VERILOG_COMMIT),
)

load("@rules_verilog//:deps.bzl", "verilog_dependencies")
verilog_dependencies()
```
Pin a reviewed commit and its archive SHA rather than tracking `main` directly.


Cadence Xcelium needs both `HOME` and `LM_LICENSE_FILE`; add them to your `.bazelrc` file:

```
test --action_env=HOME
test --action_env=LM_LICENSE_FILE
```

For Synopsys VCS flows, you can add a named Bazel config in `.bazelrc` and invoke it explicitly. Example:

```bazelrc
build:vcs --@rules_verilog//:verilog_rtl_lint_test_command="runmod -t vcs --"
```

Then run a VCS-enabled target with:

```bash
bazel build --config=vcs //tests/vcs_filelist_validation:dv_tb_vcs
```

Note: `--config=vcs` only selects the VCS/Verdi wrapper commands. Targets that need VCS-specific behavior must still set `simulator = "VCS"`.

For `simmer` VCS runs, `--simulator VCS` is enough. The VCS, `simv`, and Verdi launcher prefix defaults to `runmod vcs --`.

```bash
simmer -t //hw/dv/project_benches/sys/tb:some_vcs_test --simulator VCS
```

Override the launcher with `RV_VCS_RUNNER` or `--vcs-runner` only when a project needs a different module wrapper.

VCS simulations use the two-step `verilog_dv_tb` + `simmer` flow. The one-step
DV and RTL unit-test rules remain Xcelium-only.

### VCS FSDB wave dumping

VCS wave capture uses FSDB. These commands cover the generated simmer flow:

```bash
# Default hdl_top scope, all hierarchy, full simulation.
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --waves

# Selected scopes and eight hierarchy levels below each scope.
simmer -t 'sys_tb:smoke_test@1' --simulator VCS \
  --waves hdl_top.dut hdl_top.env --wave-depth 8

# Capture only the 1000 ns through 50000 ns interval.
simmer -t 'sys_tb:smoke_test@1' --simulator VCS \
  --waves hdl_top.dut --wave-start 1000 --wave-end 50000

# Use a project-owned UCLI file for per-scope depth and advanced FSDB controls.
simmer -t 'sys_tb:smoke_test@1' --simulator VCS --waves \
  --wave-tcl ./debug/vcs_fsdb_dump.tcl
```

The generated FSDB controls are:

| simmer argument | Effect |
|-----------------|--------|
| `--waves [scope ...]` | Enables FSDB and selects one or more HDL scopes; no scope defaults to `hdl_top`. |
| `--wave-depth N` | Applies depth `N` to every selected scope. The default captures all hierarchy. |
| `--wave-start NS` | Starts dumping at an absolute, non-negative simulation time in ns. |
| `--wave-end NS` | Stops dumping at an absolute time in ns; it must be greater than `--wave-start`. |
| `--wave-tcl FILE` | Uses a VCS UCLI file instead of generated scope, depth, and time commands. |

Copy the [VCS FSDB Tcl example](docs/examples/vcs_fsdb_dump.tcl) when different
scopes need different depths or when `dump -add` needs advanced UCLI options.
Useful revisions include `-aggregates`, `-ports`/`-in`/`-out`/`-inout`, and
`-fsdb_opt` values such as `+mda`, `+packedmda`, `+struct`, `+parameter`,
`+sva`, `+strength`, `+Reg_Only`, `+IO_Only`, or `+by_file=<file>`. UCLI also
supports `dump -suppress_file`, `dump -suppress_instance`, `dump -deltaCycle`
and `dump -glitch`; follow the installed VCS guide because some must be issued
before the first `dump -add` or require environment setup.

With `--wave-tcl`, the Tcl file owns scopes, depths, and dump timing. Keep the
output at `$::env(SIMRESULTS)/waves.fsdb` so simmer can find it and generate
`run_waves.sh`. Open Verdi locally or through the site LSF queue:

```bash
./run_waves.sh
SIMMER_WAVE_LAUNCHER="bsub -I -q syn" ./run_waves.sh
```

### Unit tests with Xcelium

Use Xcelium for one-step unit-test targets:

```starlark
verilog_rtl_unit_test(
    name = "counter_test_xrun",
    deps = [":counter_test_top"],
    simulator = "XRUN",
)

```

Configure the Xcelium site wrappers independently from the VCS regression flow:

```bazelrc
build:xrun --@rules_verilog//:verilog_dv_unit_test_command="runmod -t xrun --"
build:xrun --@rules_verilog//:verilog_rtl_unit_test_command="runmod -t xrun --"
```

Run the Xcelium unit test on the Red Hat workstation:

```bash
bazel test --config=xrun //path/to:counter_test_xrun
```

`runmod` is a site-provided command from a separate repository and is assumed
to be available on `PATH`.

### VCS Partition Compile

VCS enables automatic compile fingerprint reuse and Partition Compile by
default. An unchanged fingerprint bypasses VCS; a changed build uses the
allocation-aware partition flow. The writable partition database is
`<tb>__VCS_VCOMP/partitionlib`; `--waves` and `--gui` use sibling
`partitionlib_waves` and `partitionlib_gui` databases so incompatible KDB
options do not invalidate each other. Stable third-party IP/VIP
partitions are reused while changed project RTL and testbench partitions are
rebuilt. Tune parallel compilation after measuring the workstation:

```bash
simmer -t 'sys_tb:smoke_test@1' --simulator VCS \
  --vcs-partcomp-jobs 16 --vcs-profile
```

Use `--no-vcs-partcomp` for an unsupported VCS release or a regular `-Mupdate`
comparison. Use `--no-vcs-auto-compile-cache` to invoke VCS even when the
fingerprint matches. Shared partition databases and the full compatibility
guidance are documented in [VCS and Xcelium
workflow](docs/simmer_vcs_xcelium.md#vcs-partition-compile).

### VCS ICO and VSO.ai

ICO, VSO.ai CSO and VSO.ai Coverage Directed Solver are separate opt-in flows:

```bash
simmer -t 'sys_tb:*@20' --simulator VCS --ico \
  --ico-shared-record /nfs/project/ico/shared_record

simmer -t 'sys_tb:*@100' --simulator VCS --vso --vso-cbv --vcs-cm line \
  --vso-dbdir /nfs/project/vso/model --vso-phase stress:3

simmer -t 'sys_tb:*@20' --simulator VCS --vso-ccex \
  --vso-ccex-auto-merge-dir /nfs/project/ccex/shared
```

ICO uses the runtime-only shared-CDB model from the Y-2026.03 ICO Guide. VSO.ai
CSO uses the documented simplified init/ask-all/execute/finalize+merge model;
CCEX adds `-vso ccex` at compile and runtime. They cannot be combined in one
invocation and still require licensed Red Hat validation.

### Xcelium MSIE gatesim

For heavy gate-level simulation, keep the stable gate netlist in
`msie_primary_deps` and the changing testbench/tests in
`msie_incremental_deps`. Simmer generates both Xcelium filelists through Bazel;
do not maintain source-tree `msie/*_prim.f` or `*_incr.f` files.

Run the same test target with the same `SIMRESULTS` and `--dir-suffix` through
the three multi-step stages:

```bash
MSIE_KEY='XCELIUM-25.03:netlist-r42:sdf_wc'
simmer -t 'gate_tb:smoke_test@1' --simulator XRUN \
  --msie-href dut --dir-suffix _sdf_wc
simmer -t 'gate_tb:smoke_test@1' --simulator XRUN \
  --msie-prim dut --msie-primary-name dut_sdf_wc \
  --msie-primary-key "$MSIE_KEY" --dir-suffix _sdf_wc
simmer -t 'gate_tb:smoke_test@1' --simulator XRUN \
  --msie-incr dut_sdf_wc --msie-primary-key "$MSIE_KEY" \
  --dir-suffix _sdf_wc
```

The incremental stage validates the primary top/name, corner key, generated
filelist, primary inputs, href/externs, coverage/debug configuration and
Xcelium environment before XRUN starts. Full BUILD configuration, coverage
rules and rebuild instructions are in the
[Xcelium MSIE gatesim workflow](docs/simmer_vcs_xcelium.md#xcelium-msie-gatesim).

### Regression dashboard

The static HTML dashboard is generated at the end of a `simmer` regression.
Always quote test globs so the shell does not expand them. Generate a VCS or
Xcelium report with:

```bash
simmer -t 'sys_tb:*@1' --simulator VCS \
  --report --report-dir "$PWD/report-output"

simmer -t 'sys_tb:*@1' --simulator XRUN \
  --report --report-dir "$PWD/report-output"
```

Add simulator-specific coverage when coverage results should appear in the
dashboard:

```bash
simmer -t 'sys_tb:*@10' --simulator VCS --vcs-cm A \
  --report --report-dir "$PWD/report-output"

simmer -t 'sys_tb:*@10' --simulator XRUN --coverage A \
  --report --report-dir "$PWD/report-output"
```

For VCS, `--vcs-cm-cond obs+event`, `--vcs-cm-tgl portsonly`,
`--vcs-urg-parallel`, and `--vcs-urg-show-tests` expose the documented coverage
collection and merge controls without leaking them into XRUN.

Configure coverage files on the matching testbench target: use `vcs_cm_hier`
for VCS or `xcelium_covfile` for Xcelium, plus `dut_top`/`dut_instance` when the
defaults do not match the design hierarchy. Failed tests and stale databases
are excluded from the current-run coverage merge; unavailable metrics display
as `N/A` rather than a false zero.

Coverage totals follow the two-level average used by OpenTitan's pinned DVSim
1.34.1. Code Coverage is the arithmetic mean of the available Line/Statement,
Branch, Condition/Expression, Toggle and FSM metrics; Block is shown when
reported but is not part of that average. Total Coverage is the arithmetic mean
of the available Code Coverage, Assertion Coverage and Functional CoverGroup
Coverage values. Missing values are omitted from each denominator. A simulator
`SCORE`/`Overall` value is retained as `cov_vendor_score` in `regressions.json`
for reference, but is not used as Code Coverage or Total Coverage.

The dashboard entry point and drill-down pages are written under:

```text
<report-dir>/regression_report/index.html
<report-dir>/regression_report/<project>/index.html
<report-dir>/regression_report/<project>/<bench>/index.html
```

Open a local report on a Red Hat workstation with:

```bash
xdg-open "$PWD/report-output/regression_report/index.html"
```

For a remote workstation, serve the static files on its loopback interface:

```bash
python3.12 -m http.server 8000 \
  --bind 127.0.0.1 \
  --directory "$PWD/report-output/regression_report"
```

Forward that port from the local machine, then open `http://localhost:8000/`:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@redhat-host
```

The default simulation and report roots are
`${XDG_STATE_HOME:-$HOME/.local/state}/simmer` and its `webroot` subdirectory.
Override the report per command with `--report-dir`, or configure shared result
and report locations and a public URL:

```bash
export SIMRESULTS=/nfs/regression
export SIMMER_REPORT_DIR="$SIMRESULTS/webroot"
export SIMMER_REPORT_URL=https://regression.example.com/regression_report
simmer -t 'sys_tb:*' --simulator VCS --report
```

`SIMMER_REPORT_URL` only changes the report link printed by `simmer`; a web
server must expose `<SIMMER_REPORT_DIR>/regression_report` at that URL. Run
`simmer --help` for the complete CLI. From this repository, the same help is
available without installing a wrapper:

```bash
bazel run //bin:simmer -- --help
```

The [simmer command cookbook](docs/simmer_vcs_xcelium.md#command-cookbook)
collects ready-to-adapt commands for normal runs, reuse, waves, coverage,
reporting, MSIE, Palladium, ICO, VSO.ai and CCEX.

`--no-compile` reuse is rejected when source/runfile content, an external
compile configuration, or the selected simulator tool environment changes.
Recent normal-run compile/start failures remain visible through `simmer --history`.

### Python Dependencies
rules_verilog uses the Python libraries listed in `requirements.txt`, but it
does not create a pip repository or install them. The top-level project owns
Python dependency installation so that every external rules repository shares
the same environment. Install the requirements into the Python 3.12 environment
used by Bazel before running `simmer`:

```bash
python3.12 -m pip install -r path/to/rules_verilog/requirements.txt
```

rules_verilog BUILD packages intentionally avoid workspace-owned Python
requirement labels so `@rules_verilog//bin:simmer` can be loaded from an
external repository.

### Red Hat validation

The workstation must expose Python 3.12 as `python3.12` and Bazel 7.7.1 as
`bazel`. Run the no-license portability checks before licensed VCS/Xcelium
tests:

```bash
./tests/redhat_smoke.sh
```

The script prints the failing line and command before it exits. Licensed unit
tests still need to be run separately with both `--config=xrun` and
`--config=vcs` on the configured Red Hat EDA host.

## Rules

### RTL
Load rules into your `BUILD` files from [@rules_verilog//verilog:defs.bzl](verilog/defs.bzl)

- [verilog_rtl_library](docs/defs.md#verilog_rtl_library)
- [verilog_rtl_pkg](docs/defs.md#verilog_rtl_pkg)
- [verilog_rtl_shell](docs/defs.md#verilog_rtl_shell)
- [verilog_rtl_unit_test](docs/defs.md#verilog_rtl_unit_test)
- [verilog_rtl_lint_test](docs/defs.md#verilog_rtl_lint_test)
- [verilog_rtl_cdc_test](docs/defs.md#verilog_rtl_cdc_test)


### DV
Load rules into your `BUILD` files from [@rules_verilog//verilog:defs.bzl](verilog/defs.bzl)

- [verilog_dv_library](docs/defs.md#verilog_dv_library)
- [verilog_dv_unit_test](docs/defs.md#verilog_dv_unit_test)
- [verilog_dv_tb](docs/defs.md#verilog_dv_tb)
- [verilog_dv_test_cfg](docs/defs.md#verilog_dv_test_cfg)


### Generic Verilog
Load rules into your `BUILD` files from [@rules_verilog//verilog:defs.bzl](verilog/defs.bzl)


### Migration Notes
- [Simulator migration checklist](docs/simulator_migration_checklist.md)
- [Simmer VCS and Xcelium flow](docs/simmer_vcs_xcelium.md)
- [EDA workflow review and low-use features](docs/eda_workflow_review.md)

## Caveats
- The SVUnit package always adds svunit_pkg.sv to the compiler command line after the user flists.  Without compiler library discovery, user flists cannot include/import anything that depends on svunit_pkg.
    - To work around this ordering dependency, the project Bazel rules must create the verilog_rtl_lib using the module files as headers, and use a dummy .sv file as the top module.
    - By declaring the module files as headers, they will not get put on the compiler command line via flists - rather their parents directory appears as an incdir.
    - This allows SVUnit's generated flist to appear last on the compiler command line, without violating any compiler ordering dependencies.

### Vendor Support
These rules were written with the Cadence and Synopsys tools as the underlying compiler and simulator. Abstraction leaks are prevalent throughout the rules.

### UVM Testbenches
Use one-step `verilog_dv_unit_test`/`verilog_rtl_unit_test` for small tests under
either simulator. Full VCS UVM regressions should use
[verilog_dv_tb](docs/defs.md#verilog_dv_tb),
[verilog_dv_test_cfg](docs/defs.md#verilog_dv_test_cfg), and `simmer` so the
compiled `simv` can be reused across tests.
