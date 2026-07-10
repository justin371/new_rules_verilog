#!/usr/bin/env python
"""Parses results from Real Intent Ascent Lint"""

################################################################################
# stdlib
import argparse
import os
import re
import sys

################################################################################
# Checkout specific libraries
import cmn_logging

################################################################################
# Constants
LINE_WAIVER_REGEXP = re.compile(r"\S\s// lint: disable=(.*)")
BLOCK_WAIVER_START_REGEXP = re.compile(r"\s*// lint: disable=(.*)")
BLOCK_WAIVER_END_REGEXP = re.compile(r"\s*// lint: enable=(.*)")

################################################################################
# Helpers


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Parse output report from Ascent Lint using inline RTL waivers",
                                     formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--tool-debug',
                        default=False,
                        action='store_true',
                        help='Set the verbosity of this tool to debug level.')
    parser.add_argument("--sw",
                        dest="show_waived",
                        default=False,
                        action='store_true',
                        help='Show previously waived messages.')
    parser.add_argument("--sh",
                        dest="show_help",
                        action='store_true',
                        help="Display the help message from Ascent for each individual issue")
    options = parser.parse_args(argv)
    return options


################################################################################
# Classes


class AscentMessage(object):

    def __init__(self, errcode, severity, info, filename, lineno):
        self.errcode = errcode # ID
        self.severity = severity
        self.info = info
        self.filename = filename
        self.lineno = lineno

        self.waived = False

    def __repr__(self):
        return "{}:{}:{}  {}".format(self.filename, self.lineno, self.errcode, self.info)

    @classmethod
    def from_csv(cls, csv_row):
        if csv_row['severity'] == "S":
            return None

        severity = csv_row['severity']
        errcode = csv_row['rulename']
        info = csv_row['details']

        match = re.match(r'(\S+):(\d+)', csv_row['file'])
        filename = match.group(1)
        lineno = match.group(2)

        return cls(errcode, severity, info, filename, lineno)


