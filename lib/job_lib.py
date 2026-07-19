#!/usr/bin/env python
"""Definitions for Job-running and Job-related classes."""

################################################################################
# standard lib imports
import bisect
import ast
import datetime
import enum
import os
import signal
import socket
import subprocess
import threading
import time

from lib.runtime_options import normalize_test_runtime_options


def _positive_integer(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _lsf_host_slots(value, hostname):
    tokens = (value or "").split()
    if len(tokens) < 2 or len(tokens) % 2:
        return None
    pairs = []
    for index in range(0, len(tokens), 2):
        slots = _positive_integer(tokens[index + 1])
        if slots is None:
            return None
        pairs.append((tokens[index], slots))
    if len(pairs) == 1:
        return pairs[0][1]

    local_names = {hostname.lower(), hostname.split('.', 1)[0].lower()}
    for host, slots in pairs:
        if host.lower() in local_names or host.split('.', 1)[0].lower() in local_names:
            return slots
    return min(slots for _, slots in pairs)


def _lsf_host_list_slots(value, hostname):
    hosts = (value or "").split()
    if not hosts:
        return None
    local_names = {hostname.lower(), hostname.split('.', 1)[0].lower()}
    local_slots = sum(1 for host in hosts
                      if host.lower() in local_names or host.split('.', 1)[0].lower() in local_names)
    if local_slots:
        return local_slots
    slots_by_host = {}
    for host in hosts:
        short_name = host.split('.', 1)[0].lower()
        slots_by_host[short_name] = slots_by_host.get(short_name, 0) + 1
    return min(slots_by_host.values())


def detect_allocated_cpus(environment=None, hostname=None, affinity_getter=None, host_cpu_count=None):
    environment = os.environ if environment is None else environment
    hostname = hostname or socket.gethostname()
    affinity_getter = affinity_getter if affinity_getter is not None else getattr(os, "sched_getaffinity", None)

    affinity_count = None
    if affinity_getter is not None:
        try:
            affinity_count = len(affinity_getter(0)) or None
        except OSError:
            pass

    host_slots = _lsf_host_slots(environment.get("LSB_MCPU_HOSTS"), hostname)
    if host_slots is None:
        host_slots = _lsf_host_list_slots(environment.get("LSB_HOSTS"), hostname)
        host_source = "LSB_HOSTS"
    else:
        host_source = "LSB_MCPU_HOSTS"
    if host_slots is not None:
        if affinity_count is not None and affinity_count < host_slots:
            return affinity_count, "{} capped by CPU affinity".format(host_source)
        return host_slots, host_source

    slurm_cpus = _positive_integer(environment.get("SLURM_CPUS_PER_TASK"))
    if slurm_cpus is not None:
        if affinity_count is not None and affinity_count < slurm_cpus:
            return affinity_count, "SLURM_CPUS_PER_TASK capped by CPU affinity"
        return slurm_cpus, "SLURM_CPUS_PER_TASK"

    lsf_total = _positive_integer(environment.get("LSB_DJOB_NUMPROC"))
    if lsf_total is not None:
        if affinity_count is not None and affinity_count < lsf_total:
            return affinity_count, "LSB_DJOB_NUMPROC capped by CPU affinity"
        if lsf_total == 1:
            return 1, "LSB_DJOB_NUMPROC"
        return 1, "LSB_DJOB_NUMPROC without per-host allocation (conservative)"

    if affinity_count is not None:
        return min(affinity_count, 8), "CPU affinity fallback (capped at 8)"

    host_cpu_count = os.cpu_count() if host_cpu_count is None else host_cpu_count
    return min(host_cpu_count or 1, 8), "host CPU count fallback (capped at 8)"


@enum.unique
class JobStatus(enum.Enum):
    NOT_STARTED = 0
    TO_BE_BYPASSED = 1
    PASSED = 10
    FAILED = 11
    SKIPPED = 12 # Due to upstream dependency failures, this job was not run
    BYPASSED = 13 # Skipped due to a norun directive, allows downstream jobs to execute assuming the outputs of this job have been previously created

    @property
    def completed(self):
        return self.value >= self.__class__.PASSED.value

    @property
    def successful(self):
        return self in [self.PASSED, self.BYPASSED]

    def __str__(self):
        return self.name

    def _error(self, new_state):
        raise ValueError("May not go from {} to {}".format(self, new_state))

    def update(self, new_state):
        """Check for legal transitions.
        This doesn't actually change this instance, an assignment must be done with retval.
        Example:

          self._jobstatus = self._jobstatus.update(new_jobstatus)
        """
        if new_state == self.NOT_STARTED:
            self._error(new_state)
        if self == new_state:
            pass # No actual transition, ignore
        elif self == self.NOT_STARTED:
            pass # Any transition is legal
        elif self == self.TO_BE_BYPASSED:
            if new_state == self.PASSED:
                return self.BYPASSED # In the case of a bypassed job, part of
                # the job may still be run with a
                # placeholder command. Downstream logic
                # may mark this as passed, but keep
                # bypassed for final formatting.
            if new_state not in (self.FAILED, self.SKIPPED):
                self._error(new_state)
        elif self == self.PASSED:
            if new_state != self.FAILED:
                self._error(new_state)
        elif self == self.FAILED:
            self._error(new_state)
        elif self == self.SKIPPED:
            if new_state != self.FAILED:
                self._error(new_state)
        elif self == self.BYPASSED:
            if new_state != self.FAILED:
                self._error(new_state)
        else:
            raise ValueError("Unknown current state")
        return new_state


class JobCancelledError(RuntimeError):
    """Raised when scheduler shutdown cancels a job before launch completes."""


class Job():

    def __init__(self, rcfg, name):
        self.rcfg = rcfg # Regression cfg object
        self.name = name

        # String set by derived class of the directory to run this job in
        self.job_dir = None

        self.job_lib = None

        self.job_start_time = None
        self.job_stop_time = None

        self._jobstatus = JobStatus.NOT_STARTED
        self._cancel_event = threading.Event()

        self.suppress_output = False
        # FIXME need to implement a way to actually override this
        # FIXME add multiplier for --gui
        #self.timeout = 12.25 # Float hours
        self.timeout = rcfg.options.timeout

        self.priority = -3600 # Not sure that making this super negative is necessary if we log more stuff
        self.log = self.rcfg.log
        self.log.debug("%s priority=%d", self, self.priority)

        # Implement both directions to make traversal of graph easier
        self._dependencies = [] # Things this job is dependent on
        self._children = [] # Jobs that depend on this jop

    @property
    def execution_mode(self):
        """Execution class used by the scheduler."""
        return "exclusive"

    def __lt__(self, other):
        return self.priority < other.priority

    @property
    def jobstatus(self):
        return self._jobstatus

    @jobstatus.setter
    def jobstatus(self, new_jobstatus):
        self._jobstatus = self._jobstatus.update(new_jobstatus)

    def add_dependency(self, dep):
        if not dep:
            self.log.error("%s added null dep", self)
        else:
            self._dependencies.append(dep)
        dep._children.append(self)
        dep.increase_priority(self.priority)

    def increase_priority(self, value):
        # Recurse up with new value
        self.priority += value
        for dep in self._dependencies:
            dep.increase_priority(value)

    def pre_run(self):
        self.log.info("Starting %s %s", self.__class__.__name__, self.name)
        self.job_start_time = datetime.datetime.now()

        if not os.path.exists(self.job_dir):
            self.log.debug("Creating job_dir: %s", self.job_dir)
            os.mkdir(self.job_dir)

    def post_run(self):
        self.job_stop_time = datetime.datetime.now()
        self.log.debug("post_run %s %s duration %s", self.__class__.__name__, self.name, self.duration_s)
        #self.completed = True

    def launch_failed(self, exc):
        """Record a failure that occurs before the subprocess starts."""
        run = getattr(self.rcfg, "simmer_results_run", None)
        if run is not None:
            run.setdefault("launch_failures", []).append({
                "job": repr(self),
                "error_message": str(exc),
            })

    def post_run_failed(self, exc):
        self.error_message = str(exc)

    def incomplete_shutdown(self, message):
        """Record failure without releasing resources that a live process may still use."""
        self.job_stop_time = datetime.datetime.now()
        self.jobstatus = JobStatus.FAILED
        self.error_message = message

    def cancel(self):
        """Release job-owned resources after an explicit scheduler shutdown."""

    def request_cancel(self):
        """Request cooperative cancellation of launch-time work."""
        self._cancel_event.set()

    def wait_for_cancel(self, timeout):
        """Wait up to timeout seconds for cooperative cancellation."""
        return self._cancel_event.wait(timeout)

    @property
    def cancel_requested(self):
        return self._cancel_event.is_set()

    def raise_if_cancelled(self):
        if self.cancel_requested:
            raise JobCancelledError("Scheduler shutdown cancelled {}".format(self))

    @property
    def duration_s(self):
        try:
            delta = self.job_stop_time - self.job_start_time
        except TypeError:
            return 0
        return delta.total_seconds()


class JobRunner():

    def __init__(self, job, manager):
        self.job = job
        self.job.job_lib = self

        self.manager = manager

        self.done = False
        self.log = job.log

    def check_for_done(self):
        raise NotImplementedError

    @property
    def returncode(self):
        raise NotImplementedError

    def print_stderr_if_failed(self):
        raise NotImplementedError


class SubprocessJobRunner(JobRunner):

    TERM_GRACE_SECONDS = 10
    KILL_GRACE_SECONDS = 2
    OWNERSHIP_GRACE_SECONDS = 30

    def __init__(self, job, manager):
        super(SubprocessJobRunner, self).__init__(job, manager)
        kwargs = {'shell': True, 'start_new_session': True}
        self._timed_out = False
        self._orphaned_process_group = False
        self._term_deadline = None
        self._kill_deadline = None
        self._kill_sent = False
        self._kill_failure_reported = False
        self._ownership_deadline = None
        self.shutdown_incomplete = False
        self._kill_lock = threading.Lock()
        self._timeout_start = None
        self._paused = False
        self._paused_at = None
        self._pause_intervals = []
        self.log = job.log

        if self.job.suppress_output or self.job.rcfg.options.no_stdout:
            self.stdout_log_path = self._get_stdout_capture_path()
            self.stderr_log_path = os.path.join(self.job.job_dir, "stderr.log")
            self.stdout_fp = open(self.stdout_log_path, 'w')
            self.stderr_fp = open(self.stderr_log_path, 'w')
            kwargs['stdout'] = self.stdout_fp
            kwargs['stderr'] = self.stderr_fp
        self._start_time = datetime.datetime.now()
        try:
            self._p = subprocess.Popen(self.job.main_cmdline, **kwargs)
            self._process_group_id = self._p.pid
        except Exception:
            for stream in (getattr(self, "stdout_fp", None), getattr(self, "stderr_fp", None)):
                if stream:
                    stream.close()
            raise

    def _signal_process_group(self, sig):
        try:
            os.killpg(self._process_group_id, sig)
        except ProcessLookupError:
            pass

    def _sidecar_process_group_ids(self):
        path = getattr(self.job, "sidecar_process_groups_path", None)
        if not path:
            return ()
        try:
            with open(path, "r", encoding="ascii") as filep:
                registrations = []
                for line in filep:
                    fields = line.split()
                    if fields:
                        registrations.append((int(fields[0]), fields[1] if len(fields) > 1 else None))
        except (OSError, ValueError):
            return ()
        return tuple(
            sorted({
                group_id
                for group_id, start_time in registrations if group_id > 1 and group_id != self._process_group_id
                and self._process_group_belongs_to_runner_session(group_id, start_time)
            }))

    @staticmethod
    def _linux_process_identity(process_id):
        with open("/proc/{}/stat".format(process_id), "r", encoding="ascii") as filep:
            stat_fields = filep.read().rsplit(")", 1)[1].split()
        return stat_fields[0], int(stat_fields[2]), int(stat_fields[3]), stat_fields[19]

    def _process_group_has_live_member(self, group_id, session_id=None):
        try:
            proc_entries = os.scandir("/proc")
        except OSError:
            return None
        with proc_entries:
            for entry in proc_entries:
                if not entry.name.isdigit():
                    continue
                try:
                    state, process_group, process_session, _ = self._linux_process_identity(entry.name)
                except (OSError, ValueError, IndexError):
                    continue
                if process_group == group_id and state != "Z" and (session_id is None or process_session == session_id):
                    return True
        return False

    def _process_group_belongs_to_runner_session(self, group_id, expected_start_time=None):
        try:
            state, process_group, session_id, start_time = self._linux_process_identity(group_id)
            if expected_start_time is not None and start_time != expected_start_time:
                return False
            if state != "Z" and process_group == group_id and session_id == self._process_group_id:
                return True
        except (OSError, ValueError, IndexError):
            pass
        return bool(self._process_group_has_live_member(group_id, self._process_group_id))

    def _signal_sidecar_process_groups(self, sig):
        for group_id in self._sidecar_process_group_ids():
            try:
                os.killpg(group_id, sig)
            except ProcessLookupError:
                pass

    def _sidecar_process_group_exists(self):
        for group_id in self._sidecar_process_group_ids():
            try:
                os.killpg(group_id, 0)
            except ProcessLookupError:
                continue
            return True
        return False

    def _process_group_exists(self):
        live_member = self._process_group_has_live_member(self._process_group_id)
        if live_member is not None:
            return live_member
        try:
            os.killpg(self._process_group_id, 0)
        except ProcessLookupError:
            return False
        return True

    def _managed_process_groups_exist(self):
        return self._process_group_exists() or self._sidecar_process_group_exists()

    def _wait_for_process_group_exit(self, deadline):
        while self._managed_process_groups_exist() and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self._managed_process_groups_exist()

    def _close_output_streams(self):
        for stream in (getattr(self, "stdout_fp", None), getattr(self, "stderr_fp", None)):
            if stream and not stream.closed:
                stream.close()
        if not getattr(self, "shutdown_incomplete", False) and not self._sidecar_process_group_exists():
            path = getattr(self.job, "sidecar_process_groups_path", None)
            if path:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass

    def _send_sigkill(self, message, now):
        if self._kill_sent:
            return
        self.log.error(message, self.job)
        self._signal_process_group(signal.SIGKILL)
        self._signal_sidecar_process_groups(signal.SIGKILL)
        self._kill_sent = True
        self._kill_deadline = now + datetime.timedelta(seconds=self.KILL_GRACE_SECONDS)
        self._ownership_deadline = self._kill_deadline + datetime.timedelta(seconds=self.OWNERSHIP_GRACE_SECONDS)

    def _ownership_wait_expired(self, now):
        ownership_deadline = getattr(self, "_ownership_deadline", None)
        if ownership_deadline is None:
            ownership_deadline = self._kill_deadline + datetime.timedelta(seconds=self.OWNERSHIP_GRACE_SECONDS)
            self._ownership_deadline = ownership_deadline
        if now < ownership_deadline:
            if not getattr(self, "_kill_failure_reported", False):
                self.log.error("%s process group still exists after SIGKILL grace period", self.job)
                self._kill_failure_reported = True
            return False
        self.log.error("%s process group could not be reaped; preserving artifacts and stopping scheduling", self.job)
        self.shutdown_incomplete = True
        self._close_output_streams()
        return True

    def _paused_duration_since(self, timeout_start, now):
        duration = datetime.timedelta()
        intervals = list(getattr(self, "_pause_intervals", ()))
        if getattr(self, "_paused", False) and self._paused_at is not None:
            intervals.append((self._paused_at, now))
        for paused_at, resumed_at in intervals:
            overlap_start = max(timeout_start, paused_at)
            overlap_end = min(now, resumed_at)
            if overlap_end > overlap_start:
                duration += overlap_end - overlap_start
        return duration

    def _get_stdout_capture_path(self):
        """Avoid clobbering simulator-owned stdout.log files.

        Test jobs can ask the simulator itself to write `stdout.log` via its own
        logging switch (for example VCS `-l stdout.log`). In that case, keep the
        subprocess wrapper output separate so the simulator log remains
        authoritative.
        """
        simulator_log_path = getattr(self.job, "_log_path", None)
        default_stdout_log_path = os.path.join(self.job.job_dir, "stdout.log")
        if simulator_log_path == default_stdout_log_path:
            return os.path.join(self.job.job_dir, "job_runner.stdout.log")
        return default_stdout_log_path

    def check_for_done(self):
        if self.done:
            return self.done
        try:
            result = self._check_for_done()
        except Exception as exc:
            self.log.error("Job failed %s:\n%s", self.job, exc)
            self._signal_process_group(signal.SIGKILL)
            self._signal_sidecar_process_groups(signal.SIGKILL)
            direct_child_reaped = True
            try:
                self._p.wait(timeout=self.KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                direct_child_reaped = False
                self._p.kill()
                try:
                    self._p.wait(timeout=self.KILL_GRACE_SECONDS)
                    direct_child_reaped = True
                except subprocess.TimeoutExpired:
                    pass
            try:
                group_reaped = self._wait_for_process_group_exit(time.monotonic() + self.KILL_GRACE_SECONDS)
                self.shutdown_incomplete = not direct_child_reaped or not group_reaped
            except Exception as cleanup_exc:
                self.log.error("Could not verify process cleanup for %s: %s", self.job, cleanup_exc)
                self.shutdown_incomplete = True
            self._close_output_streams()
            result = True
        if result:
            self.done = result
        return result

    def _check_for_done(self):
        if self._p.poll() is not None:
            now = datetime.datetime.now()
            if not self._managed_process_groups_exist():
                self._close_output_streams()
                return True
            if not self._timed_out and not self._orphaned_process_group:
                self._orphaned_process_group = True
                self._term_deadline = now + datetime.timedelta(seconds=self.TERM_GRACE_SECONDS)
                self.log.error("%s left background processes after its shell exited; sending SIGTERM", self.job)
                self._signal_process_group(signal.SIGTERM)
                self._signal_sidecar_process_groups(signal.SIGTERM)
                return False
            if not self._kill_sent and now >= self._term_deadline:
                self._send_sigkill("%s left background processes after SIGTERM; sending SIGKILL", now)
                return False
            if self._kill_sent and now < self._kill_deadline:
                return False
            if self._kill_sent:
                return self._ownership_wait_expired(now)

        now = datetime.datetime.now()
        if getattr(self, "_paused", False):
            return False
        if self._timed_out:
            if not self._kill_sent and now >= self._term_deadline:
                self._send_sigkill("%s did not exit after SIGTERM; sending SIGKILL", now)
            elif self._kill_sent and now >= self._kill_deadline:
                return self._ownership_wait_expired(now)
            return False

        timeout_start = self._start_time
        timeout_start_path = getattr(self.job, "timeout_start_path", None)
        if timeout_start_path:
            timeout_start = getattr(self, "_timeout_start", None)
            if timeout_start is None:
                try:
                    timeout_start = datetime.datetime.fromtimestamp(os.path.getmtime(timeout_start_path))
                except OSError:
                    return False
                self._timeout_start = timeout_start
        if timeout_start is None:
            return False
        timeout_start += self._paused_duration_since(timeout_start, now)
        delta = now - timeout_start
        if self.job.timeout > 0 and delta > datetime.timedelta(hours=self.job.timeout):
            self.log.error("%s exceeded timeout value of %s; sending SIGTERM", self.job, self.job.timeout)
            self._timed_out = True
            self._term_deadline = now + datetime.timedelta(seconds=self.TERM_GRACE_SECONDS)
            self._signal_process_group(signal.SIGTERM)
            self._signal_sidecar_process_groups(signal.SIGTERM)
            stderr_log_path = getattr(self, "stderr_log_path", os.path.join(self.job.job_dir, "stderr.log"))
            stdout_log_path = getattr(self, "stdout_log_path", os.path.join(self.job.job_dir, "stdout.log"))
            with open(stderr_log_path, 'a') as filep:
                filep.write("%%E- %s exceeded timeout value of %s (SIGTERM sent)" % (self.job, self.job.timeout))
            with open(stdout_log_path, 'a') as filep:
                filep.write("%%E- %s exceeded timeout value of %s (SIGTERM sent)" % (self.job, self.job.timeout))
            return False
        return False

    @property
    def returncode(self):
        if (self._timed_out or self._orphaned_process_group) and self._p.returncode in (None, 0):
            return -signal.SIGTERM
        return self._p.returncode

    def flush_output_streams(self):
        """Flush parent-owned output streams before an interactive state change."""
        for stream in (getattr(self, "stdout_fp", None), getattr(self, "stderr_fp", None)):
            if stream and not stream.closed:
                stream.flush()

    def pause(self):
        """Pause the subprocess group without consuming its timeout budget."""
        with self._kill_lock:
            if self.done or self._timed_out or self._p.poll() is not None:
                return False
            if getattr(self, "_paused", False):
                return True
            self._paused = True
            self._paused_at = datetime.datetime.now()
            self._signal_process_group(signal.SIGSTOP)
            self._signal_sidecar_process_groups(signal.SIGSTOP)
            self.flush_output_streams()
            return True

    def resume(self):
        """Resume a subprocess group paused by :meth:`pause`."""
        with self._kill_lock:
            if not self._paused:
                return False
            now = datetime.datetime.now()
            self._signal_sidecar_process_groups(signal.SIGCONT)
            self._signal_process_group(signal.SIGCONT)
            self._pause_intervals.append((self._paused_at, now))
            self._paused = False
            self._paused_at = None
            return True

    def kill(self):
        """Terminate the complete subprocess group and synchronously reap it."""
        with self._kill_lock:
            if getattr(self, "_paused", False):
                now = datetime.datetime.now()
                self._signal_sidecar_process_groups(signal.SIGCONT)
                self._signal_process_group(signal.SIGCONT)
                self._pause_intervals.append((self._paused_at, now))
                self._paused = False
                self._paused_at = None
            self._signal_process_group(signal.SIGTERM)
            self._signal_sidecar_process_groups(signal.SIGTERM)
            term_deadline = time.monotonic() + self.TERM_GRACE_SECONDS
            try:
                self._p.wait(timeout=self.TERM_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass

            if not self._wait_for_process_group_exit(term_deadline):
                self.log.warning("%s did not exit after SIGTERM; sending SIGKILL", self.job)
                self._signal_process_group(signal.SIGKILL)
                self._signal_sidecar_process_groups(signal.SIGKILL)
                self._kill_sent = True

            direct_child_reaped = True
            try:
                self._p.wait(timeout=self.KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                # A process outside the new session cannot be reached through
                # the process-group signal. Reap the shell as a final fallback.
                direct_child_reaped = False
                self._p.kill()
                try:
                    self._p.wait(timeout=self.KILL_GRACE_SECONDS)
                    direct_child_reaped = True
                except subprocess.TimeoutExpired:
                    pass
            group_exited = self._wait_for_process_group_exit(time.monotonic() + self.KILL_GRACE_SECONDS)
            if not direct_child_reaped or not group_exited:
                self.log.warning("%s process group or direct child still exists after SIGKILL", self.job)
                self.shutdown_incomplete = True
            self._close_output_streams()
            self.done = True
            return direct_child_reaped and group_exited


class JobManager():
    """Manages multiple concurrent jobs"""
    POLL_SLEEP_SECONDS = 0.25
    ACTIVE_KILL_JOIN_SECONDS = (SubprocessJobRunner.TERM_GRACE_SECONDS + 2 * SubprocessJobRunner.KILL_GRACE_SECONDS + 1)
    SHUTDOWN_JOIN_SECONDS = ACTIVE_KILL_JOIN_SECONDS

    def __init__(self, options, log):
        self.log = log
        if options['idle_print_seconds'] < 1:
            raise ValueError("idle_print_seconds must be positive")
        self.idle_print_interval = datetime.timedelta(seconds=options['idle_print_seconds'])
        self.active_job_limit = int(options.get('active_job_limit', 1))
        if self.active_job_limit < 1:
            raise ValueError("active_job_limit must be positive")

        self._quit_count = options['quit_count']
        if self._quit_count < 1:
            raise ValueError("quit_count must be positive")
        self._error_count = 0
        self._done_grace_exit = False
        self.exited_prematurely = False
        self._interrupted_jobs = []
        self._shutdown_incomplete = False
        self._paused = False

        # Jobs must transition from todo->ready->active->done

        # These are jobs ready to be run, but may not dependencies filled yet
        # This list is maintained in sorted priority order
        self._todo = []

        # Jobs ready to launch (all dependencies met)
        # This list is maintained in sorted priority order
        self._ready = []

        # Jobs launched but not yet complete
        self._active = []

        # Jobs whose subprocess exited and whose post-run hook still owns its
        # compile or simulation directory.
        self._finalizing = []

        # Completed jobs
        self._done = []

        self._skipped = []

        # Every queue transition and scheduler lifecycle flag is protected by
        # this condition. Hooks and subprocess operations always run outside it.
        self._condition = threading.Condition(threading.RLock())
        self._launching = []

        self._run_jobs_thread = threading.Thread(name="_run_jobs", target=self._run_jobs, daemon=True)
        self._run_jobs_thread.daemon = True
        self._run_jobs_thread_active = True
        self._run_jobs_thread.start()

        self.job_lib_type = SubprocessJobRunner

        self._last_done_or_idle_print = datetime.datetime.now()

    def _print_state(self, log_fn):
        with self._condition:
            self._print_state_locked(log_fn)

    def _print_state_locked(self, log_fn):
        job_queues = ["_todo", "_ready", "_launching", "_active", "_finalizing", "_done", "_skipped"]
        for jq in job_queues:
            log_fn("%s: %s", jq, list(getattr(self, jq)))

    def _run_jobs(self):
        while True:
            with self._condition:
                if not self._run_jobs_thread_active:
                    return
                self._move_todo_to_ready_locked()
                job_to_launch = self._take_ready_job_locked()
                active_jobs = list(self._active)
                self._condition.notify_all()
                if job_to_launch is None and not active_jobs:
                    self._condition.wait()
                    continue

            if job_to_launch is not None:
                self._launch_job(job_to_launch)
                continue

            completed_job = None
            for job in active_jobs:
                if job.job_lib.check_for_done():
                    completed_job = job
                    break

            if completed_job is not None:
                if getattr(completed_job.job_lib, "shutdown_incomplete", False):
                    self._record_incomplete_shutdown(completed_job)
                    continue
                with self._condition:
                    if not self._run_jobs_thread_active:
                        return
                    if completed_job not in self._active:
                        continue
                    self._active.remove(completed_job)
                    self._finalizing.append(completed_job)
                    self._condition.notify_all()
                self._complete_job(completed_job)
                continue

            now = datetime.datetime.now()
            with self._condition:
                if now - self._last_done_or_idle_print > self.idle_print_interval:
                    self._last_done_or_idle_print = now
                    self._print_state_locked(self.log.info)
                self._condition.wait(timeout=self.POLL_SLEEP_SECONDS)

    def _move_children_to_skipped_locked(self, job):
        for child in job._children:
            self.log.info("Skipping job %s due to dependency (%s) failure", child, job)
            try:
                self._todo.remove(child)
                child.jobstatus = JobStatus.SKIPPED
            except ValueError:
                # Initially, this was a nice sanity check, but it doesn't always hold true
                # See azure #924
                # if child not in self._skipped:
                #    raise ValueError("Couldn't find child job to mark as skipped")
                continue
            self._skipped.append(child)
            self._move_children_to_skipped_locked(child)

    def _move_children_to_skipped(self, job):
        """Compatibility entry point for callers outside scheduler transitions."""
        with self._condition:
            self._move_children_to_skipped_locked(job)
            self._condition.notify_all()

    def _move_todo_to_ready_locked(self):
        self._print_state_locked(self.log.debug)
        jobs_that_advanced_state = []
        for i, job in enumerate(self._todo):
            if len(job._dependencies) == 0:
                # There are no dependencies
                bisect.insort_right(self._ready, job)
                jobs_that_advanced_state.append(i)
            else:
                all_dependencies_are_done = all([dep.jobstatus.completed for dep in job._dependencies])
                if not all_dependencies_are_done:
                    continue
                all_dependencies_passed = all([dep.jobstatus.successful for dep in job._dependencies])
                if all_dependencies_passed:
                    bisect.insort_right(self._ready, job)
                    jobs_that_advanced_state.append(i)
                else:
                    self.log.error("Skipping job %s due dependency failure", job)
                    jobs_that_advanced_state.append(i)
                    self._skipped.append(job)
                    job.jobstatus = JobStatus.SKIPPED

        # Can't iterate and remove in list at the same time easily
        for i in reversed(jobs_that_advanced_state):
            self._todo.pop(i)

    def _can_launch_locked(self, job):
        running_jobs = self._active + self._launching
        if job.execution_mode == "exclusive":
            return len(running_jobs) == 0
        if job.execution_mode != "parallel":
            raise ValueError("Unknown execution mode '{}'".format(job.execution_mode))
        if any(active_job.execution_mode != "parallel" for active_job in running_jobs):
            return False
        return len(running_jobs) < self.active_job_limit

    def _take_ready_job_locked(self):
        self._print_state_locked(self.log.debug)
        if self._paused:
            return None
        for index, job in enumerate(self._ready):
            if self._can_launch_locked(job):
                self._ready.pop(index)
                self._launching.append(job)
                return job
        return None

    def _launch_job(self, job):
        try:
            job.raise_if_cancelled()
            job.pre_run()
            job.raise_if_cancelled()
            self.log.debug("%s priority: %d", job, job.priority)
            runner = self.job_lib_type(job, self)
        except JobCancelledError as exc:
            self.log.info("%s", exc)
            job.job_stop_time = datetime.datetime.now()
            try:
                if not job.jobstatus.completed:
                    job.jobstatus = JobStatus.SKIPPED
                job.cancel()
            except (Exception, SystemExit) as cancel_exc:
                self.log.error("Could not cancel launch resources for %s: %s", job, cancel_exc)
            with self._condition:
                if job in self._launching:
                    self._launching.remove(job)
                self._skipped.append(job)
                self._condition.notify_all()
            return
        except (Exception, SystemExit) as exc:
            self.log.error("%s launch_failed(): %s", job, exc)
            job.job_stop_time = datetime.datetime.now()
            job.jobstatus = JobStatus.FAILED
            try:
                job.launch_failed(exc)
            except (Exception, SystemExit) as record_exc:
                self.log.error("Could not record launch failure for %s: %s", job, record_exc)
            with self._condition:
                self._launching.remove(job)
                self._error_count += 1
                self._move_children_to_skipped_locked(job)
                if self._error_count >= self._quit_count:
                    self._graceful_exit_locked()
                self._done.append(job)
                self._last_done_or_idle_print = datetime.datetime.now()
                self._condition.notify_all()
            return

        cancel_runner = False
        pause_runner = False
        with self._condition:
            self._launching.remove(job)
            if self._run_jobs_thread_active:
                self._active.append(job)
                pause_runner = self._paused
            else:
                cancel_runner = True
            self._condition.notify_all()
        if pause_runner:
            try:
                runner.pause()
            except Exception as exc:
                self.log.error("Could not pause newly launched runner for %s: %s", job, exc)
            with self._condition:
                resume_runner = not self._paused
            if resume_runner:
                try:
                    runner.resume()
                except Exception as exc:
                    self.log.error("Could not resume newly launched runner for %s: %s", job, exc)
        if cancel_runner:
            runner_stopped = False
            try:
                runner_stopped = runner.kill() is not False
            except Exception as exc:
                self.log.error("Could not stop runner launched during shutdown for %s: %s", job, exc)
            if runner_stopped:
                try:
                    job.cancel()
                except Exception as exc:
                    runner_stopped = False
                    self.log.error("Could not release launch resources for %s: %s", job, exc)
            if not runner_stopped:
                with self._condition:
                    self._shutdown_incomplete = True
                    self._condition.notify_all()

    def _complete_job(self, job):
        self.log.debug("%s body done", job)
        try:
            job.post_run()
        except (Exception, SystemExit) as exc:
            self.log.error("%s post_run_failed():\n%s", job, exc)
            job.job_stop_time = datetime.datetime.now()
            job.jobstatus = JobStatus.FAILED
            try:
                job.post_run_failed(exc)
            except (Exception, SystemExit) as record_exc:
                self.log.error("%s failed to record post_run failure:\n%s", job, record_exc)

        with self._condition:
            if not job.jobstatus.successful:
                self._error_count += 1
                if self._error_count >= self._quit_count:
                    self._graceful_exit_locked()
                self._move_children_to_skipped_locked(job)
            self._finalizing.remove(job)
            self._last_done_or_idle_print = datetime.datetime.now()
            self._done.append(job)
            self._move_todo_to_ready_locked()
            self._condition.notify_all()

    def _record_incomplete_shutdown(self, job):
        """Fail a job without running cleanup while its process group may still exist."""
        message = "Process group could not be reaped after SIGKILL; job artifacts were left untouched."
        self.log.error("%s: %s", job, message)
        try:
            job.incomplete_shutdown(message)
        except (Exception, SystemExit) as exc:
            self.log.error("Could not record incomplete shutdown for %s: %s", job, exc)
            job.job_stop_time = datetime.datetime.now()
            job.jobstatus = JobStatus.FAILED
        with self._condition:
            if job not in self._active:
                return
            self._active.remove(job)
            self._shutdown_incomplete = True
            self._error_count += 1
            self._move_children_to_skipped_locked(job)
            self._graceful_exit_locked()
            self._done.append(job)
            self._last_done_or_idle_print = datetime.datetime.now()
            self._condition.notify_all()

    def _graceful_exit_locked(self):
        if self._done_grace_exit:
            return
        self.exited_prematurely = True
        self._done_grace_exit = True
        self.log.warn("Exceeded quit count. Graceful exit.")
        self._skipped.extend(self._todo)
        self._todo = []
        self._skipped.extend(self._ready)
        self._ready = []

    def add_job(self, job):
        if not isinstance(job, Job):
            raise ValueError("Tried to add a non-Job job {} of type {}".format(job, type(job)))
        with self._condition:
            if not self._done_grace_exit and self._run_jobs_thread_active:
                bisect.insort_right(self._todo, job)
            else:
                self._skipped.append(job)
            self._condition.notify_all()

    def wait(self):
        """Blocks until no jobs are left."""
        self.log.info("Waiting until all jobs are completed.")
        with self._condition:
            while self._todo or self._ready or self._launching or self._active or self._finalizing:
                self.log.debug("still waiting")
                self._condition.wait()

    def stop(self):
        """Stop and join the scheduler thread."""
        with self._condition:
            self._run_jobs_thread_active = False
            self._condition.notify_all()
        if threading.current_thread() is not self._run_jobs_thread:
            self._run_jobs_thread.join()

    @property
    def paused(self):
        with self._condition:
            return self._paused

    @property
    def shutdown_incomplete(self):
        with self._condition:
            return self._shutdown_incomplete

    def status_snapshot(self):
        """Return stable scheduler state for the interactive interrupt menu."""
        with self._condition:
            return {
                "paused": self._paused,
                "queued": tuple(self._todo) + tuple(self._ready),
                "launching": tuple(self._launching),
                "active": tuple(self._active),
                "finalizing": tuple(self._finalizing),
                "done": tuple(self._done),
                "skipped": tuple(self._skipped),
            }

    def flush_output_streams(self):
        """Flush output streams owned by active subprocess runners."""
        with self._condition:
            runners = [job.job_lib for job in self._active if job.job_lib is not None]
        for runner in runners:
            flush = getattr(runner, "flush_output_streams", None)
            if flush is not None:
                try:
                    flush()
                except Exception as exc:
                    self.log.warning("Could not flush job output before interrupt menu: %s", exc)

    def pause(self):
        """Pause active process groups and prevent queued jobs from launching."""
        with self._condition:
            if not self._run_jobs_thread_active:
                return 0
            self._paused = True
            active_jobs = tuple(self._active)
            self._condition.notify_all()
        paused_count = 0
        for job in active_jobs:
            pause_runner = getattr(job.job_lib, "pause", None)
            try:
                if pause_runner is not None and pause_runner():
                    paused_count += 1
            except Exception as exc:
                self.log.error("Could not pause runner for %s: %s", job, exc)
        return paused_count

    def resume(self):
        """Resume paused process groups and allow queued jobs to launch."""
        with self._condition:
            self._paused = False
            active_jobs = tuple(self._active)
            self._condition.notify_all()
        resumed_count = 0
        for job in active_jobs:
            resume_runner = getattr(job.job_lib, "resume", None)
            try:
                if resume_runner is not None and resume_runner():
                    resumed_count += 1
            except Exception as exc:
                self.log.error("Could not resume runner for %s: %s", job, exc)
        return resumed_count

    @property
    def interrupted_jobs(self):
        """Jobs captured during kill that have not completed finalization."""
        with self._condition:
            return tuple(job for job in self._interrupted_jobs if job not in self._done)

    def kill(self):
        with self._condition:
            self.exited_prematurely = True
            self._run_jobs_thread_active = False
            self._paused = False
            queued_jobs = list(self._todo) + list(self._ready)
            launching_jobs = list(self._launching)
            active_jobs = list(self._active)
            finalizing_jobs = list(self._finalizing)
            self._interrupted_jobs = launching_jobs + active_jobs + finalizing_jobs
            for job in queued_jobs + launching_jobs + active_jobs:
                job.request_cancel()
            for job in queued_jobs:
                if not job.jobstatus.completed:
                    job.jobstatus = JobStatus.SKIPPED
            self._skipped.extend(self._todo)
            self._todo = []
            self._skipped.extend(self._ready)
            self._ready = []
            self._condition.notify_all()

        errors = [None] * len(active_jobs)
        incomplete_shutdowns = [False] * len(active_jobs)

        def terminate(index, job):
            runner_stopped = False
            try:
                runner_stopped = job.job_lib.kill() is not False
                if not runner_stopped:
                    incomplete_shutdowns[index] = True
            except Exception as exc: # Keep terminating the remaining process groups.
                errors[index] = exc
            if runner_stopped:
                try:
                    job.cancel()
                except Exception as exc:
                    if errors[index] is None:
                        errors[index] = exc

        kill_threads = [
            threading.Thread(name="kill_{}".format(index), target=terminate, args=(index, job), daemon=True)
            for index, job in enumerate(active_jobs)
        ]
        for thread in kill_threads:
            thread.start()
        kill_deadline = time.monotonic() + self.ACTIVE_KILL_JOIN_SECONDS
        for thread in kill_threads:
            thread.join(timeout=max(0, kill_deadline - time.monotonic()))
        unfinished_kills = [thread.name for thread in kill_threads if thread.is_alive()]
        if unfinished_kills:
            self.log.warning("Timed out waiting for active job shutdown: %s", ", ".join(unfinished_kills))

        scheduler_finished = True
        if threading.current_thread() is not self._run_jobs_thread:
            self._run_jobs_thread.join(timeout=self.SHUTDOWN_JOIN_SECONDS)
            if self._run_jobs_thread.is_alive():
                scheduler_finished = False
                self.log.warning("Timed out waiting for scheduler launch hook to stop")
        first_error = next((error for error in errors if error is not None), None)
        if first_error is not None:
            raise first_error
        return (not unfinished_kills and not any(incomplete_shutdowns) and scheduler_finished
                and not self._shutdown_incomplete)


class BazelTBJob(Job):
    """Build the selected testbench and test configs in one Bazel invocation."""

    def __init__(self, rcfg, target, vcomper, additional_targets=()):
        self.bazel_target = target
        self.bazel_targets = []
        if not rcfg.options.no_compile:
            self.bazel_targets.append(target)
        self.bazel_targets.extend(additional_targets)
        self.bazel_targets = list(dict.fromkeys(self.bazel_targets))
        super(BazelTBJob, self).__init__(rcfg, self)
        self.vcomper = vcomper
        if vcomper:
            self.vcomper.add_dependency(self)

        self.job_dir = self.vcomper.job_dir # Don't actually need a dir, but jobrunner/manager want it defined
        if self.rcfg.options.no_bazel or not self.bazel_targets:
            self.main_cmdline = "echo \"Bypassing {} due to --no-compile/--no-bazel\"".format(target)
        else:
            self.main_cmdline = "bazel build {}".format(" ".join(self.bazel_targets))

    def post_run(self):
        super(BazelTBJob, self).post_run()
        if self.job_lib.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            self.log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

    def __repr__(self):
        return 'Bazel("{}")'.format(self.bazel_target)


class BazelTestCfgJob(Job):
    """Make selected test config outputs available after vcomp."""

    def __init__(self, rcfg, targets, vcomper, prebuilt=False):
        self.bazel_targets = [targets] if isinstance(targets, str) else list(targets)
        self.bazel_target = self.bazel_targets[0]
        super(BazelTestCfgJob, self).__init__(rcfg, self)
        self.vcomper = vcomper
        if vcomper:
            self.add_dependency(vcomper)

        self.job_dir = self.vcomper.job_dir # Don't actually need a dir, but jobrunner/manager want it defined
        if self.rcfg.options.no_bazel:
            self.main_cmdline = "echo \"Bypassing test cfg build due to --no-bazel\""
        elif prebuilt:
            self.main_cmdline = "echo \"Using test cfg outputs from initial Bazel build\""
        else:
            self.main_cmdline = "bazel build {}".format(" ".join(self.bazel_targets))

    def post_run(self):
        super(BazelTestCfgJob, self).post_run()
        if self.job_lib.returncode == 0:
            self.jobstatus = JobStatus.PASSED
        else:
            self.jobstatus = JobStatus.FAILED
            self.log.error("%s failed. Log in %s", self, os.path.join(self.job_dir, "stderr.log"))

    def dynamic_args(self, target=None):
        """Additional arugmuents to specific to each simulation"""
        path, target = (target or self.bazel_target).split(":")
        path_to_dynamic_args_files = os.path.join(self.rcfg.proj_dir, "bazel-bin", path[2:],
                                                  "{}_dynamic_args.py".format(target))
        with open(path_to_dynamic_args_files, 'r') as filep:
            content = filep.read()
            dynamic_args = ast.literal_eval(content)
        return normalize_test_runtime_options(dynamic_args)

    def __repr__(self):
        return 'Bazel({} test cfgs)'.format(len(self.bazel_targets))
