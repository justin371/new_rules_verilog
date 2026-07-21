<!-- Maintained with the public rule definitions in verilog/defs.bzl. -->

Public entry point to all supported Verilog rules and APIs

<a id="verilog_dv_library"></a>

## verilog_dv_library

<pre>
verilog_dv_library(<a href="#verilog_dv_library-name">name</a>, <a href="#verilog_dv_library-deps">deps</a>, <a href="#verilog_dv_library-dpi">dpi</a>, <a href="#verilog_dv_library-in_flist">in_flist</a>, <a href="#verilog_dv_library-incdir">incdir</a>, <a href="#verilog_dv_library-makelib">makelib</a>, <a href="#verilog_dv_library-srcs">srcs</a>)
</pre>

A DV Library.
    
    Creates a generated flist file from a list of source files.
    
    Generated paths use Bazel short_path form so the flist is rooted at the
    runfiles tree (for example `hw/...` and `external/...`). Hand-authored nested
    filelists should prefer the same style and avoid `../` upward traversals.
    
    Recommended DPI usage is to keep SystemVerilog files in `srcs`/`in_flist` and
    provide shared libraries through the `dpi` attribute, for example:

```python
cc_binary(
    name = "dpi",
    srcs = glob(["*.c"]),
    linkshared = True,
)

verilog_dv_library(
    name = "pkg",
    srcs = glob(["*.sv"]),
    dpi = [":dpi"],
)
```
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_dv_library-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_dv_library-deps"></a>deps |  verilog_dv_library targets that this target is dependent on.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_library-dpi"></a>dpi |  Shared libraries to load through the DPI. Build source-based DPI libraries with `cc_binary(linkshared = True)` and pass that target here. Currently, cc_import is not supported for precompiled shared libraries. Prefer placing shared libraries here rather than globbing `.so` files into `srcs`. Example: `cc_binary(name = "dpi", srcs = glob(["*.c"]), linkshared = True)` then `verilog_dv_library(name = "pkg", srcs = glob(["*.sv"]), dpi = [":dpi"])`.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_library-in_flist"></a>in_flist |  Files to be placed directly in the generated flist. Best practice recommends 'pkg' and 'interface' files be declared here. If this attribute is empty (default), all srcs will put into the flist instead.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_library-incdir"></a>incdir |  Generate a +incdir in generated flist for every file's directory declared in 'srcs' attribute.   | Boolean | optional | True |
| <a id="verilog_dv_library-makelib"></a>makelib |  Compile this target into the named Xcelium library through `-makelib`/`-endlib`. VCS receives the same ordered sources through a separate `-file` boundary; VCS recompilation isolation is provided by `-Mupdate` and Partition Compile rather than Xcelium library syntax.   | String | optional | `""` |
| <a id="verilog_dv_library-srcs"></a>srcs |  Systemverilog source files. Files are assumed to be \<code>included inside another file (e.g. the package file) and will not be placed on directly in the flist unless declared in the 'in_flist' attribute.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |


<a id="verilog_dv_tb"></a>

## verilog_dv_tb

<pre>
verilog_dv_tb(<a href="#verilog_dv_tb-name">name</a>, <a href="#verilog_dv_tb-ccf">ccf</a>, <a href="#verilog_dv_tb-defines">defines</a>, <a href="#verilog_dv_tb-deps">deps</a>, <a href="#verilog_dv_tb-dut_instance">dut_instance</a>, <a href="#verilog_dv_tb-dut_top">dut_top</a>, <a href="#verilog_dv_tb-extra_compile_args">extra_compile_args</a>, <a href="#verilog_dv_tb-extra_runfiles">extra_runfiles</a>,
              <a href="#verilog_dv_tb-extra_runtime_args">extra_runtime_args</a>, <a href="#verilog_dv_tb-msie_incremental_deps">msie_incremental_deps</a>, <a href="#verilog_dv_tb-msie_incremental_extra_compile_args">msie_incremental_extra_compile_args</a>, <a href="#verilog_dv_tb-msie_incremental_extra_runfiles">msie_incremental_extra_runfiles</a>, <a href="#verilog_dv_tb-msie_primary_deps">msie_primary_deps</a>, <a href="#verilog_dv_tb-msie_primary_extra_compile_args">msie_primary_extra_compile_args</a>, <a href="#verilog_dv_tb-msie_primary_extra_runfiles">msie_primary_extra_runfiles</a>, <a href="#verilog_dv_tb-run_fail_patterns">run_fail_patterns</a>, <a href="#verilog_dv_tb-run_pass_patterns">run_pass_patterns</a>, <a href="#verilog_dv_tb-shells">shells</a>, <a href="#verilog_dv_tb-simulator">simulator</a>, <a href="#verilog_dv_tb-vcs_cm_hier">vcs_cm_hier</a>, <a href="#verilog_dv_tb-verilog_config">verilog_config</a>, <a href="#verilog_dv_tb-warning_waivers">warning_waivers</a>, <a href="#verilog_dv_tb-xcelium_covfile">xcelium_covfile</a>)
</pre>

