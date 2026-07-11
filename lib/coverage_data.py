"""Parse simulator text coverage summaries into dashboard metrics."""

import os
import re

_METRIC_NAMES = {
    "ASSERT": "Assertion",
    "ASSERTION": "Assertion",
    "BLOCK": "Block",
    "BRANCH": "Branch",
    "COND": "Condition",
    "CONDITION": "Condition",
    "COVERGROUP": "CoverGroup",
    "EXPRESSION": "Expression",
    "FSM": "FSM",
    "GROUP": "CoverGroup",
    "LINE": "Line",
    "OVERALL": "Overall",
    "SCORE": "Overall",
    "TGL": "Toggle",
    "TOGGLE": "Toggle",
}
_PERCENT_RE = re.compile(r"^(?:100(?:\.0+)?|[0-9]{1,2}(?:\.[0-9]+)?)%?$")


def _tokens(line):
    return [token.strip("|:") for token in line.split() if token.strip("|:")]


def parse_coverage_summary(path):
    """Return canonical percentage metrics from an URG or IMC text report."""
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8", errors="replace") as filep:
        lines = filep.readlines()

    for index, line in enumerate(lines):
        headers = [_METRIC_NAMES[token.upper()] for token in _tokens(line) if token.upper() in _METRIC_NAMES]
        if "Overall" not in headers or len(headers) < 2:
            continue
        for value_line in lines[index + 1:]:
            values = [token for token in _tokens(value_line) if _PERCENT_RE.match(token)]
            if len(values) < len(headers):
                continue
            return {header: value if value.endswith("%") else value + "%" for header, value in zip(headers, values)}
    return {}
