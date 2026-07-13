# LIB KNOWLEDGE

## OVERVIEW

Reusable Python core for discovery, job scheduling, simulator backends, compile caching, results, coverage, and reports.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Bazel test discovery/config | `regression.py` | Owns discovery cache and test selection |
| Scheduler and job states | `job_lib.py` | `todo -> ready -> active -> done/skipped` |
| Simulator contract | `simulators/base.py` | Concrete backends must conform |
| VCS/Xcelium mechanics | `simulators/{vcs,xcelium}.py` | Commands, waves, coverage, artifact validation |
| Backend option validation | `simulators/{vcs,xcelium}_options.py` | Reject mixed or unsupported switches |
| VCS scheduler extensions | `simulators/{vcs_jobs,vso}.py` | VSO/ICO and partition-specific planning |
| Runtime options | `runtime_options.py` | Normalize, merge, quote, and resolve timeouts |
| Persistent run history | `simmer_results.py` | Atomic/locked result-store updates |
| Dashboard rendering | `regression_report.py` | Autoescaped Jinja plus atomic writes |

## CONVENTIONS

- `lib/` must not import `bin/`; `bin/simmer.py` composes these services.
- Keep simulator branching behind `SimulatorInterface`, not in generic discovery or scheduler code.
- Keep VCS `-cm`, VSO/ICO, FSDB, and Verdi behavior out of Xcelium; keep MSIE, PLDM/emulation, and Xcelium coverage out of VCS.
- Preserve scheduler queue ownership, dependency-failure propagation, timeout escalation, and thread-cost accounting.
- Keep persisted schemas versioned and writes atomic; corruption and concurrent writers have focused tests.
- Each module has an explicit `py_library` in `lib/BUILD`; update deps instead of relying on ambient imports.
- Use stdlib `unittest`, `tempfile`, `SimpleNamespace`, and `unittest.mock` in focused module tests.

## ANTI-PATTERNS

- Do not bypass backend option validation or silently accept mixed simulator controls.
- Do not mutate job status outside the scheduler transition path.
- Do not make simulator adapters depend on site-specific launcher availability during unit tests.
- Do not weaken explicit cache fingerprints or artifact validation to make reuse succeed; unrelated untracked files are not cache inputs.

## CHECKS

```bash
bazel test //tests:job_manager_launch_test //tests:regression_discovery_test
bazel test //tests:runtime_options_test //tests:compile_cache_test
bazel test //tests:simmer_results_test //tests:regression_report_test
```