A DV Testbench.
    
    rules_verilog uses two separate rules to strongly differentiate between
    compilation and simulation. verilog_dv_tb is used for compilation and    
    verilog_dv_test_cfg is used for simulation.

    A verilog_dv_tb describes how to compile a testbench. It is not a
    standalone executable bazel rule. It is intended to provide simmer (a
    higher level simulation spawning tool) hooks to execute the compile and
    subsequent simulations.

    The compile and runtime filelists are generated according to the selected
    simulator. The generated file names are `<name>_compile_args.f` and
    `<name>_runtime_args.f`.
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_dv_tb-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_dv_tb-ccf"></a>ccf |  Xcelium coverage configuration file. At most one file is accepted; VCS coverage uses `-cm` options instead.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_tb-defines"></a>defines |  Additional preprocessor defines to throw for this testbench compile. Key, value pairs are joined without additional characters. If it is a unary flag, set the value portion to be the empty string. For binary flags, add an '=' as a suffix to the key.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| <a id="verilog_dv_tb-deps"></a>deps |  A list of verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on. Dependency ordering within this label list is not necessary if dependencies are consistently declared in all other rules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| <a id="verilog_dv_tb-dut_instance"></a>dut_instance |  DUT instance hierarchy used by coverage reports.   | String | optional | `"hdl_top.dut"` |
| <a id="verilog_dv_tb-dut_top"></a>dut_top |  DUT module name used to scope code coverage.   | String | optional | `"dut"` |
| <a id="verilog_dv_tb-extra_compile_args"></a>extra_compile_args |  Additional flags to pass to the selected simulator compile/elaboration step.   | List of strings | optional | [] |
| <a id="verilog_dv_tb-extra_runfiles"></a>extra_runfiles |  Additional files that need to be passed as runfiles to bazel. Most commonly used for files referred to by extra_compile_args or extra_runtime_args.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_tb-extra_runtime_args"></a>extra_runtime_args |  Additional flags passed only to simulator runs. Runtime path arguments should use absolute paths or `bazel_runfiles_main/...` paths.   | List of strings | optional | [] |
| <a id="verilog_dv_tb-msie_incremental_deps"></a>msie_incremental_deps |  Xcelium MSIE dependencies for the changing testbench/test partition. Configure together with msie_primary_deps.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_tb-msie_incremental_extra_compile_args"></a>msie_incremental_extra_compile_args |  Xcelium compile/elaboration flags used only while building the MSIE incremental snapshot.   | List of strings | optional | [] |
| <a id="verilog_dv_tb-msie_incremental_extra_runfiles"></a>msie_incremental_extra_runfiles |  Files referenced only by msie_incremental_extra_compile_args.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_tb-msie_primary_deps"></a>msie_primary_deps |  Xcelium MSIE dependencies for the stable primary DUT/netlist partition. Configure together with msie_incremental_deps.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_tb-msie_primary_extra_compile_args"></a>msie_primary_extra_compile_args |  Xcelium compile/elaboration flags used only while building the MSIE primary snapshot.   | List of strings | optional | [] |
| <a id="verilog_dv_tb-msie_primary_extra_runfiles"></a>msie_primary_extra_runfiles |  Files referenced only by msie_primary_extra_compile_args, such as primary SDF command files.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_tb-run_fail_patterns"></a>run_fail_patterns |  Additional regular expressions that identify a failed simulation.   | List of strings | optional | [] |
| <a id="verilog_dv_tb-run_pass_patterns"></a>run_pass_patterns |  Regular expressions that identify a successful simulation. When set, at least one must match.   | List of strings | optional | [] |
| <a id="verilog_dv_tb-shells"></a>shells |  List of shells to use. Each label must be a verilog_rtl_shell instance. Each shell thrown will create two defines:  \<code>define gumi_{module} {module}_shell  \</code>define gumi_use_{module}_shell The shell module declaration must be guarded by the gumi_use_{module}_shell define:  \<code>ifdef gumi_use_{module}_shell     module {module}_shell(/*AUTOARGS*/);       ...     endmodule  \</code>endif   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_tb-simulator"></a>simulator |  Simulator to use for this DV testbench. Supported values are XRUN and VCS. The selected simulator determines which compile/runtime filelists are generated.   | String | optional | `"XRUN"` |
| <a id="verilog_dv_tb-vcs_cm_hier"></a>vcs_cm_hier |  VCS `-cm_hier` coverage configuration file.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |
| <a id="verilog_dv_tb-verilog_config"></a>verilog_config |  Key/value pairs where each key is a Verilog configuration name and each value is the relative path to its configuration `.v` file.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| <a id="verilog_dv_tb-warning_waivers"></a>warning_waivers |  Waive warnings in the compile. By default, simmer promotes all compile warnings to errors. This list is converted to python regular expressions which are imported by simmer to waive warning. Xcelium waivers commonly match '\*W,&lt;ID&gt;'; VCS waivers commonly match 'Warning-\[&lt;ID&gt;\]'.   | List of strings | optional | [] |
| <a id="verilog_dv_tb-xcelium_covfile"></a>xcelium_covfile |  Xcelium coverage configuration file. Replaces the legacy `ccf` attribute.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |


<a id="verilog_dv_test_cfg"></a>

## verilog_dv_test_cfg

