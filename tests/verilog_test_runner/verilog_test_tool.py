import sys
from pathlib import Path


def main():
    data = Path(__file__).with_name("verilog_test_tool.data")
    if data.read_text(encoding="utf-8").strip() != "tool runfile is present":
        raise RuntimeError("verilog_test tool data runfile is unavailable")
    if not Path(__file__).with_name("target_config.data").is_file():
        raise RuntimeError("verilog_test tool was not built in the runtime target configuration")

    expected = [
        "--pre-flist",
        "-f",
        "tests/verilog_test_runner/verilog_test_library.f",
        "tests/verilog_test_runner/verilog_test_top.sv",
        "--post-flist",
    ]
    if sys.argv[1:] != expected:
        raise RuntimeError("unexpected verilog_test arguments: {!r}".format(sys.argv[1:]))


if __name__ == "__main__":
    main()
