#!/usr/bin/env python
"""Parses results from Cadence HAL lint"""

################################################################################
# stdlib
import argparse
import os
import re
import subprocess
import sys

################################################################################
# Bigger libraries (better to place these later for dependency ordering
import bs4

################################################################################
# Checkout specific libraries
import cmn_logging

log = None

LOG_INDENT = ' ' * 9

################################################################################
# Constants
WAIVER_REGEXP = re.compile(r"\s// lint: disable=(.*)")

################################################################################
# Helpers


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Parse output report from HAL Lint using inline RTL waivers",
                                     formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--tool-debug',
                        default=False,
                        action='store_true',
                        help='Set the verbosity of this tool to debug level.')
    parser.add_argument("--bazel-target", default="lint_top", help="bazel target to use for lint")
    parser.add_argument("--sw",
                        dest="show_waived",
                        default=False,
                        action='store_true',
                        help='Show previously waived messages.')
    parser.add_argument("--sh",
                        dest="show_help",
                        action='store_true',
                        help="Display the help message from hal for each individual issue")
    parser.add_argument("--waiver-direct",
                        help="Direct waiver regex for when inline pragmas and design_info are insufficient")
    options = parser.parse_args(argv)
    return options


def find_bazel_runfiles(relpath, bazel_target):
    bazel_bin = subprocess.check_output(["bazel", "info", "bazel-bin"], text=True).strip()
    runfiles_main = os.path.join(bazel_bin, relpath, "{}.runfiles".format(bazel_target), "__main__")
    return runfiles_main


################################################################################
# Classes


class HalMessage(object):

    def __init__(self, errcode, severity, info, source_line, filename, lineno, help_msg):
        self.errcode = errcode # ID
        self.severity = severity
        self.info = info
        self.source_line = source_line
        self.filename = filename
        self.lineno = lineno
        self.help_msg = help_msg

        self.waived = False

    def __repr__(self):
        message = "{}:{}:{}  {}\n{}{}".format(self.filename, self.lineno, self.errcode, self.info, LOG_INDENT,
                                              self.source_line)
        if options.show_help:
            message += "\n\n{}{}".format(LOG_INDENT, self.help_msg)
        return message

    @classmethod
    def from_soup(cls, soup):
        errcode = soup.id.text.strip()
        severity = soup.severity.text.strip()
        info = soup.info.text.strip()
        try:
            source_line = soup.source_line.text.strip()
        except AttributeError:
            source_line = ""
        try:
            file_info = soup.file_info.text.strip()
            match = re.search(r'{"([^"]+)" ([0-9]+) [0-9]+}', file_info)
            filename = match.group(1)
            lineno = match.group(2)
        except AttributeError:
            filename = ""
            lineno = ""
        try:
            help_msg = soup.help.text.strip()
        except AttributeError:
            help_msg = ""

        return cls(errcode, severity, info, source_line, filename, lineno, help_msg)


class HalLintLog(object):

    def __init__(self, path, waiver_direct):
        self.issues = []
        self.files_with_notes = {}
        self.dirs_with_notes = {}
        self.waiver_direct_regex = re.compile(waiver_direct) if waiver_direct else None

        with open(path, 'r', encoding='utf-8', errors='replace') as logp:
            text = logp.read()

        # Cadence uses cdata in their xml output, need to avoid lxml parser which strips it out
        soup = bs4.BeautifulSoup(text, "html.parser")
        messages = soup.find_all(r'message')

        for message in messages:
            self.issues.append(HalMessage.from_soup(message))

        # Ignore notes, not sure if we should do this or flag these as well
        self.issues = [i for i in self.issues if i.severity != 'info']

        self.warnings = [issue for issue in self.issues if issue.severity == 'warning']
        self.errors = [issue for issue in self.issues if issue.severity == 'error']
        self.fatals = [issue for issue in self.issues if issue.severity == 'fatal']

        self.files_with_notes = set([issue.filename for issue in self.issues])

        # Each entry in this set is a tuple of (filename, lineno, errcode)
        waivers = set()
        for filename in self.files_with_notes:
            if filename == "":
                continue

            with open(filename, errors='replace') as filep:
                for i, line in enumerate(filep.readlines()):
                    match = WAIVER_REGEXP.search(line)
                    if match:
                        rules = match.group(1).split(',')
                        for rule in rules:
                            waivers.add((filename, str(i + 1), rule.strip()))

        for issue in self.issues:
            # Only apply a direct waiver if the filename and lineno are empty, meaning HAL didn't render the error correctly
            if (issue.filename, issue.lineno, issue.errcode) in waivers:
                issue.waived = True
            elif (issue.filename == "" and issue.lineno == "" and self.waiver_direct_regex
                  and self.waiver_direct_regex.search(issue.info)):
                issue.waived = True

        self.prep_file_stats()

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
        for warning in self.warnings:
            if not warning.waived:
                log.warn("%s", warning)
            elif options.show_waived:
                log.info("%s", warning)

        for error in self.errors:
            if not error.waived:
                log.error("%s", error)
            elif options.show_waived:
                log.info("%s", error)

        for fatal in self.fatals:
            log.error("%s", fatal)

        log.info("The following files have unwaived issues:")
        sorted_files = sorted(self.files_with_notes.items(), key=lambda x: x[1])
        for file_tuple in sorted_files:
            log.info("{file_name}: {count}".format(file_name=file_tuple[0], count=file_tuple[1]))

        log.info("The following directories have unwaived issues:")
        sorted_dirs = sorted(self.dirs_with_notes.items(), key=lambda x: x[1])
        for dir_tuple in sorted_dirs:
            log.info("{}: {}".format(dir_tuple[0], dir_tuple[1]))

        self._waived_unwaived('warnings')
        self._waived_unwaived('errors  ')
        self._waived_unwaived('fatals  ')


def main(options, log):
    xml_logfile = "xrun.log.xml"
    text_logfile = "xrun.log"

    if not os.path.exists(xml_logfile):
        log.error("XML logfile doesn't exist, something probably went pretty wrong earlier")
    elif os.path.getsize(xml_logfile) == 0:
        log.error("XML Logfile was 0 bytes, something probably went pretty wrong earlier")

    log.info("Text Logfile: %s", text_logfile)
    log.info("XML Logfile: %s", xml_logfile)

    try:
        newest_lint_log = HalLintLog(xml_logfile, options.waiver_direct)
        newest_lint_log.stats()
    except Exception as exc:
        log.error("Failed to parse lint log file: %s", exc)

    log.exit_if_warnings_or_errors("Previous errors")


if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    verbosity = cmn_logging.DEBUG if options.tool_debug else cmn_logging.INFO
    log = cmn_logging.build_logger("lint", level=verbosity)
    main(options, log)
