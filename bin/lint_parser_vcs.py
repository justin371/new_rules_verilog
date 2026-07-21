#!/usr/bin/env python
"""Parses VCS lint-style diagnostics with inline RTL waivers."""

import argparse
import os
import re
import sys

import cmn_logging


LINE_WAIVER_REGEXP = re.compile(r"\S[ \t]+// lint: disable=(.*)")
BLOCK_WAIVER_START_REGEXP = re.compile(r"\s*// lint: disable=(.*)")
BLOCK_WAIVER_END_REGEXP = re.compile(r"\s*// lint: enable=(.*)")
HEADER_REGEXP = re.compile(r"^(?P<severity>Warning|Error|Fatal|Lint)-\[(?P<errcode>[^\]]+)\]\s*(?P<info>.*)$")
FILE_LINE_REGEXPS = [
    re.compile(r'"(?P<filename>[^"]+)",\s*(?:line\s*)?(?P<lineno>\d+)'),
    re.compile(r'(?P<filename>[A-Za-z]:[\\/][^,\n]+),\s*(?:line\s*)?(?P<lineno>\d+)'),
    re.compile(r'(?P<filename>[/\w.\-\\]+),\s*(?:line\s*)?(?P<lineno>\d+)'),
]


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Parse VCS lint-style output using inline RTL waivers",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument('--tool-debug', default=False, action='store_true', help='Set parser verbosity to debug.')
    parser.add_argument("--sw", dest="show_waived", default=False, action='store_true', help='Show previously waived messages.')
    parser.add_argument("--waiver-direct", default="", help="Direct waiver regex for messages without file/line info.")
    return parser.parse_args(argv)


class VcsMessage(object):
    def __init__(self, errcode, severity, info, filename, lineno, block):
        self.errcode = errcode
        self.severity = severity
        self.info = info
        self.filename = filename
        self.lineno = lineno
        self.block = block
        self.waived = False

    def __repr__(self):
        prefix = "{}:{}:{}  {}".format(self.filename, self.lineno, self.errcode, self.info)
        if self.filename == "" and self.lineno == "":
            prefix = "{}  {}".format(self.errcode, self.info)
        return "{}\n{}".format(prefix, self.block.rstrip())


