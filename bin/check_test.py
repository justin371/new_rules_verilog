#!/usr/bin/env python

# Scan test that confirms the simultion log file has no errors
#
# Error could include test from the bench, assertions, not seeing enough activity, etc.
#

import argparse
import os
import platform
import re
import sys
import subprocess

# Error signatures from log files
error_signature = [
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
]

# Signatures indicating a successful test completion
finish_signature = [
    "#I Final Report", "finish at simulation time", "Simulation complete via", "--- UVM Report Summary ---"
]

#compile the regular expressions to be used in a search
err_regex = None


def gen_err_regex():
    global err_regex
    err_regex = re.compile(r"(" + ")|(".join(error_signature) + ")")


finish_regex = re.compile(r"(" + ")|(".join(finish_signature) + ")")

enable_regex = re.compile(r".*TEST_CHECK_ENABLE: (.*)")
disable_regex = re.compile(r".*TEST_CHECK_DISABLE: (.*)")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Check a simulation logfile for errors.",
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("logfile", help="Logfile to parse")
    parser.add_argument("--file-size-limit",
                        default=0,
                        help='Maximum logfile size (MB) if running at UVM_NONE should be 5MB')
    parser.add_argument("--error-limit", default=25, help='Stop parsing logfile at this number of errors')
    options = parser.parse_args(argv)
    return options


def enable_disable_checks(line):
    enable_match = enable_regex.match(line)
    if enable_match:
        # Add check to err_regex, recompile
        new_regex = enable_match.group(1)
        if new_regex not in error_signature:
            error_signature.append(new_regex)
            gen_err_regex()
        return True
    disable_match = disable_regex.match(line)
    if disable_match:
        # Remove check from err_regex, recompile
        remove_regex = disable_match.group(1)
        if remove_regex in error_signature:
            error_signature.remove(remove_regex)
            gen_err_regex()
        return True
    return False


def main(options):
    gen_err_regex()
    error_lines = []
    found_finish_line = False
    output_file = os.path.basename(options.logfile)
    seed_lines = []
    run_time_lines = []
    uvm_verbosity = None
    if (len(sys.argv) > 2):
        max_size = eval(sys.argv[2])
    else:
        max_size = 0

    # search lines of the log file for "seed", or error or finish signatures

    with open(options.logfile, 'r', encoding='utf-8', errors='ignore') as in_file:
        try:
            for line_no, line in enumerate(in_file):
                # Before the actual checking, we need to see if a disable or enable statement is used
                if enable_disable_checks(line):
                    pass # Side effect of this function is to add or remove the desired regex to err_regex
                elif err_regex.search(line):
                    error_lines.append(line)
                    if len(error_lines) >= options.error_limit:
                        break
                elif "random seed used" in line or "SVSEED" in line:
                    # This is going to be a really inefficient lookup eventually
                    seed_lines.append(line)
                elif not found_finish_line and finish_regex.search(line):
                    found_finish_line = True
                elif "real\t" in line:
                    run_time_lines.append(line)
        except UnicodeDecodeError:
            finish_line = 0
            print("UnicodeDecodeError on line ", line_num + 1)

    if len(error_lines) > 0:
        # We found some errors
        print("Error found in ", options.logfile)
        with open(output_file + ".err", 'w') as err_log:
            for line in seed_lines:
                err_log.write(line)
            for line in run_time_lines:
                err_log.write(line)
            for line in error_lines:
                err_log.write(line)
            err_log.write('%s\n' % platform.node())
        # Clean up log file by removing path to filenames
        #fn_regex = re.compile(r'(/.*/)(.*\.sv.?)\(')
        #with open(options.logfile, 'r', encoding='utf-8', errors='ignore') as in_file:
        #with open(output_file+".log",'w') as out_file:
        #for line in in_file:
        #out_file.write(fn_regex.sub(r'\g<2>(', line))
        sys.exit(1)
    elif not found_finish_line:
        # No finish was found
        with open(output_file + ".err", 'w') as err_log:
            for line in seed_lines:
                err_log.write(line)
            for line in run_time_lines:
                err_log.write(line)
            err_log.write('******Did not find finish encountered!!!\n\n')
            err_log.write('%s\n' % platform.node())
            tail_lines = subprocess.Popen(['tail', '-25', options.logfile],
                                          stdout=subprocess.PIPE,
                                          universal_newlines=True).stdout.readlines()
            #    print subprocess.check_output(['tail', '-10', options.logfile])
            for line in tail_lines:
                err_log.write(line)
        sys.exit(1)
    elif max_size > 0 and (os.path.getsize(options.logfile) > max_size * 2**20):
        with open(output_file + ".err", 'w') as err_log:
            err_log.write("#E log file size %d exceeds max_size %d" % (os.path.getsize(options.logfile), max_size))
        sys.exit(1)
    else:
        # Test run passed
        with open(output_file + ".pass", 'w') as pass_log:
            pass_log.write('%s\n' % platform.node())
            pass_log.write("No Err found\n")
            for line in seed_lines:
                pass_log.write(line)
            for line in run_time_lines:
                pass_log.write(line)
        sys.exit(0)


if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    main(options)