<pre>
verilog_dv_test_cfg(<a href="#verilog_dv_test_cfg-name">name</a>, <a href="#verilog_dv_test_cfg-tags">tags</a>, <a href="#verilog_dv_test_cfg-abstract">abstract</a>, <a href="#verilog_dv_test_cfg-inherits">inherits</a>, <a href="#verilog_dv_test_cfg-uvm_testname">uvm_testname</a>, <a href="#verilog_dv_test_cfg-tb">tb</a>, <a href="#verilog_dv_test_cfg-simulator">simulator</a>, <a href="#verilog_dv_test_cfg-sim_opts">sim_opts</a>, <a href="#verilog_dv_test_cfg-no_run">no_run</a>, <a href="#verilog_dv_test_cfg-sockets">sockets</a>, <a href="#verilog_dv_test_cfg-pre_run">pre_run</a>, <a href="#verilog_dv_test_cfg-timeout">timeout</a>, <a href="#verilog_dv_test_cfg-description">description</a>, <a href="#verilog_dv_test_cfg-gls_tb">gls_tb</a>, <a href="#verilog_dv_test_cfg-pre_opts">pre_opts</a>, <a href="#verilog_dv_test_cfg-post_opts">post_opts</a>, <a href="#verilog_dv_test_cfg-gatesim_modes">gatesim_modes</a>)
</pre>

A DV test configuration.

    This is not a executable target. It generates multiple files which may then
    be used by simmer (the wrapping tool to invoke the simulator).
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_dv_test_cfg-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_dv_test_cfg-tags"></a>tags | Bazel tags for the base configuration. Including `gatesim` also generates one configuration per `gatesim_modes` entry. Scheduling tags remain on the base configuration. | List of strings | optional | None |
| <a id="verilog_dv_test_cfg-abstract"></a>abstract |  When True, this configuration is an inheritance-only base and may omit `tb`. Concrete configurations must resolve a testbench directly or through `inherits`.   | Boolean | optional | False |
| <a id="verilog_dv_test_cfg-inherits"></a>inherits |  Inherit configurations from other verilog_dv_test_cfg targets. Entries later in the list will override arguments set by previous inherits entries. Only attributes noted as inheritable in documentation may be inherited. Any field explicitly set in this rule will override values set via inheritance.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_dv_test_cfg-uvm_testname"></a>uvm_testname |  UVM testname eventually passed to simulator via plusarg +UVM_TESTNAME. This attribute is inheritable. See 'inherits' attribute.   | String | optional | "" |
| <a id="verilog_dv_test_cfg-tb"></a>tb |  The testbench to run this test on. This label must be a `verilog_dv_tb` target. It is inheritable and required after inheritance for every concrete configuration.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |
| <a id="verilog_dv_test_cfg-simulator"></a>simulator |  Simulator to use for this test configuration. Supported values are XRUN and VCS. This attribute is inheritable. Concrete configurations default to the associated testbench's simulator, then XRUN, and must match the testbench. An abstract configuration without a testbench may leave it unresolved.   | String | optional | `""` |
| <a id="verilog_dv_test_cfg-sim_opts"></a>sim_opts |  Additional runtime simulation options. The key/value pairs are concatenated; use an empty value for unary options and include `=` at the end of keys that take a value. Inherited dictionaries are merged in order and this configuration overrides matching keys.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| <a id="verilog_dv_test_cfg-no_run"></a>no_run |  Set to True to skip running this test. This flag is not used by bazel but is used as a query filter by simmer.TODO: Deprecate this flag in favor of using built-in tags.   | Boolean | optional | False |
| <a id="verilog_dv_test_cfg-sockets"></a>sockets |  Dictionary mapping of socket_name to socket_command. Simmer has the ability to spawn parallel processes to the primary simulation that are connected via sockets. For each entry in the dictionary, simmer will create a separate process and pass a unique temporary file path to both the simulator and the socket_command. The socket name must match [A-Za-z_][A-Za-z0-9_]* and is passed as "+SOCKET__&lt;socket_name&gt;=&lt;socket_file&gt;" to the simulator. The socket_file is a short, unique path under /tmp created by simmer to stay within Unix-domain socket path limits. The socket_command is a bash command that must contain the literal placeholder "{socket_file}"; other shell braces are preserved. The socket_command will be run from the root of the project tree.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| <a id="verilog_dv_test_cfg-pre_run"></a>pre_run | Bazel target to run immediately before simulation. This attribute is inheritable. | String | optional | None |
| <a id="verilog_dv_test_cfg-timeout"></a>timeout |  Main simulation timeout in minutes, excluding socket and pre-run setup. This option is inheritable. Use -1 to inherit, 0 to disable, or a positive value to set a timeout.   | Integer | optional | -1 |
| <a id="verilog_dv_test_cfg-description"></a>description |  The test simulation scenarios. (e.g. description = """ This is the test description """, )  | String | optional | None |
| <a id="verilog_dv_test_cfg-gls_tb"></a>gls_tb | Base gate-level testbench label. When `gatesim` is tagged, each generated corner appends its mode to this label. If omitted, `tb` is used as the base. | Label | optional | None |
| <a id="verilog_dv_test_cfg-pre_opts"></a>pre_opts | Runtime option overrides merged into `sim_opts` for the base, pre-layout configuration. | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | None |
| <a id="verilog_dv_test_cfg-post_opts"></a>post_opts | Runtime option overrides merged into `sim_opts` for generated gate-simulation corner configurations. | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | None |
| <a id="verilog_dv_test_cfg-gatesim_modes"></a>gatesim_modes | Suffixes used to generate gate-simulation configurations when `tags` includes `gatesim`. | List of strings | optional | `["nl", "sdf_wc", "sdf_lt", "tt_min", "tt_max"]` |


