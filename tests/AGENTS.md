# TEST KNOWLEDGE

## OVERVIEW

Bazel-driven stdlib `unittest` coverage plus nested workspace fixtures and license-free validation of generated simulator contracts.

## STRUCTURE

```text
*_test.py                 # focused Python unit/behavior tests
external_fixture/         # standalone WORKSPACE consumed as external IP
vcs_filelist_validation/  # VCS/XRUN two-step and one-step generated contracts
redhat_smoke.sh           # Red Hat/Python/Bazel portability gate
doc_test.sh               # direct documentation consistency checks
```

## CONVENTIONS

- Name files `<module>_test.py`, classes `<Subject>Test`, and methods `test_<behavior>`.
- Use stdlib `unittest`, `tempfile`, pathlib, `SimpleNamespace`, `unittest.mock`, and small local fakes.
- Declare one explicit Bazel `py_test` per module with exact library/data dependencies.
- Prefer tool stubs and generated-artifact inspection for license-free simulator contracts.
- Keep license-requiring BUILD targets tagged and manual; CI cannot validate real VCS/Xcelium execution.
- Update `tests/BUILD` when adding tests or fixture data.

## WHERE TO TEST

| Change | Test location |
|--------|---------------|
| Core `lib/<module>.py` behavior | matching top-level `<module>_test.py` |
| Scheduler/process launch | `job_manager_launch_test.py` |
| Discovery/cache behavior | `regression_discovery_test.py` |
| Public docs/exports | `docs_test.py`, `doc_test.sh` |
| VCS/XRUN two-step and one-step scripts/filelists | `vcs_filelist_validation/` |
| External repository paths | `external_fixture/` plus VCS validation tests |

## ANTI-PATTERNS

- Do not make no-license CI invoke real EDA binaries; keep real simulator validation separate on Red Hat.
- Do not replace precise fixtures with broad mocks that skip rendered commands, quoting, paths, or exit codes.
- Do not assume all `examples/...` targets are CI-safe; only the native DPI C test is license-free.

## CHECKS

```bash
bazel test --test_output=errors //:buildifier_diff //tests/... //examples/dpi:dpi_c_test
bazel test //tests/vcs_filelist_validation:vcs_filelist_validation_test
bazel test //tests/vcs_filelist_validation:vcs_runtime_contract_test
./tests/doc_test.sh
./tests/redhat_smoke.sh  # Red Hat-compatible host only
```