class VcsLintLog(object):
    def __init__(self, path, waiver_direct, log):
        self.issues = []
        self.files_with_notes = {}
        self.dirs_with_notes = {}
        self.waiver_direct_regex = re.compile(waiver_direct) if waiver_direct else None

        with open(path, 'r', encoding='utf-8', errors='replace') as logp:
            lines = logp.readlines()

        self._parse_messages(lines)
        self.infos = []
        self.warnings = [issue for issue in self.issues if issue.severity in ['Warning', 'Lint']]
        self.errors = [issue for issue in self.issues if issue.severity == 'Error']
        self.fatals = [issue for issue in self.issues if issue.severity == 'Fatal']

        self._apply_waivers(log)
        self.prep_file_stats(log)

    def _parse_messages(self, lines):
        current_block = []
        current_header = None

        def flush_current():
            if current_header is None:
                return
            block = "".join(current_block)
            filename = ""
            lineno = ""
            for regex in FILE_LINE_REGEXPS:
                match = regex.search(block)
                if match:
                    filename = match.group('filename')
                    lineno = match.group('lineno')
                    break
            self.issues.append(
                VcsMessage(
                    errcode=current_header.group('errcode'),
                    severity=current_header.group('severity'),
                    info=current_header.group('info').strip(),
                    filename=filename,
                    lineno=lineno,
                    block=block,
                )
            )

        for line in lines:
            header = HEADER_REGEXP.match(line)
            if header:
                flush_current()
                current_header = header
                current_block = [line]
            elif current_header is not None:
                current_block.append(line)
        flush_current()

    def _apply_waivers(self, log):
        line_waivers = {}
        block_waivers = {}
        files_with_paths = set(issue.filename for issue in self.issues if issue.filename)

        for filename in files_with_paths:
            if not os.path.exists(filename):
                log.debug("Skipping waiver scan for missing file path: %s", filename)
                continue
            with open(filename, errors='replace') as filep:
                for i, line in enumerate(filep.readlines()):
                    match = LINE_WAIVER_REGEXP.search(line)
                    if match:
                        self._handle_line_waiver(line_waivers, filename, i + 1, match.group(1))
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
                    if str(issue.lineno) == str(lineno):
                        issue.waived = True
                        break
            if issue.filename in block_waivers and issue.errcode in block_waivers[issue.filename]:
                for line_pair in block_waivers[issue.filename][issue.errcode]:
                    if issue.lineno != "" and int(issue.lineno) > line_pair[0] and int(issue.lineno) < line_pair[1]:
                        issue.waived = True
                        break
            if not issue.waived and issue.filename == "" and issue.lineno == "" and self.waiver_direct_regex:
                if self.waiver_direct_regex.search(issue.info):
                    issue.waived = True

    def _handle_line_waiver(self, line_waivers, filename, lineno, match):
        line_waivers.setdefault(filename, {})
        for rule in match.split(','):
            rule = rule.strip()
            line_waivers[filename].setdefault(rule, [])
            line_waivers[filename][rule].append(lineno)

    def _handle_block_start(self, block_waivers, filename, lineno, match, log):
        block_waivers.setdefault(filename, {})
        for rule in match.split(','):
            rule = rule.strip()
            if rule in block_waivers[filename] and block_waivers[filename][rule][-1][1] is None:
                log.error("In %s, %s has a disable on line %s and %s without an enable in between", filename, rule, block_waivers[filename][rule][-1][0], lineno)
            else:
                block_waivers[filename].setdefault(rule, [])
                block_waivers[filename][rule].append([lineno, None])

    def _handle_block_end(self, block_waivers, filename, lineno, match, log):
        if filename not in block_waivers:
            log.error("In %s, enable pragmas on line %s for '%s' appear before any disable pragmas", filename, lineno, match)
            return
        for rule in match.split(','):
            rule = rule.strip()
            if rule not in block_waivers[filename] or block_waivers[filename][rule][-1][1] is not None:
                log.error("In %s, enable pragma for %s on line %s doesn't have a matching disable", filename, rule, lineno)
                continue
            block_waivers[filename][rule][-1][1] = lineno

    def _check_block_waivers(self, block_waivers, log):
        for filename, rule_dict in block_waivers.items():
            for rule, waiver_list in rule_dict.items():
                if waiver_list and waiver_list[-1][1] is None:
                    log.error("In %s, couldn't find a matching enable for %s. The disable is on line %s", filename, rule, waiver_list[-1][0])
                    del waiver_list[-1]

    def prep_file_stats(self, log):
        self.files_with_notes = {}
        self.dirs_with_notes = {}

        def rtl_dir_from_path(file_path):
            orig_path = file_path
            loop_count = 0
            base_dir = None
            while os.path.basename(file_path) not in ['rtl', 'analog'] and loop_count <= 10:
                base_dir = os.path.basename(file_path)
                file_path = os.path.split(file_path)[0]
                loop_count += 1
            if loop_count > 10 or base_dir is None:
                log.debug("Couldn't resolve base directory for %s", orig_path)
                return orig_path
            return os.path.join(file_path, base_dir)

        for issue in self.issues:
            if issue.waived:
                continue
            self.files_with_notes.setdefault(issue.filename, 0)
            self.files_with_notes[issue.filename] += 1
            if issue.filename:
                rtl_dir = rtl_dir_from_path(issue.filename)
                self.dirs_with_notes.setdefault(rtl_dir, 0)
                self.dirs_with_notes[rtl_dir] += 1

    def _waived_unwaived(self, level, log):
        issues = getattr(self, level.strip())
        waived = sum(issue.waived for issue in issues)
        unwaived = len(issues) - waived
        if unwaived:
            log.error("Found %3d %s (+%3d waived)", unwaived, level, waived)
        else:
            log.info("Found %3d %s (+%3d waived)", unwaived, level, waived)

    def stats(self, options, log):
        for issue in self.warnings + self.errors + self.fatals:
            if not issue.waived:
                log.error("%s", issue)
            elif options.show_waived:
                log.info("%s", issue)

        self._waived_unwaived('warnings', log)
        self._waived_unwaived('errors  ', log)
        self._waived_unwaived('fatals  ', log)


def main(options, log):
    logfile = "lint.log"
    if not os.path.exists(logfile):
        log.error("Logfile %s doesn't exist, something probably went wrong earlier", logfile)
        log.exit_if_warnings_or_errors("Previous errors")
        return

    newest_lint_log = VcsLintLog(logfile, options.waiver_direct, log)
    newest_lint_log.stats(options, log)
    log.exit_if_warnings_or_errors("VCS lint parsing failed due to previous errors")


if __name__ == '__main__':
    options = parse_args(sys.argv[1:])
    verbosity = cmn_logging.DEBUG if options.tool_debug else cmn_logging.INFO
    log = cmn_logging.build_logger("vcs_lint", level=verbosity)
    main(options, log)