<a id="verilog_dv_unit_test"></a>

## verilog_dv_unit_test

<pre>
verilog_dv_unit_test(<a href="#verilog_dv_unit_test-name">name</a>, <a href="#verilog_dv_unit_test-compile_args">compile_args</a>, <a href="#verilog_dv_unit_test-default_sim_opts">default_sim_opts</a>, <a href="#verilog_dv_unit_test-deps">deps</a>, <a href="#verilog_dv_unit_test-run_args">run_args</a>, <a href="#verilog_dv_unit_test-sim_args">sim_args</a>, <a href="#verilog_dv_unit_test-simulator">simulator</a>, <a href="#verilog_dv_unit_test-ut_sim_template">ut_sim_template</a>)
</pre>

Compiles and runs a small unit test for DV.
    
    This is typically a unit test for a single verilog_dv_library and its dependencies.
    Additional sim options may be passed after '--' in the bazel command.
    Interactive example:
      bazel run //hw/dv/interfaces/apb_pkg:test -- -gui
    For ci testing purposes:
      bazel test //hw/dv/interfaces/apb_pkg:test


**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_dv_unit_test-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_dv_unit_test-compile_args"></a>compile_args |  Additional arguments passed to compilation/elaboration. With VCS, legacy `-define NAME` entries become `+define+NAME`; Xcelium-only debug and wave flags are omitted.   | List of strings | optional | [] |
| <a id="verilog_dv_unit_test-default_sim_opts"></a>default_sim_opts |  Default simulator options to pass to the simulator.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_dv_unit_test_opts.f |
| <a id="verilog_dv_unit_test-deps"></a>deps |  verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on. Dependency ordering within this label list is not necessary if dependencies are consistently declared in all other rules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| <a id="verilog_dv_unit_test-run_args"></a>run_args |  Additional arguments passed only to simulation runtime.   | List of strings | optional | [] |
| <a id="verilog_dv_unit_test-sim_args"></a>sim_args |  Deprecated compile arguments. Use `compile_args` and `run_args` instead. With VCS, legacy `-define NAME` entries become `+define+NAME`; Xcelium-only debug and wave flags are omitted.   | List of strings | optional | [] |
| <a id="verilog_dv_unit_test-simulator"></a>simulator |  Simulator to use for this one-step unit test. When omitted, `verilog_unit_test_simulator` selects XRUN or VCS.   | String | optional | `""` |
| <a id="verilog_dv_unit_test-ut_sim_template"></a>ut_sim_template |  The template to generate the bash script to run the simulation. Custom templates selected with VCS must implement the VCS compile-then-`simv` flow. Existing placeholders including `FLISTS`, `SIM_ARGS`, `COMPILE_ARGS`, and `RUN_ARGS` are available for both simulators.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_dv_unit_test.sh.template |


<a id="verilog_rtl_cdc_test"></a>

## verilog_rtl_cdc_test

<pre>
verilog_rtl_cdc_test(<a href="#verilog_rtl_cdc_test-name">name</a>, <a href="#verilog_rtl_cdc_test-bash_template">bash_template</a>, <a href="#verilog_rtl_cdc_test-bbox_array_size">bbox_array_size</a>, <a href="#verilog_rtl_cdc_test-bbox_modules">bbox_modules</a>, <a href="#verilog_rtl_cdc_test-cmd_files">cmd_files</a>, <a href="#verilog_rtl_cdc_test-defines">defines</a>, <a href="#verilog_rtl_cdc_test-deps">deps</a>,
                     <a href="#verilog_rtl_cdc_test-epilogue_template">epilogue_template</a>, <a href="#verilog_rtl_cdc_test-preamble_template">preamble_template</a>, <a href="#verilog_rtl_cdc_test-shells">shells</a>, <a href="#verilog_rtl_cdc_test-top">top</a>)
</pre>

Run Jaspergold CDC on a verilog_rtl_library.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_rtl_cdc_test-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_rtl_cdc_test-bash_template"></a>bash_template |  The template for the generated bash script which will run the case.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | //vendors/cadence:verilog_rtl_cdc_test.sh.template |
| <a id="verilog_rtl_cdc_test-bbox_array_size"></a>bbox_array_size |  Black box any RTL array greater than the specified size. If the value of this attribute is 0, the CDC tool will use the default size   | Integer | optional | 0 |
| <a id="verilog_rtl_cdc_test-bbox_modules"></a>bbox_modules |  List of modules to black box   | List of strings | optional | [] |
| <a id="verilog_rtl_cdc_test-cmd_files"></a>cmd_files |  A list of tcl files containing commands to run. Multiple files are allowed to facilitate separating common project commands and block-specific commands.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| <a id="verilog_rtl_cdc_test-defines"></a>defines |  List of additional \<code>defines for this cdc run. LINT and CDC are always defined If a define is only for control and has no value, e.g. \</code>define USE_AXI, the dictionary entry key should be "USE_AXI" and the value should be the empty string. If a define needs a value, e.g. \<code>define WIDTH 8, the dictionary value must start with '=', e.g. '=8'   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| <a id="verilog_rtl_cdc_test-deps"></a>deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| <a id="verilog_rtl_cdc_test-epilogue_template"></a>epilogue_template |  The template to generate the final reporting commands for this cdc test.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_rtl_cdc_epilogue_cmds.tcl.template |
| <a id="verilog_rtl_cdc_test-preamble_template"></a>preamble_template |  The template to generate the initial commands (the preamble) for this cdc test.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_rtl_cdc_preamble_cmds.tcl.template |
| <a id="verilog_rtl_cdc_test-shells"></a>shells |  List of verilog_rtl_shell Labels. For each Label, a gumi define will be placed on the command line to use this shell instead of the original module. This requires that the original module was instantiated using \<code>gumi_&lt;module_name&gt; instead of just &lt;module_name&gt;.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_cdc_test-top"></a>top |  The name of the top-level module for this cdc run   | String | required |  |


