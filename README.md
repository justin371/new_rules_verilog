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

VCS regression testbenches use the two-step `simmer` flow. Small DV and RTL unit
tests support both `simulator = "XRUN"` and `simulator = "VCS"`.

### Unit tests with Xcelium and VCS

Select the backend on each unit-test target:

```starlark
verilog_rtl_unit_test(
    name = "counter_test_xrun",
    deps = [":counter_test_top"],
    simulator = "XRUN",
)

verilog_rtl_unit_test(
    name = "counter_test_vcs",
    deps = [":counter_test_top"],
    simulator = "VCS",
)
```

Site wrappers can be configured independently without mixing vendor arguments:

```bazelrc
build:xrun --@rules_verilog//:verilog_dv_unit_test_command="runmod -t xrun --"
build:xrun --@rules_verilog//:verilog_rtl_unit_test_command="runmod -t xrun --"

build:vcs --@rules_verilog//:verilog_dv_unit_test_command_vcs="runmod vcs -- vcs"
build:vcs --@rules_verilog//:verilog_rtl_unit_test_command_vcs="runmod vcs -- vcs"
build:vcs --@rules_verilog//:verilog_rtl_wave_viewer_command_vcs="runmod vcs -- verdi"
```

Run both backends on the Red Hat workstation:

```bash
bazel test --config=xrun //path/to:counter_test_xrun
bazel test --config=vcs //path/to:counter_test_vcs
```

`runmod` is a site-provided command from a separate repository and is assumed
to be available on `PATH`.

VCS RTL unit tests accept `--waves`, `--launch`, `--compile-arg <arg>`, and
`--run-arg <arg>` after Bazel's `--` separator.

### Python Dependencies
rules_verilog is also dependent on several python libraries. These are defined in requirements.txt and may be installed in the package manager of your choice. The recommended flow is to install them via the `pip_parse` rule in your `WORKSPACE` file:

```skylark
load("@rules_python//python:pip.bzl", "pip_parse")

pip_parse(
    name = "pip_deps",
    requirements_lock = "@rules_verilog//:requirements.txt",
)

load("@pip_deps//:requirements.bzl", "install_deps")
install_deps()
```

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
