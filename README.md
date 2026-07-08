# Verilog rules for Bazel

## Setup
                                                                                                  
Add the following to your `WORKSPACE` file:

```skylark
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
http_archive(                                                                                                                                                                            
    name = "rules_verilog",
    urls = ["https://github.com/Lightelligence/rules_verilog/archive/v0.0.0.tar.gz"],
    sha256 = "ab64a872410d22accb383c7ffc6d42e90f4de40a7cd92f43f4c26471c4f14908",
    strip_prefix = "rules_verilog-0.0.0",
)
load("@rules_verilog//:deps.bzl", "verilog_dependencies")
verilog_dependencies()
```
**Note**: Update commit and sha256 as needed.


Cadence Xcelium needs both HOME and LM_LICENESE_FILE environment variables, add them to your `.bazelrc` file:

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

VCS is supported through the two-step `simmer` flow. `verilog_dv_unit_test` and `verilog_rtl_unit_test` remain XRUN-only.

### Python Dependencies
rules_verilog is also dependent on several python libraries. These are defined in requirements.txt and maybe installed in the package manager of your choice. The recommended flow is to install them via the pip_install rule in your `WORKSPACE` file:

```skylark
load("@rules_python//python:pip.bzl", "pip_install")

pip_install(
    name = "pip_deps",
    requirements = "@rules_verilog//:requirements.txt",
)
```

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

- [verilog_test](docs/defs.md#verilog_test)

### Migration Notes
- [Simulator migration checklist](docs/simulator_migration_checklist.md)
- [Simmer VCS and Xcelium flow](docs/simmer_vcs_xcelium.md)

## Caveats
- The SVUnit package always adds svunit_pkg.sv to the compiler command line after the user flists.  Without compiler library discovery, user flists cannot include/import anything that depends on svunit_pkg.
    - To work around this ordering dependency, the project Bazel rules must create the verilog_rtl_lib using the module files as headers, and use a dummy .sv file as the top module.
    - By declaring the module files as headers, they will not get put on the compiler command line via flists - rather their parents directory appears as an incdir.
    - This allows SVUnit's generated flist to appear last on the compiler command line, without violating any compiler ordering dependencies.

### Vendor Support
These rules were written with the Cadence and Synopsys tools as the underlying compiler and simulator. Abstraction leaks are prevalent throughout the rules.

### UVM Testbenches
While rules for XRUN unit tests exist, VCS testbenches use [verilog_dv_tb](docs/defs.md#verilog_dv_tb), [verilog_dv_test_cfg](docs/defs.md#verilog_dv_test_cfg), and `simmer` for two-step compile and simulation.