<a id="verilog_rtl_library"></a>

## verilog_rtl_library

<pre>
verilog_rtl_library(<a href="#verilog_rtl_library-name">name</a>, <a href="#verilog_rtl_library-deps">deps</a>, <a href="#verilog_rtl_library-direct">direct</a>, <a href="#verilog_rtl_library-enable_gumi">enable_gumi</a>, <a href="#verilog_rtl_library-gumi_file_override">gumi_file_override</a>, <a href="#verilog_rtl_library-gumi_override">gumi_override</a>, <a href="#verilog_rtl_library-headers">headers</a>,
                    <a href="#verilog_rtl_library-is_pkg">is_pkg</a>, <a href="#verilog_rtl_library-is_shell_of">is_shell_of</a>, <a href="#verilog_rtl_library-lib_files">lib_files</a>, <a href="#verilog_rtl_library-makelib">makelib</a>, <a href="#verilog_rtl_library-modules">modules</a>, <a href="#verilog_rtl_library-no_synth">no_synth</a>)
</pre>

A collection of RTL design files. Creates a generated flist file to be included later in a compile.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_rtl_library-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_rtl_library-deps"></a>deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_library-direct"></a>direct |  Verilog files that must be put directly onto the command line. 'modules' should be used instead of 'direct' wherever possible   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_library-enable_gumi"></a>enable_gumi |  When set and `gumi_file_override` is absent, create an additional file containing default preprocessor values for the gumi system.   | Boolean | optional | True |
| <a id="verilog_rtl_library-gumi_file_override"></a>gumi_file_override |  Use the supplied Label or file as the GUMI definitions file instead of generating one. The override remains part of the library's transitive sources and runfiles.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |
| <a id="verilog_rtl_library-gumi_override"></a>gumi_override |  A list of strings of module names to create gumi defines. If empty (default), the modules variable is used instead. Useful when using 'direct' or 'lib_files' or to limit the defines created when using a glob in 'modules'   | List of strings | optional | [] |
| <a id="verilog_rtl_library-headers"></a>headers |  Files that will be included into other files. A '+incdir' flag will be added for each source file's directory.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_library-is_pkg"></a>is_pkg |  INTERNAL: Do not set in verilog_rtl_library instances. Used for internal bookkeeping for macros derived from verilog_rtl_library. Used to enforce naming conventions related to packages to encourage simple dependency graphs   | Boolean | optional | False |
| <a id="verilog_rtl_library-is_shell_of"></a>is_shell_of |  INTERNAL: Do not set in verilog_rtl_library instances. Used for internal bookkeeping for macros derived from verilog_rtl_library. If set, this library is represents a 'shell' of another module. Allows downstream test rules to specify this Label as a 'shell' to override another instance via the gumi system.   | String | optional | "" |
| <a id="verilog_rtl_library-lib_files"></a>lib_files |  Verilog library files containing multiple modules. A '-v' flag will be added for each file in this attribute. It is preferable to used the 'modules' attribute when possible because library files require parsing entire files to discover all modules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_library-makelib"></a>makelib |  Compile this target into the named Xcelium library through `-makelib`/`-endlib`. VCS receives the same ordered sources through a separate `-file` boundary; VCS recompilation isolation is provided by `-Mupdate` and Partition Compile rather than Xcelium library syntax.   | String | optional | `""` |
| <a id="verilog_rtl_library-modules"></a>modules |  Verilog files containing a single module where the module name matches the file name. A '-y' flag will be added for each source file's directory. This is the preferred mechanism for specifying RTL modules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_library-no_synth"></a>no_synth |  Compatibility marker for downstream synthesis aspects or consumers. Simulation targets continue to include this library.   | Boolean | optional | False |


<a id="verilog_rtl_lint_test"></a>

## verilog_rtl_lint_test

<pre>
verilog_rtl_lint_test(<a href="#verilog_rtl_lint_test-name">name</a>, <a href="#verilog_rtl_lint_test-command_template">command_template</a>, <a href="#verilog_rtl_lint_test-defines">defines</a>, <a href="#verilog_rtl_lint_test-deps">deps</a>, <a href="#verilog_rtl_lint_test-design_info">design_info</a>, <a href="#verilog_rtl_lint_test-lint_parser">lint_parser</a>, <a href="#verilog_rtl_lint_test-rulefile">rulefile</a>,
                      <a href="#verilog_rtl_lint_test-run_template">run_template</a>, <a href="#verilog_rtl_lint_test-shells">shells</a>, <a href="#verilog_rtl_lint_test-simulator">simulator</a>, <a href="#verilog_rtl_lint_test-top">top</a>, <a href="#verilog_rtl_lint_test-waiver_direct">waiver_direct</a>)
