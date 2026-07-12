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
import subprocess
import threading
import time

from lib.runtime_options import normalize_test_runtime_options


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
            if new_state != self.FAILED:
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


class Job():

    _priority_cache = {}

    def __init__(self, rcfg, name):
        self.rcfg = rcfg # Regression cfg object
        self.name = name

        # String set by derived class of the directory to run this job in
        self.job_dir = None

        self.job_lib = None

        self.job_start_time = None
        self.job_stop_time = None

        self._jobstatus = JobStatus.NOT_STARTED

        self.suppress_output = False
        # FIXME need to implement a way to actually override this
        # FIXME add multiplier for --gui
        #self.timeout = 12.25 # Float hours
        self.timeout = rcfg.options.timeout

        self.priority = -3600 # Not sure that making this super negative is necessary if we log more stuff
        self._get_priority()
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

    def _get_priority(self):
        """This function is intended to assign a priority to this Job based on statistics of previous runs of this Job.

        However, integration with the external simulation statistics aggregator didn't work well so support was removed.
        """
        return # Default zero priority

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

    def __init__(self, job, manager):
        super(SubprocessJobRunner, self).__init__(job, manager)
        kwargs = {'shell': True, 'preexec_fn': os.setsid}
        self._timed_out = False
        self._term_deadline = None
        self._kill_sent = False
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

    def _close_output_streams(self):
        for stream in (getattr(self, "stdout_fp", None), getattr(self, "stderr_fp", None)):
            if stream and not stream.closed:
                stream.close()

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
            self._p.wait()
            self._close_output_streams()
            result = True
        if result:
            self.done = result
        return result

    def _check_for_done(self):
        if self._p.poll() is not None:
            if self._timed_out and not self._kill_sent:
                self._signal_process_group(signal.SIGKILL)
                self._kill_sent = True
            self._close_output_streams()
            return True

        now = datetime.datetime.now()
        if self._timed_out:
            if not self._kill_sent and now >= self._term_deadline:
                self.log.error("%s did not exit after SIGTERM; sending SIGKILL", self.job)
                self._signal_process_group(signal.SIGKILL)
                self._kill_sent = True
            return False

        timeout_start = self._start_time
        timeout_start_path = getattr(self.job, "timeout_start_path", None)
        if timeout_start_path:
            try:
                timeout_start = datetime.datetime.fromtimestamp(os.path.getmtime(timeout_start_path))
            except OSError:
                timeout_start = None
        if timeout_start is None:
            return False
        delta = now - timeout_start
        if self.job.timeout > 0 and delta > datetime.timedelta(hours=self.job.timeout):
            self.log.error("%s exceeded timeout value of %s; sending SIGTERM", self.job, self.job.timeout)
            self._timed_out = True
            self._term_deadline = now + datetime.timedelta(seconds=self.TERM_GRACE_SECONDS)
            self._signal_process_group(signal.SIGTERM)
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
        if self._timed_out and self._p.returncode in (None, 0):
            return -signal.SIGTERM
        return self._p.returncode

    def kill(self):
        self._signal_process_group(signal.SIGTERM)
        # None of the following variants seemed to work (due to shell=True ?)
        # process = psutil.Process(self._p.pid)
        # for proc in process.children(recursive=True):
        #     proc.kill()
        # process.kill()

        # self._p.terminate()

        # self._p.kill()


