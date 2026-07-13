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
    "STATEMENT": "Line",
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


def _percentage(value):
    try:
        return float(str(value).rstrip("%"))
    except (TypeError, ValueError):
        return None


def _average(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _format_percentage(value):
    return "{:.2f}%".format(value) if value is not None else None


def aggregate_coverage_metrics(metrics):
    """Apply the OpenTitan DVSim coverage averages to canonical metrics."""
    condition = _percentage(metrics.get("Condition"))
    if condition is None:
        condition = _percentage(metrics.get("Expression"))

    code_average = _average([
        _percentage(metrics.get("Line")),
        _percentage(metrics.get("Branch")),
        condition,
        _percentage(metrics.get("Toggle")),
        _percentage(metrics.get("FSM")),
    ])
    assertion = _percentage(metrics.get("Assertion"))
    functional = _percentage(metrics.get("CoverGroup"))
    total = _average([code_average, assertion, functional])

    code_metrics = {
        key: value
        for key, value in metrics.items()
        if key in ("Block", "Line", "Branch", "Condition", "Expression", "Toggle", "FSM")
    }
    if code_average is not None:
        code_metrics = {"Overall": _format_percentage(code_average), **code_metrics}

    functional_metrics = {}
    if functional is not None:
        functional_metrics.update({
            "Overall": _format_percentage(functional),
            "CoverGroup": _format_percentage(functional),
        })
    if assertion is not None:
        functional_metrics["Assertion"] = _format_percentage(assertion)

    return {
        "total": _format_percentage(total),
        "vendor_score": metrics.get("Overall"),
        "cc": code_metrics,
        "cf": functional_metrics,
    }
