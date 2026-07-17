"""Helpers for the shared DV test runtime-options contract."""

import re
import shlex

RUNTIME_OPTIONS_SCHEMA_VERSION = 1
_UVM_VERBOSITY_RE = re.compile(r"(?<!\S)\+UVM_VERBOSITY=[A-Z_]+")


def normalize_test_runtime_options(runtime_options):
    """Return a normalized runtime-options dictionary for simmer.

    This contract is emitted by verilog_dv_test_cfg dynamic_args files and
    consumed by simmer. Keep it small and focused on per-test runtime behavior.
    """
    if runtime_options is None:
        runtime_options = {}
    if not isinstance(runtime_options, dict):
        raise TypeError("runtime_options must be a dict")

    timeout_minutes = runtime_options.get("timeout_minutes", runtime_options.get("timeout"))
    if timeout_minutes in ("", None):
        timeout_minutes = None

    pre_run = runtime_options.get("pre_run")
    if pre_run is None:
        pre_run = ""

    normalized = {
        "schema_version": runtime_options.get("schema_version", RUNTIME_OPTIONS_SCHEMA_VERSION),
        "simulator": runtime_options.get("simulator", "XRUN").upper(),
        "uvm_testname": runtime_options.get("uvm_testname"),
        "sim_opts": dict(runtime_options.get("sim_opts", {})),
        "timeout_minutes": timeout_minutes,
        # Keep the historical key for compatibility with older code paths.
        "timeout": timeout_minutes,
        "sockets": dict(runtime_options.get("sockets", {})),
        "tags": list(runtime_options.get("tags", [])),
        "pre_run": pre_run,
        "run_pass_patterns": list(runtime_options.get("run_pass_patterns", [])),
        "run_fail_patterns": list(runtime_options.get("run_fail_patterns", [])),
    }
    return normalized


def cli_sim_opts_to_dict(cli_sim_opts):
    """Normalize CLI --sim-opts into the same dict shape as verilog_dv_test_cfg."""
    if not cli_sim_opts:
        return {}

    normalized = {}
    for sim_opt in cli_sim_opts:
        parts = sim_opt.split("=", maxsplit=1)
        if len(parts) == 1:
            key = parts[0]
            value = ""
        elif len(parts) == 2:
            key = parts[0] + "="
            value = parts[1]
        else:
            raise ValueError("Unexpected split while parsing sim opt: {}".format(sim_opt))
        normalized[key] = value
    return normalized


def merge_test_runtime_sim_opts(runtime_options, cli_sim_opts):
    """Merge Bazel test-cfg sim_opts with CLI sim opts, giving CLI precedence."""
    normalized_runtime_options = normalize_test_runtime_options(runtime_options)
    merged = dict(normalized_runtime_options["sim_opts"])
    merged.update(cli_sim_opts_to_dict(cli_sim_opts))
    return merged


def format_sim_opts_dict(sim_opts):
    """Format a normalized sim_opts dict into simulator command-line fragments."""
    return shlex.join("{}{}".format(key, value) for key, value in sim_opts.items())


def format_log_check_args(runtime_options):
    """Return checker CLI arguments from the normalized test contract."""
    normalized = normalize_test_runtime_options(runtime_options)
    args = []
    for pattern in normalized["run_pass_patterns"]:
        args.extend(["--pass-pattern", pattern])
    for pattern in normalized["run_fail_patterns"]:
        args.extend(["--fail-pattern", pattern])
    return shlex.join(args)


def append_uvm_control_options(sim_opts, options):
    """Append simulator-independent UVM controls to an option string."""
    if options.uvm_set_int:
        sim_opts += " " + shlex.join(["+uvm_set_config_int={}".format(value) for value in options.uvm_set_int])
    if options.uvm_set_str:
        sim_opts += " " + shlex.join(["+uvm_set_config_string={}".format(value) for value in options.uvm_set_str])
    if options.sim_opts_file:
        with open(options.sim_opts_file, "r", encoding="utf-8") as filep:
            for line in filep:
                sim_opts += " " + shlex.join(shlex.split(line, comments=True))

    if options.verbosity:
        if _UVM_VERBOSITY_RE.search(sim_opts):
            sim_opts = _UVM_VERBOSITY_RE.sub("+UVM_VERBOSITY=" + options.verbosity, sim_opts)
        else:
            sim_opts += " +UVM_VERBOSITY=" + options.verbosity
            if options.verbosity == "UVM_DEBUG":
                sim_opts += " +UVM_TR_RECORD +UVM_LOG_RECORD "
    elif not _UVM_VERBOSITY_RE.search(sim_opts):
        sim_opts += " +UVM_VERBOSITY=UVM_MEDIUM"

    if options.uvm_config_db_trace:
        sim_opts += " +UVM_CONFIG_DB_TRACE"
    if options.uvm_resource_db_trace:
        sim_opts += " +UVM_RESOURCE_DB_TRACE"
    if options.uvm_max_quit_count:
        sim_opts += " +UVM_MAX_QUIT_COUNT={}".format(options.uvm_max_quit_count)
    if options.uvm_set_verbosity:
        sim_opts += " " + shlex.join(["+uvm_set_verbosity={}".format(value) for value in options.uvm_set_verbosity])
    if options.uvm_set_config_int:
        sim_opts += " " + shlex.join(["+uvm_set_config_int={}".format(value) for value in options.uvm_set_config_int])
    if options.uvm_set_config_string:
        sim_opts += " " + shlex.join(
            ["+uvm_set_config_string={}".format(value) for value in options.uvm_set_config_string])
    return sim_opts


def resolve_test_timeout_hours(runtime_options, default_timeout_hours, cli_timeout_was_explicit):
    """Resolve the effective per-test timeout in hours.

    CLI --timeout is authoritative when explicitly requested. Otherwise honor the
    verilog_dv_test_cfg timeout (stored in minutes) when present.
    """
    if cli_timeout_was_explicit:
        return default_timeout_hours

    normalized_runtime_options = normalize_test_runtime_options(runtime_options)
    timeout_minutes = normalized_runtime_options.get("timeout_minutes")
    if timeout_minutes is None or timeout_minutes < 0:
        return default_timeout_hours
    return float(timeout_minutes) / 60.0
