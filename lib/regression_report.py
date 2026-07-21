#!/usr/bin/env python3
"""Generate and retain static HTML regression reports."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import tempfile
import threading
from urllib.parse import quote as url_quote

import fcntl

import jinja2

MAX_HISTORY = 30
_COVERAGE_CLEANUP_LOCK_KEY = "deferred_coverage_cleanup"


def _ensure_directory(path, label):
    path = Path(path)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        try:
            path.mkdir()
        except FileExistsError:
            pass
        mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise ValueError("{} must not be a symlink: {}".format(label, path))
    if not stat.S_ISDIR(mode):
        raise ValueError("{} must be a directory: {}".format(label, path))
    return path


def _ensure_child_directories(root, *components):
    path = Path(root)
    for component in components:
        path = _ensure_directory(path / component, "Report directory")
    return path


@contextmanager
def _advisory_lock(path, shared=False, blocking=True):
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Lock path must be a regular file: {}".format(path))
        operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(descriptor)


@contextmanager
def _publication_signal_guard():
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous_handlers = {}

    def interrupt_publication(signal_number, _frame):
        raise KeyboardInterrupt("Report publication interrupted by signal {}".format(signal_number))

    for signal_number in (signal.SIGTERM, signal.SIGHUP):
        previous_handler = signal.getsignal(signal_number)
        if previous_handler == signal.SIG_IGN:
            continue
        previous_handlers[signal_number] = previous_handler
        signal.signal(signal_number, interrupt_publication)
    try:
        yield
    finally:
        for signal_number, previous_handler in previous_handlers.items():
            signal.signal(signal_number, previous_handler)


@contextmanager
def coverage_artifact_lock(regression_dir, timestamp, shared, blocking=True):
    """Coordinate report retention with readers of a coverage artifact."""
    coverage_root = Path(regression_dir) / "report_coverage"
    coverage_root.parent.mkdir(parents=True, exist_ok=True)
    coverage_root = _ensure_directory(coverage_root, "Coverage report directory")
    lock_dir = _ensure_child_directories(coverage_root, ".locks")
    lock_name = hashlib.sha256(str(timestamp).encode("utf-8")).hexdigest() + ".lock"
    with _advisory_lock(lock_dir / lock_name, shared=shared, blocking=blocking) as acquired:
        yield acquired


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coverage_value(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).rstrip("%"))
    except (TypeError, ValueError):
        return None


def _coverage_metric(coverage, section, metric="Overall"):
    return _coverage_value(coverage.get(section, {}).get(metric))


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "item"


def _is_safe_report_component(value):
    separators = tuple(separator for separator in (os.path.sep, os.path.altsep) if separator)
    if not isinstance(value, str) or value in ("", ".", "..") or "\0" in value:
        return False
    return not any(separator in value for separator in separators)


def _write_text_atomic(path, contents):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".report-", dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as filep:
            filep.write(contents)
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def _write_json_atomic(path, value):
    _write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _read_file_bytes(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Report path must be a regular file: {}".format(path))
        with os.fdopen(descriptor, "rb", closefd=False) as filep:
            return filep.read()
    finally:
        os.close(descriptor)


def _write_bytes_atomic(path, contents):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".report-", dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "wb") as filep:
            filep.write(contents)
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def _load_json(path, default):
    try:
        contents = _read_file_bytes(path)
    except FileNotFoundError:
        return default
    value = json.loads(contents.decode("utf-8"))
    if not isinstance(value, type(default)):
        raise ValueError("Unexpected JSON structure in {}".format(path))
    return value


def _history_timestamps(regressions):
    return sorted(regressions,
                  key=lambda timestamp: (_safe_int(regressions[timestamp].get("publication_order")), timestamp))


def _zip_filter(*iterables):
    return zip(*iterables)


def create_template_environment(template_dir):
    """Create the autoescaping Jinja environment used by HTML reports."""
    environment = jinja2.Environment(
        autoescape=jinja2.select_autoescape(enabled_extensions=("html", "xml", "html.j2", "xml.j2")),
        loader=jinja2.FileSystemLoader(searchpath=template_dir),
    )
    environment.filters["zip"] = _zip_filter
    return environment


def regression_history_series(regressions, timestamps):
    """Return pass and coverage chart series."""
    entries = [regressions[timestamp] for timestamp in timestamps if timestamp in regressions]
    return (
        [entry.get("passrate", 0) for entry in entries],
        [entry.get("cov_total") for entry in entries],
        [entry.get("cov_code", 0) for entry in entries],
        [entry.get("cov_func", 0) for entry in entries],
    )


class RegressionReport:
    """Own static report rendering and retention."""

    def __init__(self, rcfg, template_env, webroot_dir):
        self.rcfg = rcfg
        self.env = template_env
        self.webroot_dir = webroot_dir
        self.output_path = os.path.join(self.webroot_dir, "regression_report")
        self.project_info_path = os.path.join(self.output_path, "project_info.json")

        self.HOME_TEMPLATE = self.env.get_template("regression_report_templates/home_template.html.j2")
        self.BENCHS_TEMPLATE = self.env.get_template("regression_report_templates/benchs_template.html.j2")
        self.REGRESSION_REPORT_TEMPLATE = self.env.get_template(
            "regression_report_templates/regression_report_template.html.j2")
        self.LOGS_TEMPLATE = self.env.get_template("regression_report_templates/logs_template.html.j2")

        self.header = {}
        self.raw_trd = []
        self.trd = {}
        self.cov = {}
        self.proj_name = ""
        self.project_info = {}
        self.bench_list = []
        self.category_stats = {}
        self.processed_category_stats = []
        self.rerun_context = {}
        self._pending_history_cleanup = []
        self.publication_committed = False

    def _refresh_project_info(self):
        try:
            project_info = _load_json(self.project_info_path, {})
        except (json.JSONDecodeError, ValueError) as exc:
            self.rcfg.log.warning("Ignoring invalid report project index %s: %s", self.project_info_path, exc)
            project_info = {}
        benches = set(project_info.get(self.proj_name, []))
        benches.update(self.bench_list)
        project_info[self.proj_name] = sorted(benches)
        self.project_info = project_info

    def process_trd(self, trd):
        """Normalize print_summary rows and group them by bench."""
        self.trd = {}
        current_bench = None
        last_job = None

        for raw_entry in trd:
            entry = list(raw_entry)
            entry.extend([""] * max(0, 9 - len(entry)))
            if entry[0]:
                current_bench = entry[0]
            if entry[1] and current_bench:
                total = _safe_int(entry[6])
                pass_rate = (_safe_int(entry[3]) / total * 100) if total else 0
                normalized = entry[:7] + ["{:.2f}".format(pass_rate), entry[7], entry[8]]
                self.trd.setdefault(current_bench, []).append(normalized)
                last_job = normalized
            elif entry[7] and last_job is not None:
                last_job[8] = "|".join(part for part in [last_job[8], entry[7]] if part)

        for bench, rows in self.trd.items():
            test_rows = rows[1:] if rows and rows[0][1] == "vcomp" else rows
            passed = sum(_safe_int(row[3]) for row in test_rows)
            skipped = sum(_safe_int(row[4]) for row in test_rows)
            failed = sum(_safe_int(row[5]) for row in test_rows)
            total = passed + skipped + failed
            rows.append([
                "Total",
                "",
                "",
                str(passed) if passed else "",
                str(skipped) if skipped else "",
                str(failed) if failed else "",
                str(total) if total else "",
                "{:.2f}".format(passed / total * 100) if total else "0.00",
                "",
                "",
            ])

        self.bench_list = list(self.trd)

    def process_category_stats(self):
        """Convert category statistics into template-friendly rows."""
        self.processed_category_stats = []
        for category, stats in (self.category_stats or {}).items():
            total = stats["total"]
            executed = stats["executed"]
            passed = stats["passed"]
            completion_rate = "{:.2f}%".format(executed / total * 100) if total else "N/A"
            pass_rate = "{:.2f}%".format(passed / executed * 100) if executed else "N/A"
            self.processed_category_stats.append([
                category,
                str(total),
                str(executed),
                completion_rate,
                str(passed),
                pass_rate,
            ])

    def run(self, header, trd, cov, category_stats, rerun_context=None, report_url=None):
        """Prepare and render a complete report."""
        self.prepare(header, trd, cov, category_stats, rerun_context=rerun_context)
        self.render_locked(report_url=report_url)

    def prepare(self, header, trd, cov, category_stats, rerun_context=None):
        for label, value in (("project name", header.get("project_name")), ("report time", header.get("time"))):
            if not _is_safe_report_component(value):
                raise ValueError("Unsafe {} path component: {!r}".format(label, value))
        project_name = header["project_name"]
        if project_name in ("index.html", "project_info.json", ".locks") or (project_name.startswith("open_")
                                                                             and project_name.endswith(".sh")):
            raise ValueError("Reserved project name: {!r}".format(project_name))
        if header["time"] == "index":
            raise ValueError("Reserved report time: 'index'")
        self.header = header
        self.raw_trd = [list(row) for row in trd]
        self.cov = cov or {}
        self.category_stats = category_stats or {}
        self.rerun_context = rerun_context or {}
        self.process_trd(trd)
        for bench in self.bench_list:
            if not _is_safe_report_component(bench):
                raise ValueError("Unsafe bench path component: {!r}".format(bench))
            if bench == "index.html":
                raise ValueError("Reserved bench name: 'index.html'")
        self.process_category_stats()
        self.proj_name = self.header["project_name"]
        Path(self.webroot_dir).mkdir(parents=True, exist_ok=True)
        _ensure_directory(self.output_path, "Report root")
        self._refresh_project_info()

    def render_locked(self, report_url=None):
        lock_dir = _ensure_child_directories(self.output_path, ".locks")
        project_lock_name = hashlib.sha256(self.proj_name.encode("utf-8")).hexdigest() + ".lock"
        with _advisory_lock(lock_dir / project_lock_name), _advisory_lock(lock_dir / "index.lock"), \
             _publication_signal_guard():
            self.publication_committed = False
            _ensure_child_directories(self.output_path, self.proj_name)
            for bench in self.bench_list:
                _ensure_child_directories(self.output_path, self.proj_name, bench)
            self._assert_revision_available()
            snapshot = self._publication_snapshot()
            self._pending_history_cleanup = []
            try:
                self.render_regression_page()
                self.render_bench_page()
                self.render_home_page()
                self.write_run_launcher(report_url)
            except (Exception, KeyboardInterrupt,
                    SystemExit): # noqa: BROAD_EXCEPT_OK - restore every changed report index.
                try:
                    self._restore_publication_snapshot(snapshot)
                except Exception as rollback_error: # noqa: BROAD_EXCEPT_OK - preserve the original publication failure.
                    self.rcfg.log.warning("Failed to restore report publication snapshot: %s", rollback_error)
                raise
            self.publication_committed = True
            for maintenance_name, maintenance in (("history cleanup", self._cleanup_committed_history),
                                                  ("launcher cleanup", self._prune_run_launchers)):
                try:
                    maintenance()
                except Exception as exc: # noqa: BROAD_EXCEPT_OK - publication is committed.
                    self.rcfg.log.warning("Report was published, but %s did not finish: %s", maintenance_name, exc)

    def _assert_revision_available(self):
        timestamp = self.header["time"]
        project_path = Path(self.output_path, self.proj_name)
        for bench in self.bench_list:
            bench_path = project_path / bench
            regressions_path = bench_path / "regressions.json"
            try:
                regressions = _load_json(regressions_path, {})
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError):
                regressions = {}
            revision_artifacts = (
                bench_path / "{}.html".format(timestamp),
                bench_path / "{}.rerun.json".format(timestamp),
                bench_path / "logs" / timestamp,
            )
            if timestamp in regressions or any(path.exists() for path in revision_artifacts):
                raise FileExistsError("Report revision already exists: {}".format(timestamp))

    def _publication_snapshot(self):
        project_path = Path(self.output_path, self.proj_name)
        paths = [
            Path(self.project_info_path),
            Path(self.output_path, "index.html"),
            Path(self.output_path, "open_{}.sh".format(self.header["time"])),
            project_path / "index.html",
        ]
        for bench in self.bench_list:
            bench_path = project_path / bench
            paths.extend([
                bench_path / "index.html",
                bench_path / "regressions.json",
                bench_path / "{}.html".format(self.header["time"]),
                bench_path / "{}.rerun.json".format(self.header["time"]),
            ])
        snapshot = {}
        for path in paths:
            try:
                snapshot[path] = _read_file_bytes(path)
            except FileNotFoundError:
                snapshot[path] = None
        return snapshot

    def _restore_publication_snapshot(self, snapshot):
        timestamp = self.header["time"]
        project_path = Path(self.output_path, self.proj_name)
        for bench in self.bench_list:
            bench_path = project_path / bench
            for path in (bench_path / "{}.html".format(timestamp), bench_path / "{}.rerun.json".format(timestamp)):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            run_logs_path = bench_path / "logs" / timestamp
            if run_logs_path.is_symlink():
                run_logs_path.unlink()
            else:
                shutil.rmtree(run_logs_path, ignore_errors=True)
        launcher_path = Path(self.output_path, "open_{}.sh".format(timestamp))
        try:
            launcher_path.unlink()
        except FileNotFoundError:
            pass
        for path, contents in snapshot.items():
            if contents is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                _write_bytes_atomic(path, contents)

    def _cleanup_committed_history(self):
        regression_dir = getattr(self.rcfg, "regression_dir", None)
        cleanup_path = (Path(regression_dir, "report_coverage", ".locks", "coverage_cleanup.json")
                        if regression_dir else None)
        if regression_dir is None:
            self._cleanup_committed_history_locked(cleanup_path)
            return
        with coverage_artifact_lock(regression_dir, _COVERAGE_CLEANUP_LOCK_KEY, shared=False):
            self._cleanup_committed_history_locked(cleanup_path)

    def _cleanup_committed_history_locked(self, cleanup_path):
        cleanup_records = []
        if cleanup_path is not None:
            try:
                cleanup_records = _load_json(cleanup_path, [])
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError) as exc:
                self.rcfg.log.warning("Ignoring invalid deferred coverage cleanup file %s: %s", cleanup_path, exc)
        remaining_records = [record for record in cleanup_records if self._coverage_cleanup_pending(record)]
        pending_history_cleanup = self._pending_history_cleanup
        self._pending_history_cleanup = []
        prospective_records = [
            self._coverage_cleanup_record(timestamp, summary)
            for _bench_path, timestamp, summary in pending_history_cleanup
        ]
        remaining_records.extend(record for record in prospective_records if record is not None)
        try:
            for (bench_path, timestamp, summary), prospective_record in zip(pending_history_cleanup,
                                                                            prospective_records):
                try:
                    cleanup_record = self._remove_history_artifacts(bench_path, timestamp, summary)
                    if cleanup_record is None and prospective_record in remaining_records:
                        remaining_records.remove(prospective_record)
                except (OSError, ValueError) as exc:
                    self.rcfg.log.warning("Failed to clean retained report artifacts for %s: %s", timestamp, exc)
        except KeyboardInterrupt:
            self._persist_coverage_cleanup(cleanup_path, remaining_records)
            raise
        self._persist_coverage_cleanup(cleanup_path, remaining_records)

    def _persist_coverage_cleanup(self, cleanup_path, records):
        unique_records = list({
            (record["regression_dir"], record["timestamp"], record["artifact_dir"]): record
            for record in records
        }.values())
        if unique_records and cleanup_path is not None:
            cleanup_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(cleanup_path, unique_records)
            os.chmod(cleanup_path, 0o600)
        elif cleanup_path is not None:
            try:
                cleanup_path.unlink()
            except FileNotFoundError:
                pass

    def _coverage_cleanup_record(self, timestamp, summary):
        artifact_dir = summary.get("coverage_artifact_dir")
        regression_dir = getattr(self.rcfg, "regression_dir", None)
        if not artifact_dir or not regression_dir:
            return None
        return {
            "regression_dir": str(Path(regression_dir).resolve()),
            "timestamp": timestamp,
            "artifact_dir": str(Path(artifact_dir).resolve()),
        }

    def _coverage_cleanup_pending(self, record):
        if not isinstance(record, dict) or any(not isinstance(record.get(key), str) or not record[key]
                                               for key in ("regression_dir", "timestamp", "artifact_dir")):
            self.rcfg.log.warning("Dropping invalid deferred coverage cleanup record: %r", record)
            return False
        timestamp = record["timestamp"]
        if not _is_safe_report_component(timestamp):
            self.rcfg.log.warning("Dropping unsafe deferred coverage cleanup timestamp: %r", timestamp)
            return False
        configured_regression_dir = getattr(self.rcfg, "regression_dir", None)
        if not configured_regression_dir:
            self.rcfg.log.warning("Dropping deferred coverage cleanup without an active regression directory")
            return False
        regression_dir = Path(record["regression_dir"]).resolve()
        configured_regression_dir = Path(configured_regression_dir).resolve()
        if regression_dir != configured_regression_dir:
            self.rcfg.log.warning("Dropping deferred coverage cleanup for a foreign regression directory: %s",
                                  regression_dir)
            return False
        coverage_root = (configured_regression_dir / "report_coverage").resolve()
        candidate = Path(record["artifact_dir"]).resolve()
        try:
            relative_candidate = candidate.relative_to(coverage_root / timestamp)
        except ValueError:
            relative_candidate = None
        if relative_candidate is None or len(relative_candidate.parts) != 1:
            self.rcfg.log.warning("Dropping out-of-root deferred coverage cleanup path: %s", candidate)
            return False
        if not candidate.exists():
            return False
        with coverage_artifact_lock(configured_regression_dir, timestamp, shared=False, blocking=False) as acquired:
            if not acquired:
                return True
            try:
                shutil.rmtree(candidate)
            except FileNotFoundError:
                return False
            except OSError as exc:
                self.rcfg.log.warning("Failed to remove deferred coverage artifact %s: %s", candidate, exc)
                return True
        return False

    def dashboard_data(self):
        """Return latest per-bench summaries for every known project."""
        dashboard = {}
        for project_name, benches in self.project_info.items():
            project_rows = []
            for bench in benches:
                regressions_path = os.path.join(self.output_path, project_name, bench, "regressions.json")
                try:
                    regressions = _load_json(regressions_path, {})
                except (json.JSONDecodeError, ValueError):
                    regressions = {}
                timestamps = _history_timestamps(regressions)
                timestamp = timestamps[-1] if timestamps else ""
                summary = dict(regressions.get(timestamp, {}))
                summary.update({"bench": bench, "timestamp": timestamp})
                project_rows.append(summary)
            dashboard[project_name] = project_rows
        return dashboard

    def render_home_page(self):
        self._refresh_project_info()
        rendered_html = self.HOME_TEMPLATE.render(
            project=self.project_info,
            dashboard=self.dashboard_data(),
        )
        _write_text_atomic(os.path.join(self.output_path, "index.html"), rendered_html)

    def render_bench_page(self):
        self._refresh_project_info()
        project_path = _ensure_child_directories(self.output_path, self.proj_name)
        for bench in self.bench_list:
            _ensure_child_directories(project_path, bench)
        _write_json_atomic(self.project_info_path, self.project_info)
        rendered_html = self.BENCHS_TEMPLATE.render(
            project_name=self.proj_name,
            project=self.project_info,
            bench_summaries=self.dashboard_data().get(self.proj_name, []),
        )
        _write_text_atomic(os.path.join(project_path, "index.html"), rendered_html)

    def write_run_launcher(self, report_url=None):
        """Write an executable that opens this run's immutable report pages."""
        timestamp = self.header["time"]
        targets = []
        for bench in self.bench_list:
            if report_url:
                targets.append("{}/{}/{}/{}.html".format(
                    report_url.rstrip("/"),
                    url_quote(self.proj_name, safe=""),
                    url_quote(bench, safe=""),
                    url_quote(timestamp, safe=""),
                ))
            else:
                report_path = Path(self.output_path, self.proj_name, bench, "{}.html".format(timestamp)).resolve()
                targets.append(report_path.as_uri())

        if not targets:
            return None

        launcher_path = os.path.join(self.output_path, "open_{}.sh".format(timestamp))
        target_lines = "\n".join("    {}".format(shlex.quote(target)) for target in targets)
        launcher = """#!/usr/bin/env bash

set -Eeuo pipefail

REPORT_TARGETS=(
{targets}
)

open_report() {{
    local report_target=$1
    if [ -n "${{BROWSER:-}}" ]; then
        "$BROWSER" "$report_target"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$report_target"
    elif command -v gio >/dev/null 2>&1; then
        gio open "$report_target"
    elif command -v firefox >/dev/null 2>&1; then
        firefox "$report_target"
    elif command -v google-chrome >/dev/null 2>&1; then
        google-chrome "$report_target"
    else
        printf 'ERROR: No browser launcher found. Report: %s\n' "$report_target" >&2
        return 1
    fi
}}

for report_target in "${{REPORT_TARGETS[@]}}"; do
    printf 'Opening Simmer report: %s\n' "$report_target"
    open_report "$report_target"
done
""".format(targets=target_lines)
        _write_text_atomic(launcher_path, launcher)
        os.chmod(launcher_path, 0o755)

        return launcher_path

    def _prune_run_launchers(self):
        try:
            launchers = sorted(Path(self.output_path).glob("open_*.sh"), key=lambda path: path.lstat().st_mtime_ns)
        except OSError as exc:
            self.rcfg.log.warning("Failed to inspect retained report launchers: %s", exc)
            return
        for stale_launcher in launchers[:-MAX_HISTORY]:
            try:
                stale_launcher.unlink()
            except OSError as exc:
                self.rcfg.log.warning("Failed to remove retained report launcher %s: %s", stale_launcher, exc)

    def _copy_logs(self, bench_path, details):
        timestamp = self.header["time"]
        run_logs_path = Path(bench_path, "logs", timestamp)
        logs_list = []

        for row_index, row in enumerate(details[:-1], start=1):
            copied_logs = []
            for log_index, log_path in enumerate(filter(None, row[8].split("|")), start=1):
                source = Path(log_path)
                if not source.is_file():
                    self.rcfg.log.warning("Regression log does not exist: %s", source)
                    continue
                _ensure_child_directories(bench_path, "logs", timestamp)
                destination_name = "{}_{:02d}_{}.log".format(_slug(row[1]), log_index, _slug(source.parent.name))
                destination_path = run_logs_path / destination_name
                shutil.copy2(source, destination_path)
                os.chmod(destination_path, 0o644)
                copied_logs.append(destination_name)

            if not copied_logs:
                continue
            logs_page = "{:03d}_{}.html".format(row_index, _slug(row[1]))
            rendered_logs = self.LOGS_TEMPLATE.render(
                project_name=self.proj_name,
                bench_name=os.path.basename(bench_path),
                logs=copied_logs,
            )
            _write_text_atomic(run_logs_path / logs_page, rendered_logs)
            row[-1] = "{}/{}".format(timestamp, logs_page)
            logs_list.append(["logs/{}/{}".format(timestamp, name) for name in copied_logs])

        return logs_list

    def _remove_history_artifacts(self, bench_path, timestamp, summary):
        if not _is_safe_report_component(timestamp):
            self.rcfg.log.warning("Skipping artifact cleanup for unsafe report timestamp %r", timestamp)
            return
        shutil.rmtree(os.path.join(bench_path, "logs", timestamp), ignore_errors=True)
        history_page = os.path.join(bench_path, "{}.html".format(timestamp))
        if os.path.isfile(history_page):
            os.remove(history_page)

        manifest_name = summary.get("rerun_manifest")
        if manifest_name == "{}.rerun.json".format(timestamp):
            manifest_path = os.path.join(bench_path, manifest_name)
            if os.path.isfile(manifest_path):
                os.remove(manifest_path)

        cleanup_record = self._coverage_cleanup_record(timestamp, summary)
        if cleanup_record is not None:
            if self._coverage_cleanup_pending(cleanup_record):
                self.rcfg.log.warning("Coverage artifact is still in use; deferring cleanup: %s",
                                      cleanup_record["artifact_dir"])
                return cleanup_record
        return None

    def _prune_history(self, bench_path, regressions):
        for timestamp in list(regressions):
            if not _is_safe_report_component(timestamp):
                self.rcfg.log.warning("Dropping unsafe report timestamp %r from history", timestamp)
                del regressions[timestamp]
        timestamps = _history_timestamps(regressions)
        removed = []
        excess = max(0, len(timestamps) - MAX_HISTORY)
        removable = [timestamp for timestamp in timestamps if timestamp != self.header["time"]]
        for timestamp in removable[:excess]:
            removed.append((timestamp, regressions[timestamp]))
            del regressions[timestamp]
        return _history_timestamps(regressions), removed

    def _raw_trd_for_bench(self, bench):
        rows = []
        current_bench = None
        for row in self.raw_trd:
            if row[0]:
                current_bench = row[0]
            if current_bench == bench:
                rows.append(row[:])
        return rows

    def _write_rerun_manifest(self, bench_path, bench, coverage, context):
        failed_tests = context.get("failed_tests", [])
        if not failed_tests:
            return None, None
        manifest_name = "{}.rerun.json".format(self.header["time"])
        manifest_path = os.path.abspath(os.path.join(bench_path, manifest_name))
        manifest = {
            "schema_version": 1,
            "webroot_dir": os.path.abspath(self.webroot_dir),
            "project_dir": context["project_dir"],
            "regression_dir": context["regression_dir"],
            "header": self.header,
            "trd": self._raw_trd_for_bench(bench),
            "category_stats": self.category_stats,
            "coverage": dict(context["coverage"], metrics=coverage),
            "failed_tests": failed_tests,
        }
        _write_json_atomic(manifest_path, manifest)
        os.chmod(manifest_path, 0o600)
        return manifest_name, shlex.join(["simmer", "--rerun-report", manifest_path])

    def render_regression_page(self):
        for bench, source_details in self.trd.items():
            coverage_enabled = bool(self.header.get("coverage_enabled"))
            coverage = self.cov.get(bench, {}) if coverage_enabled else {}
            cc_info = coverage.get("cc", {})
            cf_info = coverage.get("cf", {})
            bench_path = _ensure_child_directories(self.output_path, self.proj_name, bench)
            details = [row[:] + [""] for row in source_details]
            logs_list = self._copy_logs(bench_path, details)
            rerun_context = self.rerun_context.get(bench, {})
            rerun_manifest, rerun_command = self._write_rerun_manifest(bench_path, bench, coverage, rerun_context)

            test_rows = source_details[1:-1]
            passed = sum(_safe_int(row[3]) for row in test_rows)
            skipped = sum(_safe_int(row[4]) for row in test_rows)
            failed = sum(_safe_int(row[5]) for row in test_rows)
            total = sum(_safe_int(row[6]) for row in test_rows)
            regression_summary = {
                "passed": passed,
                "skipped": skipped,
                "failed": failed,
                "total": total,
                "passrate": round(passed / total * 100, 2) if total else 0.0,
                "coverage_enabled": coverage_enabled,
                "cov_total": _coverage_value(coverage.get("total")),
                "cov_code": _coverage_metric(coverage, "cc"),
                "cov_func": _coverage_metric(coverage, "cf"),
                "cov_vendor_score": _coverage_value(coverage.get("vendor_score")),
                "logs": logs_list,
                "revision_of": self.header.get("revision_of"),
                "rerun_manifest": rerun_manifest,
                "coverage_artifact_dir": rerun_context.get("coverage", {}).get("artifact_dir"),
            }

            json_file_path = os.path.join(bench_path, "regressions.json")
            try:
                regressions = _load_json(json_file_path, {})
            except (json.JSONDecodeError, ValueError) as exc:
                self.rcfg.log.warning("Ignoring invalid regression history %s: %s", json_file_path, exc)
                regressions = {}
            regression_summary["publication_order"] = max(
                (_safe_int(summary.get("publication_order")) for summary in regressions.values()), default=0) + 1
            regressions[self.header["time"]] = regression_summary
            remain_list, removed_history = self._prune_history(bench_path, regressions)
            passrate_list, cov_total_list, cov_code_list, cov_func_list = regression_history_series(
                regressions, remain_list)
            history = [dict(regressions[timestamp], timestamp=timestamp) for timestamp in reversed(remain_list)]

            rendered_html = self.REGRESSION_REPORT_TEMPLATE.render(
                header=self.header,
                bench_name=bench,
                regression_details=details,
                regressions=remain_list,
                history=history,
                latest_summary=regression_summary,
                passrate_list=passrate_list,
                cov_total_list=cov_total_list,
                cov_code_list=cov_code_list,
                cov_func_list=cov_func_list,
                project=self.project_info,
                cc_info=cc_info,
                cf_info=cf_info,
                rerun_command=rerun_command,
                processed_category_stats=self.processed_category_stats,
            )

            index_path = os.path.join(bench_path, "index.html")
            _write_text_atomic(os.path.join(bench_path, "{}.html".format(self.header["time"])), rendered_html)
            _write_json_atomic(json_file_path, regressions)
            _write_text_atomic(index_path, rendered_html)
            for timestamp, summary in removed_history:
                self._pending_history_cleanup.append((bench_path, timestamp, summary))
