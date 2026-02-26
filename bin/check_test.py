#!/usr/bin/env python

import argparse
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
    r'%E-', r'%F-', r'%W-', r'#E',
    r"\*ERROR\*", r"\*FAILED\*",
    r"SVA_CHECKER_ERROR", r"Assertion FAILURE", r"Solver failed",
    r"VIRL_MEM_ERR",
    r"Warning-.FCIBR", r"Warning-.FCPSBU", r"Warning-.STASKW_CO",
    r"Warning-.SVART-NAFRLTS", r"Warning-.FCIELIE",
    r"Warning:.*AxiPC.sv",
    r"Error!!", r"Error:", r"ERROR..FAILURE", r"FATAL..FAILURE",
    r"Error-",
    r"UVM_ERROR [@/]", r"UVM_FATAL [@/]",
    r"UVM_ERROR .*[@/]", r"UVM_FATAL .*[@/]",
    r"WARNING.FAILURE",
    r" \*E,", r" \*F,",
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
    r"#I Final Report",
    r"finish at simulation time",
    r"Simulation complete via",
    r"--- UVM Report Summary ---"
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
    global active_signatures
    
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

def main():
    # 1. Initialize Regex
    compile_error_regex()
    
    # 2. Parse Arguments
    parser = argparse.ArgumentParser(description="Check a simulation logfile for errors.")
    parser.add_argument("logfile", help="Logfile to parse")
    parser.add_argument("--file-size-limit", type=float, default=0,
                        help='Maximum logfile size (MB). Default 0 (no limit)')
    parser.add_argument("--error-limit", type=int, default=25, 
                        help='Stop parsing logfile at this number of errors')
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

    # 4. Initialize State
    error_lines = []
    seed_lines = []
    run_time_lines = []
    found_finish = False
    
    # 5. Scan File
    # Using errors='replace' handles unicode issues in C (much faster than try/except loop)
    try:
        with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                
                # A. Check for dynamic enable/disable (Optimization: fast string check first)
                if "TEST_CHECK_" in line:
                    if update_signatures(line):
                        continue # Skip error check on the configuration line itself
                
                # B. Check for Errors
                # This is the most expensive operation, done once per line
                if err_regex.search(line):
                    error_lines.append(line)
                    if len(error_lines) >= options.error_limit:
                        break # Optimization: Stop reading if error limit reached
                
                # C. Check for Finish signature (Optimized: stop checking once found)
                elif not found_finish and finish_regex.search(line):
                    found_finish = True
                
                # D. Gather Metadata (Seeds and Runtime)
                # Using simple string substring checks is faster than regex
                elif "SVSEED" in line or "random seed used" in line:
                    seed_lines.append(line)
                elif "real\t" in line and "user\t" in line: # Specific check for time format
                    run_time_lines.append(line)
                    
    except FileNotFoundError:
        print(f"Error: File {logfile} not found.")
        sys.exit(1)

    # 6. Generate Reports
    
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
