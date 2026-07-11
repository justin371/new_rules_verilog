import shlex
import tempfile
import unittest
from types import SimpleNamespace

from lib.runtime_options import append_uvm_control_options, format_log_check_args


def _options(**overrides):
    values = {
        "sim_opts_file": None,
        "uvm_config_db_trace": False,
        "uvm_max_quit_count": 0,
        "uvm_resource_db_trace": False,
        "uvm_set_config_int": None,
        "uvm_set_config_string": None,
        "uvm_set_int": None,
        "uvm_set_str": None,
        "uvm_set_verbosity": None,
        "verbosity": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RuntimeOptionsTest(unittest.TestCase):

    def test_uvm_controls_override_verbosity_and_preserve_file_quoting(self):
        with tempfile.NamedTemporaryFile(mode="w") as options_file:
            options_file.write('+LABEL="value with spaces" # ignored\n')
            options_file.flush()
            options = _options(
                sim_opts_file=options_file.name,
                uvm_config_db_trace=True,
                uvm_set_int=["env.limit,5"],
                verbosity="UVM_HIGH",
            )

            result = shlex.split(append_uvm_control_options(" +UVM_VERBOSITY=UVM_LOW", options))

        self.assertIn("+UVM_VERBOSITY=UVM_HIGH", result)
        self.assertIn("+uvm_set_config_int=env.limit,5", result)
        self.assertIn("+LABEL=value with spaces", result)
        self.assertIn("+UVM_CONFIG_DB_TRACE", result)

    def test_log_checker_patterns_are_shell_escaped(self):
        runtime_options = {
            "run_pass_patterns": ["PROJECT PASS$"],
            "run_fail_patterns": ["PROJECT FAIL; rm -rf /"],
        }

        self.assertEqual([
            "--pass-pattern",
            "PROJECT PASS$",
            "--fail-pattern",
            "PROJECT FAIL; rm -rf /",
        ], shlex.split(format_log_check_args(runtime_options)))


if __name__ == "__main__":
    unittest.main()
