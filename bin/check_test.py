#!/usr/bin/env python

import argparse
import mmap
import os
import platform
import re
import sys
from collections import deque

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Error signatures from log files
# Note: These are treated as Regex patterns.
default_error_signatures = [
    r'%E-',
    r'%F-',
    r'%W-',
    r'#E',
    r"\*ERROR\*",
    r"\*FAILED\*",
    r"SVA_CHECKER_ERROR",
    r"Assertion FAILURE",
    r"Solver failed",
    r"VIRL_MEM_ERR",
    r"Warning-.FCIBR",
    r"Warning-.FCPSBU",
    r"Warning-.STASKW_CO",
    r"Warning-.SVART-NAFRLTS",
    r"Warning-.FCIELIE",
    r"Warning:.*AxiPC.sv",
    r"Error!!",
    r"Error:",
    r"ERROR..FAILURE",
    r"FATAL..FAILURE",
    r"Error-",
    r"UVM_ERROR [@/]",
    r"UVM_FATAL [@/]",
    r"UVM_ERROR .*[@/]",
    r"UVM_FATAL .*[@/]",
    r"WARNING.FAILURE",
    r" \*E,",
    r" \*F,",
    r"VIRL_MEM_WARNING",
    r": Assertion .* failed\.",
    r"UVM_WARNING .*uvm_reg_map.*RegModel.*In map .*overlaps with address of existing register",
    r"UVM_WARNING .*uvm_reg_map.*RegModel.*In map .*overlaps with address range of memory",
    r"UVM_WARNING .*uvm_reg_map.*RegModel.*In map .*overlaps existing memory with range",
    r"UVM_WARNING .*uvm_reg_map.*RegModel.*In map .*maps to same address as register",
    r"UVM_WARNING .*uvm_reg_map.*RegModel.*In map .*maps to same address as memory",
    r"\*W,RMEMNOF",
    r"\*W,ASRTST .*has failed",
    r"ERROR:",
]

# Signatures indicating a successful test completion
finish_signatures = [
    r"#I Final Report", r"finish at simulation time", r"Simulation complete via", r"--- UVM Report Summary ---"
]

# Compile static regexes once
# Using non-capturing groups (?:) is slightly faster than capturing groups
finish_regex = re.compile(r"(?:" + ")|(?:".join(finish_signatures) + r")")
enable_regex = re.compile(r".*TEST_CHECK_ENABLE: (.*)")
disable_regex = re.compile(r".*TEST_CHECK_DISABLE: (.*)")

# Global error regex placeholder
err_regex = None
active_signatures = list(default_error_signatures)


def compile_error_regex():
    """Compiles the list of error signatures into a single regex object."""
    global err_regex
    if not active_signatures:
        # Match nothing if list is empty
        err_regex = re.compile(r"(?!x)x")
    else:
        # Use non-capturing groups for performance
        pattern = r"(?:" + ")|(?:".join(active_signatures) + r")"
        err_regex = re.compile(pattern)


def update_signatures(line):
    """
    Parses line for Enable/Disable commands.
    Returns True if signatures were updated.
    """
    # Fast string check before running regex
    if "TEST_CHECK_ENABLE" in line:
        match = enable_regex.match(line)
        if match:
            new_sig = match.group(1)
            if new_sig not in active_signatures:
                active_signatures.append(new_sig)
                compile_error_regex()
                return True

    elif "TEST_CHECK_DISABLE" in line:
        match = disable_regex.match(line)
        if match:
            rem_sig = match.group(1)
            if rem_sig in active_signatures:
                active_signatures.remove(rem_sig)
                compile_error_regex()
                return True

    return False