</pre>

Compile and run lint on target

    This rule was originally written for Cadence HAL to be run under xcelium. As such, it
    is not entirely generic. It also uses a log post-processor
    (passed in by the lint_parser attribute) to allow for easier waiving of warnings.

    When `simulator = "VCS"`, the rule automatically switches to built-in
    Synopsys defaults for the launcher, lint command file, parser, and default
    rulefile. Projects may still override these assets if they need a more
    opinionated local policy.

    The DUT must have no unwaived warning/errors in order for this rule to
    pass. The intended philosophy is for blocks to maintain a clean lint status
    throughout the lifecycle of the project, not to run lint as a checklist
    item towards the end of the project.

    There are several attributes in this rule that must be kept in sync.
    run_template, rulefile, lint_parser, and command_template must use the associated
    files for each vendor. The default values auto-select between the built-in
    Cadence and Synopsys sets based on the simulator attribute. If an instance
    overrides any of these vendor-specific values, it should override the full set.

    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_rtl_lint_test-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_rtl_lint_test-command_template"></a>command_template |  The template to generate the command script for this lint test. The command templates are located at @rules_verilog//vendors/&lt;vendor name&gt;/verilog_rtl_lint_cmds.tcl.template   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_rtl_lint_cmds.tcl.template |
| <a id="verilog_rtl_lint_test-defines"></a>defines |  List of additional \<code>defines for this lint run. LINT is always defined by default If a define is only for control and has no value, e.g. \</code>define USE_AXI, the dictionary entry key should be "USE_AXI" and the value should be the empty string. If a define needs a value, e.g. \<code>define WIDTH 8, the dictionary value must start with '=', e.g. '=8'   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| <a id="verilog_rtl_lint_test-deps"></a>deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| <a id="verilog_rtl_lint_test-design_info"></a>design_info |  A Cadence design_info file to add additional lint rule/waivers   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_lint_test-lint_parser"></a>lint_parser |  Post processor for lint logs allowing for easier waiving of warnings. Parsers for HAL, Ascent, and VCS are included in rules_verilog release at `@rules_verilog//bin:lint_parser_(hal|ascent|vcs)`. When left at the default HAL label and `simulator = "VCS"`, the rule automatically switches to the built-in VCS parser.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//bin:lint_parser_hal |
| <a id="verilog_rtl_lint_test-rulefile"></a>rulefile |  The rules configuration file for this lint run. Each project may write its own tool-specific rulefile. When omitted and `simulator = "VCS"`, rules_verilog uses a built-in Synopsys default lint opts file. When `simulator = "XRUN"`, a project-specific Cadence/HAL rulefile is still required. Example HAL rulefile: https://github.com/freecores/t6507lp/blob/ca7d7ea779082900699310db459a544133fe258a/lint/run/hal.def   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional |  |
| <a id="verilog_rtl_lint_test-run_template"></a>run_template |  The template to generate the script to run the lint test. The command templates are located at @rules_verilog//vendors/&lt;vendor name&gt;/verilog_rtl_lint_test.tcl.template   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_rtl_lint_test.sh.template |
| <a id="verilog_rtl_lint_test-shells"></a>shells |  List of verilog_rtl_shell Labels. For each Label, a gumi define will be placed on the command line to use this shell instead of the original module. This requires that the original module was instantiated using \<code>gumi_&lt;module_name&gt; instead of just &lt;module_name&gt;.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_lint_test-simulator"></a>simulator |  Simulator launcher to use for this lint test. When omitted, `verilog_unit_test_simulator` selects XRUN or VCS. XRUN uses the built-in Cadence defaults. VCS automatically switches to the built-in Synopsys launcher, lint command file, parser, and default rulefile.   | String | optional | `""` |
| <a id="verilog_rtl_lint_test-top"></a>top |  The name of the top-level module for this lint run   | String | required |  |
| <a id="verilog_rtl_lint_test-waiver_direct"></a>waiver_direct |  Lint waiver python regex to apply directly to a lint message. This is sometimes needed to work around cases when HAL has formatting errors in xrun.log.xml that cause problems for the lint parser   | String | optional | "" |


<a id="verilog_rtl_unit_test"></a>

## verilog_rtl_unit_test

<pre>
verilog_rtl_unit_test(<a href="#verilog_rtl_unit_test-name">name</a>, <a href="#verilog_rtl_unit_test-command_override">command_override</a>, <a href="#verilog_rtl_unit_test-data">data</a>, <a href="#verilog_rtl_unit_test-deps">deps</a>, <a href="#verilog_rtl_unit_test-post_flist_args">post_flist_args</a>, <a href="#verilog_rtl_unit_test-pre_flist_args">pre_flist_args</a>, <a href="#verilog_rtl_unit_test-run_args">run_args</a>, <a href="#verilog_rtl_unit_test-shells">shells</a>,
                      <a href="#verilog_rtl_unit_test-simulator">simulator</a>, <a href="#verilog_rtl_unit_test-ut_sim_template">ut_sim_template</a>, <a href="#verilog_rtl_unit_test-ut_sim_waves_template">ut_sim_waves_template</a>, <a href="#verilog_rtl_unit_test-wave_viewer_command">wave_viewer_command</a>)
