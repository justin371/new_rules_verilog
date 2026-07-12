"""VCS-only ICO and VSO.ai scheduler jobs."""

import shlex

from lib.job_lib import Job, JobStatus


class IcoInitJob(Job):
    """Initialize the shared VCS ICO CDB before tests start."""

    def __init__(self, rcfg, simulator):
        super().__init__(rcfg, "ico_init")
        self.simulator = simulator
        self.job_dir = simulator._get_ico_artifact_dir()
        self.main_cmdline = None

    def pre_run(self):
        super().pre_run()
        command_parts, self.log_path = self.simulator.build_ico_init_command()
        if command_parts is None:
            self.main_cmdline = "echo {} > {}".format(
                shlex.quote("Reusing initialized VCS ICO shared CDB."),
                shlex.quote(self.log_path),
            )
        else:
            self.main_cmdline = shlex.join(command_parts) + " > {} 2>&1".format(shlex.quote(self.log_path))
        self.log.debug(" > %s", self.main_cmdline)

    def post_run(self):
        super().post_run()
        if self.job_lib.returncode == 0:
            self.jobstatus = JobStatus.PASSED
            self.rcfg.deferred_messages.append("VCS ICO shared-CDB init log: {}".format(self.log_path))
        else:
            self.jobstatus = JobStatus.FAILED
            self.log.error("%s failed. Log in %s", self, getattr(self, "log_path", "<unknown>"))

    def __repr__(self):
        return "VCS ICO init"


class VsoInitJob(Job):
    """Run VSO.ai init after all selected VCS builds complete."""

    def __init__(self, rcfg, simulator, vcomp_jobs):
        super().__init__(rcfg, "vso_init")
        self.simulator = simulator
        self.vcomp_jobs = vcomp_jobs
        self.job_dir = simulator.vso_workflow.artifact_dir()

    def pre_run(self):
        super().pre_run()
        args, self.log_path = self.simulator.vso_workflow.build_init_command(self.rcfg.all_vcomp, self.vcomp_jobs)
        command = [self.simulator.vso_workflow.driver_path()] + args
        self.main_cmdline = shlex.join(command) + " > {} 2>&1".format(shlex.quote(self.log_path))

    def post_run(self):
        super().post_run()
        self.jobstatus = JobStatus.PASSED if self.job_lib.returncode == 0 else JobStatus.FAILED
        if self.jobstatus == JobStatus.PASSED:
            self.rcfg.deferred_messages.append("VSO.ai init log: {}".format(self.log_path))
        else:
            self.log.error("%s failed. Log in %s", self, self.log_path)

    def __repr__(self):
        return "VSO.ai init"


class VsoAskJob(Job):
    """Run VSO.ai ask-all and schedule the returned test runs."""

    def __init__(self, rcfg, simulator):
        super().__init__(rcfg, "vso_ask")
        self.simulator = simulator
        self.job_dir = simulator.vso_workflow.artifact_dir()

    def pre_run(self):
        super().pre_run()
        args, self.log_path = self.simulator.vso_workflow.build_ask_command()
        command = [self.simulator.vso_workflow.driver_path()] + args
        self.main_cmdline = shlex.join(command) + " > {} 2>&1".format(shlex.quote(self.log_path))

    def post_run(self):
        super().post_run()
        if self.job_lib.returncode:
            self.jobstatus = JobStatus.FAILED
            self.log.error("%s failed. Log in %s", self, self.log_path)
            return
        try:
            result = self.simulator.vso_workflow.apply_ask_results(self.rcfg.all_vcomp, self.log_path)
        except (OSError, RuntimeError) as exc:
            self.jobstatus = JobStatus.FAILED
            self.log.error("Failed to apply VSO.ai ask results from %s: %s", self.log_path, exc)
            return
        for test in result["selected_tests"]:
            self.job_lib.manager.add_job(test)
        if self.rcfg.simmer_results_run is not None:
            self.rcfg.simmer_results_run["planned_tests"] = result["planned_runs"]
        self.jobstatus = JobStatus.PASSED
        self.rcfg.deferred_messages.append("VSO.ai ask log: {}".format(self.log_path))

    def __repr__(self):
        return "VSO.ai ask"