class JobManager():
    """Manages multiple concurrent jobs"""
    POLL_SLEEP_SECONDS = 0.25

    def __init__(self, options, log):
        self.log = log
        self.idle_print_interval = datetime.timedelta(seconds=options['idle_print_seconds'])
        self.active_job_limit = max(1, int(options.get('active_job_limit', 1)))

        self._quit_count = options['quit_count']
        self._error_count = 0
        self._done_grace_exit = False
        self.exited_prematurely = False

        # Jobs must transition from todo->ready->active->done

        # These are jobs ready to be run, but may not dependencies filled yet
        # This list is maintained in sorted priority order
        self._todo = []

        # Jobs ready to launch (all dependencies met)
        # This list is maintained in sorted priority order
        self._ready = []

        # Jobs launched but not yet complete
        self._active = []

        # Completed jobs
        self._done = []

        self._skipped = []

        self._jobs_added = threading.Event()

        self._run_jobs_thread = threading.Thread(name="_run_jobs", target=self._run_jobs)
        self._run_jobs_thread.daemon = True
        self._run_jobs_thread_active = True
        self._run_jobs_thread.start()

        self.job_lib_type = SubprocessJobRunner

        self._last_done_or_idle_print = datetime.datetime.now()

    def _print_state(self, log_fn):
        job_queues = ["_todo", "_ready", "_active", "_done", "_skipped"]
        for jq in job_queues:
            log_fn("%s: %s", jq, getattr(self, jq))

    def _run_jobs(self):
        while self._run_jobs_thread_active:
            self._move_todo_to_ready()
            self._move_ready_to_active()
            while len(self._active):
                for i, job in enumerate(self._active):
                    if job.job_lib.check_for_done():
                        self.log.debug("%s body done", job)
                        try:
                            job.post_run()
                        except (Exception, SystemExit) as exc:
                            self.log.error("%s  post_run_failed()\n:%s", job, exc)
                            job.job_stop_time = datetime.datetime.now()
                            job.jobstatus = JobStatus.FAILED
                            try:
                                job.post_run_failed(exc)
                            except (Exception, SystemExit) as record_exc:
                                self.log.error("%s failed to record post_run failure:\n%s", job, record_exc)
                        if not job.jobstatus.successful:
                            self._error_count += 1
                            if self._error_count >= self._quit_count:
                                self._graceful_exit()
                            self._move_children_to_skipped(job)
                        self._active.pop(i)
                        self._last_done_or_idle_print = datetime.datetime.now()
                        self._done.append(job)
                        # Ideally this would be before post_run, but pass_fail status may be set there
                        self._move_todo_to_ready()
                        self._move_ready_to_active()
                time_since_last_done_or_idle_print = datetime.datetime.now() - self._last_done_or_idle_print
                if time_since_last_done_or_idle_print > self.idle_print_interval:
                    self._last_done_or_idle_print = datetime.datetime.now()
                    self._print_state(self.log.info)

                time.sleep(self.POLL_SLEEP_SECONDS)
            if not len(self._active):
                self._jobs_added.wait()
                self._jobs_added.clear()

    def _move_children_to_skipped(self, job):
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
            self._move_children_to_skipped(child)

    def _move_todo_to_ready(self):
        self._print_state(self.log.debug)
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

    def _move_ready_to_active(self):
        self._print_state(self.log.debug)
        jobs_that_advanced_state = []

        def can_launch(job):
            if job.execution_mode == "exclusive":
                return len(self._active) == 0

            if job.execution_mode != "parallel":
                raise ValueError("Unknown execution mode '{}'".format(job.execution_mode))

            if any(active_job.execution_mode != "parallel" for active_job in self._active):
                return False

            return len(self._active) < self.active_job_limit

        made_progress = True
        while made_progress:
            made_progress = False
            for i, job in enumerate(self._ready):
                if i in jobs_that_advanced_state:
                    continue
                if not can_launch(job):
                    continue

                try:
                    job.pre_run()
                    self.log.debug("%s priority: %d", job, job.priority)
                    self.job_lib_type(job, self)
                except (Exception, SystemExit) as exc:
                    self.log.error("%s launch_failed(): %s", job, exc)
                    job.job_stop_time = datetime.datetime.now()
                    job.jobstatus = JobStatus.FAILED
                    try:
                        job.launch_failed(exc)
                    except Exception as record_exc:
                        self.log.error("Could not record launch failure for %s: %s", job, record_exc)
                    self._error_count += 1
                    self._move_children_to_skipped(job)
                    if self._error_count >= self._quit_count:
                        self._graceful_exit()
                    jobs_that_advanced_state.append(i)
                    self._done.append(job)
                    self._last_done_or_idle_print = datetime.datetime.now()
                    made_progress = True
                    continue
                jobs_that_advanced_state.append(i)
                self._active.append(job)
                made_progress = True

                if job.execution_mode == "exclusive":
                    break

                if len(self._active) >= self.active_job_limit:
                    break

        for i in reversed(jobs_that_advanced_state):
            if i < len(self._ready):
                self._ready.pop(i)

    def _graceful_exit(self):
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
        if not self._done_grace_exit:
            bisect.insort_right(self._todo, job)
            self._jobs_added.set()
        else:
            self._skipped.append(job)

    def wait(self):
        """Blocks until no jobs are left."""
        self.log.info("Waiting until all jobs are completed.")
        while len(self._todo) or len(self._ready) or len(self._active):
            self.log.debug("still waiting")
            time.sleep(self.POLL_SLEEP_SECONDS)

    def stop(self):
        """Stop the job runner thread (cpu intenstive). This is really more of a pause than a full stop&exit."""
        self._run_jobs_thread_active = False
        self._jobs_added.set()

    def kill(self):
        self.exited_prematurely = True
        self.stop()
        for job in self._active:
            job.job_lib.kill()


class BazelTBJob(Job):
    """Runs bazel to build up a tb compile."""

    def __init__(self, rcfg, target, vcomper):
        self.bazel_target = target
        super(BazelTBJob, self).__init__(rcfg, self)
        self.vcomper = vcomper
        if vcomper:
            self.vcomper.add_dependency(self)

        self.job_dir = self.vcomper.job_dir # Don't actually need a dir, but jobrunner/manager want it defined
        if self.rcfg.options.no_compile or self.rcfg.options.no_bazel:
            self.main_cmdline = "echo \"Bypassing {} due to --no-compile/--no-bazel\"".format(target)
        else:
            self.main_cmdline = "bazel build {}".format(target)

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
    """Build all selected test configs for one vcomp in a single Bazel invocation."""

    def __init__(self, rcfg, targets, vcomper):
        self.bazel_targets = [targets] if isinstance(targets, str) else list(targets)
        self.bazel_target = self.bazel_targets[0]
        super(BazelTestCfgJob, self).__init__(rcfg, self)
        self.vcomper = vcomper
        if vcomper:
            self.add_dependency(vcomper)

        self.job_dir = self.vcomper.job_dir # Don't actually need a dir, but jobrunner/manager want it defined
        if self.rcfg.options.no_bazel:
            self.main_cmdline = "echo \"Bypassing test cfg build due to --no-bazel\""
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
