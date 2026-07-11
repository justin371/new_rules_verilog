"""Extract useful repository timings from a Bazel JSON profile."""

import json
import re

_REPOSITORY_RE = re.compile(r"(?:@@?|external[/\\])([A-Za-z0-9._+~-]+)")
_REPOSITORY_NAME_RE = re.compile(r"repository(?: rule)?[=: ]+([A-Za-z0-9._+~-]+)", re.IGNORECASE)


def _repository_name(event, searchable):
    for key, value in event.get("args", {}).items():
        if "repo" not in str(key).lower():
            continue
        match = _REPOSITORY_RE.search(str(value))
        if match:
            return match.group(1)
        value = str(value).strip("@")
        if re.fullmatch(r"[A-Za-z0-9._+~-]+", value):
            return value

    match = _REPOSITORY_RE.search(searchable) or _REPOSITORY_NAME_RE.search(searchable)
    return match.group(1) if match else None


def repository_timings(profile_path):
    """Return aggregated Bazel repository event timings, longest first."""
    with open(profile_path, encoding="utf-8") as profile_file:
        events = json.load(profile_file).get("traceEvents", [])

    totals = {}
    for event in events:
        if event.get("ph") != "X" or not event.get("dur"):
            continue

        args = event.get("args", {})
        searchable = " ".join([str(event.get("cat", "")), str(event.get("name", ""))] +
                              ["{}={}".format(key, value) for key, value in args.items()])
        if "repos" not in searchable.lower() and "external/" not in searchable:
            continue

        repository = _repository_name(event, searchable)
        if not repository or repository == "BazelRepositoryModule":
            continue

        duration_s, count = totals.get(repository, (0.0, 0))
        totals[repository] = (duration_s + event["dur"] / 1_000_000.0, count + 1)

    return sorted(
        [(duration_s, repository, count) for repository, (duration_s, count) in totals.items()],
        reverse=True,
    )