</pre>

Compile and simulate a verilog_rtl_library.

    Allows a designer to write small unit/directed tests which can be included in regression.

    This rule is capable of running SVUnit regressions as well. See ut_sim_template attribute.

    This unit test can either immediately launch a waveform viewer, or it can render a waveform database which can be loaded separately.
    To launch the waveform viewer after the test completes, run the following: 'bazel run <target> -- --launch &'.
    To render a database without launching a viewer, run the following: 'bazel run <target> -- --waves'.
    Any other unknown options will be passed directly to the simulator, for example: 'bazel run <target> -- --waves +my_arg=4'.

    Typically, an additional verilog_rtl_library containing 'unit_test_top.sv'
    is created. This unit_test_top will be dependent on the DUT top, and will
    be the only entry in the `deps` attribute list provided to verilog_rtl_unit_test.
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_rtl_unit_test-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_rtl_unit_test-command_override"></a>command_override |  Allows custom override of simulator command in the event of wrapping via modulefiles. Example override in project's .bazelrc:   build --@rules_verilog//:verilog_rtl_unit_test_command="runmod -t xrun --"   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//:verilog_rtl_unit_test_command |
| <a id="verilog_rtl_unit_test-data"></a>data |  Non-verilog dependencies. Useful when reading in data files as stimulus/prediction.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_unit_test-deps"></a>deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| <a id="verilog_rtl_unit_test-post_flist_args"></a>post_flist_args |  Additional command line arguments to be placed after the flist arguments. See ut_sim_template attribute for exact layout. With VCS, legacy `-define NAME` entries become `+define+NAME`; Xcelium-only debug and wave flags are omitted, and non-compiler plusargs are passed to `simv`.   | List of strings | optional | [] |
| <a id="verilog_rtl_unit_test-pre_flist_args"></a>pre_flist_args |  Additional command line arguments to be placed after the simulator binary but before the flist arguments. See ut_sim_template attribute for exact layout. For defines to have effect, they must be declared in pre_flist_args, not post_flist_args. With VCS, legacy `-define NAME` entries become `+define+NAME`; Xcelium-only debug and wave flags are omitted, and non-compiler plusargs are passed to `simv`.   | List of strings | optional | [] |
| <a id="verilog_rtl_unit_test-run_args"></a>run_args |  Additional arguments passed only to simulation runtime. With VCS, legacy runtime plusargs in `pre_flist_args` or `post_flist_args` are also passed to `simv`.   | List of strings | optional | [] |
| <a id="verilog_rtl_unit_test-shells"></a>shells |  List of verilog_rtl_shell Labels. For each Label, a gumi define will be placed on the command line to use this shell instead of the original module. This requires that the original module was instantiated using \<code>gumi_&lt;module_name&gt; instead of just &lt;module_name&gt;.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_rtl_unit_test-simulator"></a>simulator |  Simulator to use for this one-step RTL unit test. When omitted, `verilog_unit_test_simulator` selects XRUN or VCS. VCS one-step wave dumping is currently disabled.   | String | optional | `""` |
| <a id="verilog_rtl_unit_test-ut_sim_template"></a>ut_sim_template |  The template to generate the script to run the test. Also available is an Xcelium-only [SVUnit](http://agilesoc.com/open-source-projects/svunit/) template: @rules_verilog//vendors/cadence:verilog_rtl_unit_test_svunit.sh.template. Targets using it must set `simulator = "XRUN"` unless they provide a VCS-compatible custom template. If using the SVUnit template, you may also want to throw: <pre><code>    post_flist_args = [     "--directory &lt;path_to_test_directory_from_workspace&gt;",  ],</code></pre>   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_rtl_unit_test.sh.template |
| <a id="verilog_rtl_unit_test-ut_sim_waves_template"></a>ut_sim_waves_template |  The template to generate the waves command script to run in the test. When using the SVUnit ut_sim_template or a custom SVUnit invocation, the default verilog_rtl_unit_test_waves.tcl.template will not work. You must either write your own waves script or use the SVUnit waves template: @rules_verilog//vendors/cadence:verilog_rtl_unit_test_svunit_waves.tcl.template.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//vendors/cadence:verilog_rtl_unit_test_waves.tcl.template |
| <a id="verilog_rtl_unit_test-wave_viewer_command"></a>wave_viewer_command |  Allows custom override of waveform viewer command in the event of wrapping via modulefiles. Example override in project's .bazelrc:   build --@rules_verilog//:verilog_rtl_wave_viewer_command="runmod xrun --"   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @rules_verilog//:verilog_rtl_wave_viewer_command |


<a id="verilog_test"></a>

## verilog_test

<pre>
verilog_test(<a href="#verilog_test-name">name</a>, <a href="#verilog_test-data">data</a>, <a href="#verilog_test-deps">deps</a>, <a href="#verilog_test-post_flist_args">post_flist_args</a>, <a href="#verilog_test-pre_flist_args">pre_flist_args</a>, <a href="#verilog_test-shells">shells</a>, <a href="#verilog_test-tool">tool</a>)
</pre>

Provides a way to run a test against a set of libs.

**ATTRIBUTES**

| Name | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_test-name"></a>name | A unique name for this target. | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required | |
| <a id="verilog_test-data"></a>data | Non-verilog dependencies | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_test-deps"></a>deps | Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider. | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required | |
| <a id="verilog_test-post_flist_args"></a>post_flist_args | Commands and arguments after flist arguments | List of strings | optional | [] |
| <a id="verilog_test-pre_flist_args"></a>pre_flist_args | Commands and arguments before flist arguments | List of strings | optional | [] |
| <a id="verilog_test-shells"></a>shells | List of verilog_rtl_shell Labels. For each Label, a gumi define will be placed on the command line to use this shell instead of the original module. This requires that the original module was instantiated using \<code>gumi_&lt;module_name&gt; instead of just &lt;module_name&gt;. | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| <a id="verilog_test-tool"></a>tool | Label to a single executable tool to run. The executable and its default runfiles are available to the generated runner. Inserted before pre_flist_args if set. Do not duplicate in pre_flist_args. | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |


<a id="verilog_tool_encapsulation"></a>

## verilog_tool_encapsulation

<pre>
verilog_tool_encapsulation(<a href="#verilog_tool_encapsulation-name">name</a>, <a href="#verilog_tool_encapsulation-build_setting_default">build_setting_default</a>)
</pre>



**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="verilog_tool_encapsulation-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| <a id="verilog_tool_encapsulation-build_setting_default"></a>build_setting_default | Initial command value used when the build setting is not overridden. | String | required |  |


<a id="verilog_rtl_pkg"></a>

## verilog_rtl_pkg

<pre>
verilog_rtl_pkg(<a href="#verilog_rtl_pkg-name">name</a>, <a href="#verilog_rtl_pkg-direct">direct</a>, <a href="#verilog_rtl_pkg-no_synth">no_synth</a>, <a href="#verilog_rtl_pkg-deps">deps</a>, <a href="#verilog_rtl_pkg-visibility">visibility</a>)
</pre>

A single Systemverilog package.

This rule is a specialized case of verilog_rtl_library. Systemverilog
packages should be placed into their own rule instance to limit cross
dependencies. In general, a block may depend on another block's package but
should not need to depend on all the modules in the block.


**PARAMETERS**


| Name  | Description | Default Value |
| :------------- | :------------- | :------------- |
| <a id="verilog_rtl_pkg-name"></a>name |  A unique name for this target.   |  none |
| <a id="verilog_rtl_pkg-direct"></a>direct |  The Systemverilog file containing the package.<br><br>See verilog_rtl_library::direct.   |  none |
| <a id="verilog_rtl_pkg-no_synth"></a>no_synth |  Compatibility marker for downstream synthesis aspects or consumers. Simulation targets continue to include this package.   |  <code>False</code> |
| <a id="verilog_rtl_pkg-deps"></a>deps |  Other packages this target is dependent on.<br><br>See verilog_rtl_library::deps.   |  <code>[]</code> |
| <a id="verilog_rtl_pkg-visibility"></a>visibility |  Bazel target visibility.   |  <code>None</code> |


<a id="verilog_rtl_shell"></a>

## verilog_rtl_shell

<pre>
verilog_rtl_shell(<a href="#verilog_rtl_shell-name">name</a>, <a href="#verilog_rtl_shell-module_to_shell_name">module_to_shell_name</a>, <a href="#verilog_rtl_shell-shell_module_label">shell_module_label</a>, <a href="#verilog_rtl_shell-deps">deps</a>, <a href="#verilog_rtl_shell-visibility">visibility</a>)
</pre>

An RTL shell has the same ports as another module.

This rule is a specialized case of verilog_rtl_library.
A 'shell' is similar to a 'stub' (empty module), but a shell may contain
limited functionality. Frequent uses include:
  * Blackboxing hierarchy that will not be the target of testing
  * Replacing functionality with a simpler model (e.g. simulation-only memory models)


**PARAMETERS**


| Name  | Description | Default Value |
| :------------- | :------------- | :------------- |
| <a id="verilog_rtl_shell-name"></a>name |  A unique name for this target.   |  none |
| <a id="verilog_rtl_shell-module_to_shell_name"></a>module_to_shell_name |  The name of the module that will be replaced.<br><br>When a downstream test uses this 'shell', a gumi define will be created using this name.<br><br>When a shell needs to be hand-edited after generation If module_to_shell_name == 'custom', then all rules regarding shells are ignored and gumi shell defines are not thrown, allowing the user great power.   |  none |
| <a id="verilog_rtl_shell-shell_module_label"></a>shell_module_label |  The Label or file containing the shell. The shell is selected explicitly by simulation consumers.   |  none |
| <a id="verilog_rtl_shell-deps"></a>deps |  Other packages this target is dependent on.<br><br>In general. shells should avoid having dependencies. Exceptions include necessary packages and possible a DV model to implement functional behavior.<br><br>See verilog_rtl_library::deps.   |  <code>[]</code> |
| <a id="verilog_rtl_shell-visibility"></a>visibility | Bazel target visibility forwarded to the generated `verilog_rtl_library`. | <code>None</code> |