class AscentLintLog(object):

    def __init__(self, path, log):
        self.issues = []
        self.files_with_notes = {}
        self.dirs_with_notes = {}
        self.file_map = {}

        found_file_map = False

        # Can't use CSV. Need the full logfile because need to grab the file definitions
        with open(path, 'r', encoding='utf-8', errors='replace') as logp:
            for line in logp:
                if line.strip() == "Lint engine run exited with errors upstream. Skipping report.":
                    log.critical("Ascent failed before it can render a report. Exiting")
                match = re.match(r"([IWE])\s+([A-Z_]+):\s+(\S+):(\d+)\s+(.*)\s+New", line)
                if match:
                    self.issues.append(
                        AscentMessage(match.group(2), match.group(1),
                                      match.group(5).strip(), match.group(3), int(match.group(4))))
                    continue
                if line.startswith("File Definitions"):
                    found_file_map = True
                if found_file_map:
                    match = re.match(r"([a-zA-Z0-9_]+\.s?vh?(_\d+)?)\s+(.{0,2}\S+)", line)
                    if match:
                        self.file_map[match.group(1)] = match.group(3)

        self.infos = [issue for issue in self.issues if issue.severity == 'I']
        self.warnings = [issue for issue in self.issues if issue.severity == 'W']
        self.errors = [issue for issue in self.issues if issue.severity == 'E']

        self.files_with_notes = set([issue.filename for issue in self.issues])

        # Each entry in this set is a tuple of (filename, lineno, errcode)
        line_waivers = {}
        # line_waivers = set()
        block_waivers = {}
        for filename in self.files_with_notes:
            if filename == "":
                continue

            # Map from the base path name to the bazel-relative path name to be able to find waivers
            relative_filename = self.file_map[filename]
            with open(relative_filename, errors='replace') as filep:
                for i, line in enumerate(filep.readlines()):
                    match = LINE_WAIVER_REGEXP.search(line)
                    if match:
                        self._handle_line_waiver(line_waivers, filename, i + 1, match.group(1), log)
                    match = BLOCK_WAIVER_START_REGEXP.match(line)
                    if match:
                        self._handle_block_start(block_waivers, filename, i + 1, match.group(1), log)
                        continue
                    match = BLOCK_WAIVER_END_REGEXP.match(line)
                    if match:
                        self._handle_block_end(block_waivers, filename, i + 1, match.group(1), log)
                        continue

        self._check_block_waivers(block_waivers, log)

        for issue in self.issues:
            if issue.filename in line_waivers and issue.errcode in line_waivers[issue.filename]:
                for lineno in line_waivers[issue.filename][issue.errcode]:
                    if issue.lineno == lineno:
                        issue.waived = True
                        continue
            # Don't use try/except because this should not succeed in try often
            if issue.filename in block_waivers and issue.errcode in block_waivers[issue.filename]:
                for line_pair in block_waivers[issue.filename][issue.errcode]:
                    if issue.lineno > line_pair[0] and issue.lineno < line_pair[1]:
                        issue.waived = True

        self.prep_file_stats()

    def _handle_line_waiver(self, line_waivers, filename, lineno, match, log):
        line_waivers.setdefault(filename, {})
        rules = match.split(',')
        for rule in rules:
            rule = rule.strip()
            line_waivers[filename].setdefault(rule, [])
            line_waivers[filename][rule].append(lineno)
            continue

    def _handle_block_start(self, block_waivers, filename, lineno, match, log):
        block_waivers.setdefault(filename, {})
        rules = match.split(',')
        for rule in rules:
            rule = rule.strip()
            # Check to see if the last 'disable' has a matching 'enable'
            if rule in block_waivers[filename]:
                if block_waivers[filename][rule][-1][1] is None:
                    log.error("In %s, %s has a 'disable' on line %s and %s without an 'enable' in between", filename,
                              rule, block_waivers[filename][rule][-1][0], lineno)
                else:
                    # previous disable/enable is coherent so we can add a new entry to the list
                    block_waivers[filename][rule].append([lineno, None])
            else:
                block_waivers[filename][rule] = [[lineno, None]]

    def _handle_block_end(self, block_waivers, filename, lineno, match, log):
        if filename not in block_waivers:
            log.error("In %s, 'enable' pragmas on line %s for '%s' appears before any 'disable' pragmas", filename,
                      lineno, match)
            return
        rules = match.split(',')
        for rule in rules:
            rule = rule.strip()
            if rule not in block_waivers[filename]:
                log.error("In %s, 'enable' pragma for %s on line %s appears before any 'disable' pragmas", filename,
                          rule, lineno)
                return
            if block_waivers[filename][rule][-1][1] is None:
                block_waivers[filename][rule][-1][1] = lineno
            else:
                log.error(
                    "In %s, 'enable' pragma for %s on line %s doesn't have a matching 'disable'. Previous ['disable', 'enable'] are on lines %s",
                    filename, rule, lineno, str(block_waivers[filename][rule][-1]))

    def _check_block_waivers(self, block_waivers, log):
        for filename, rule_dict in block_waivers.items():
            for rule, waiver_list in rule_dict.items():
                if waiver_list[-1][1] is None:
                    log.error("In %s, couldn't find a matching 'enable' for %s. The 'disable' is on line %s", filename,
                              rule, waiver_list[-1][0])
                    # Remove the partial block waiver from the list since it's incomplete
                    del waiver_list[-1]

    def prep_file_stats(self):

        self.files_with_notes = {}

        for issue in self.issues:
            if not issue.waived:
                self.files_with_notes.setdefault(issue.filename, 0)
                self.files_with_notes[issue.filename] += 1

        def rtl_dir_from_path(file_path):
            orig_path = file_path
            loop_count = 0
            base_dir = None
            while os.path.basename(file_path) not in ['rtl', 'analog'] and loop_count <= 10:
                base_dir = os.path.basename(file_path)
                file_path = os.path.split(file_path)[0]
                loop_count += 10

            if loop_count == 10:
                log.info("Couldn't resolve base directory for {}".format(orig_path))
                return orig_path

            return os.path.join(file_path, base_dir)

        for issue in self.issues:
            if not issue.waived:
                rtl_dir = rtl_dir_from_path(issue.filename)
                self.dirs_with_notes.setdefault(rtl_dir, 0)
                self.dirs_with_notes[rtl_dir] += 1

    def _waived_unwaived(self, level):
        issues = getattr(self, level.strip())
        waived = sum([i.waived for i in issues])
        unwaived = len(issues) - waived
        if unwaived:
            log.error("Found %3d %s (+%3d waived)", unwaived, level, waived)
        else:
            log.info("Found %3d %s (+%3d waived)", unwaived, level, waived)

    def stats(self):
        for info in self.infos:
            if not info.waived:
                log.error("%s", info)
            elif options.show_waived:
                log.info("%s", info)

        for warning in self.warnings:
            if not warning.waived:
                log.error("%s", warning)
            elif options.show_waived:
                log.info("%s", warning)

        for error in self.errors:
            if not error.waived:
                log.error("%s", error)
            elif options.show_waived:
                log.info("%s", error)

        log.debug("The following files have unwaived issues:")
        sorted_files = sorted(self.files_with_notes.items(), key=lambda x: x[1])
        for file_tuple in sorted_files:
            log.debug("{file_name}: {count}".format(file_name=file_tuple[0], count=file_tuple[1]))

        log.debug("The following directories have unwaived issues:")
        sorted_dirs = sorted(self.dirs_with_notes.items(), key=lambda x: x[1])
        for dir_tuple in sorted_dirs:
            log.debug("{}: {}".format(dir_tuple[0], dir_tuple[1]))

        self._waived_unwaived('infos')
        self._waived_unwaived('warnings')
        self._waived_unwaived('errors  ')


def main(options, log):
    try:
        newest_lint_log = AscentLintLog("lint.rpt", log)
        newest_lint_log.stats()
    except Exception:
        log.error("Failed to parse lint.rpt")

    log.exit_if_warnings_or_errors("Lint parsing failed due to previous errors")


if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    verbosity = cmn_logging.INFO if options.tool_debug else cmn_logging.DEBUG
    log = cmn_logging.build_logger("bazel_lint.log", level=verbosity)
    main(options, log)