def get_file_tail(filepath, n_lines=25):
    """Returns the last n_lines of a file using a deque."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return deque(f, n_lines)
    except Exception:
        return []


def scan_static_log(filepath, error_limit):
    """Scan logs without dynamic signature directives using mmap."""

    def decode_line(line):
        return line.decode('utf-8', errors='replace').replace('\r\n', '\n')

    def find_lines(data, markers, required_marker=None):
        line_starts = set()
        for marker in markers:
            offset = 0
            while True:
                match_start = data.find(marker, offset)
                if match_start == -1:
                    break
                line_start = data.rfind(b'\n', 0, match_start) + 1
                line_end = data.find(b'\n', match_start)
                line_end = len(data) if line_end == -1 else line_end + 1
                if required_marker is None or required_marker in data[line_start:line_end]:
                    line_starts.add(line_start)
                offset = match_start + len(marker)
        lines = []
        for line_start in sorted(line_starts):
            line_end = data.find(b'\n', line_start)
            line_end = len(data) if line_end == -1 else line_end + 1
            lines.append(decode_line(data[line_start:line_end]))
        return lines

    with open(filepath, 'rb') as log_file:
        if os.path.getsize(filepath) == 0:
            return [], [], [], False
        with mmap.mmap(log_file.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if data.find(b"TEST_CHECK_") != -1:
                return None

            error_lines = []
            seen_line_starts = set()
            byte_error_regex = re.compile(err_regex.pattern.encode('utf-8'))
            for match in byte_error_regex.finditer(data):
                line_start = data.rfind(b'\n', 0, match.start()) + 1
                if line_start in seen_line_starts:
                    continue
                line_end = data.find(b'\n', match.end())
                line_end = len(data) if line_end == -1 else line_end + 1
                error_lines.append(decode_line(data[line_start:line_end]))
                seen_line_starts.add(line_start)
                if len(error_lines) >= error_limit:
                    break
            seed_lines = find_lines(data, [b"SVSEED", b"random seed used"])
            run_time_lines = find_lines(data, [b"real\t"], required_marker=b"user\t")
            found_finish = any(data.find(signature.encode('utf-8')) != -1 for signature in finish_signatures)
            return error_lines, seed_lines, run_time_lines, found_finish


def main():
    # 1. Initialize Regex
    compile_error_regex()

    # 2. Parse Arguments
    parser = argparse.ArgumentParser(description="Check a simulation logfile for errors.")
    parser.add_argument("logfile", help="Logfile to parse")
    parser.add_argument("--file-size-limit",
                        type=float,
                        default=0,
                        help='Maximum logfile size (MB). Default 0 (no limit)')
    parser.add_argument("--error-limit", type=int, default=25, help='Stop parsing logfile at this number of errors')
    options = parser.parse_args()

    logfile = options.logfile
    output_base = os.path.basename(logfile)

    # 3. Check File Size (MB)
    if options.file_size_limit > 0:
        size_mb = os.path.getsize(logfile) / (1024 * 1024.0)
        if size_mb > options.file_size_limit:
            with open(output_base + ".err", 'w') as err_log:
                err_log.write(f"#E log file size {size_mb:.2f}MB exceeds limit {options.file_size_limit}MB\n")
            sys.exit(1)

    try:
        scan_result = scan_static_log(logfile, options.error_limit)
        if scan_result is None:
            error_lines = []
            seed_lines = []
            run_time_lines = []
            found_finish = False
            with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if "TEST_CHECK_" in line and update_signatures(line):
                        continue
                    if err_regex.search(line):
                        error_lines.append(line)
                        if len(error_lines) >= options.error_limit:
                            break
                    elif not found_finish and finish_regex.search(line):
                        found_finish = True
                    elif "SVSEED" in line or "random seed used" in line:
                        seed_lines.append(line)
                    elif "real\t" in line and "user\t" in line:
                        run_time_lines.append(line)
        else:
            error_lines, seed_lines, run_time_lines, found_finish = scan_result
    except FileNotFoundError:
        print(f"Error: File {logfile} not found.")
        sys.exit(1)

    # CASE 1: Errors Found
    if error_lines:
        print(f"Error found in {logfile}")
        with open(output_base + ".err", 'w') as err_log:
            err_log.writelines(seed_lines)
            err_log.writelines(run_time_lines)
            err_log.writelines(error_lines)
            err_log.write(f'{platform.node()}\n')
        sys.exit(1)

    # CASE 2: No Finish Signature Found
    elif not found_finish:
        with open(output_base + ".err", 'w') as err_log:
            err_log.writelines(seed_lines)
            err_log.writelines(run_time_lines)
            err_log.write('******Did not find finish encountered!!!\n\n')
            err_log.write(f'{platform.node()}\n')

            # Use Python to get tail instead of subprocess (faster/safer)
            tail_lines = get_file_tail(logfile, 25)
            err_log.writelines(tail_lines)
        sys.exit(1)

    # CASE 3: Pass
    else:
        with open(output_base + ".pass", 'w') as pass_log:
            pass_log.write(f'{platform.node()}\n')
            pass_log.write("No Err found\n")
            pass_log.writelines(seed_lines)
            pass_log.writelines(run_time_lines)
        sys.exit(0)


if __name__ == '__main__':
    main()
