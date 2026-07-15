# BIN KNOWLEDGE

## OVERVIEW

Executable/composition layer for `simmer`, parser utilities, generated run scripts, wave commands, and HTML reports.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Regression orchestration | `simmer.py` | Defines compile/test jobs and assembles the DAG |
| Common CLI flags | `args_parse/common.py` | Shared XRUN/VCS options |
| Backend CLI flags | `args_parse/{vcs,xcelium}.py` | Keep backend switches isolated |
| Parse CLI | `args_parse/parser.py` | Composes common and backend parsers and tracks explicitly supplied switches |
| Validate backend options | `../lib/simulators/{vcs,xcelium}_options.py` | Validation runs after the selected simulator is resolved |
| Generated compile/run scripts | `templates/*.j2` | Jinja context comes from `simmer.py` and simulator adapters |
| Static report pages | `templates/regression_report_templates/` | Rendered by `lib/regression_report.py` |
| Log checking | `check_test.py` | Importable library target plus executable |

## CONVENTIONS

- Keep `bin/` as orchestration: reusable discovery, scheduling, persistence, and backend mechanics belong in `lib/`.
- Add CLI options to the matching common/backend parser, then validate them in the selected backend.
- Templates are Bazel runtime data. Update `bin/BUILD` whenever a module or template dependency changes.
- Preserve shell quoting and exit-code precedence in generated scripts; simulator failure outranks log-parser failure.
- Report templates use an autoescaped Jinja environment and depth-sensitive relative links.

## ANTI-PATTERNS

- Do not put VCS switches in Xcelium parsing/templates or XRUN switches in VCS paths.
- Do not move discovery, scheduling, cache, result-history, or backend job mechanics into `simmer.py`.
- Do not mechanically rewrite braces: `bin/templates` is Jinja, while `vendors/` uses Bazel string substitution.
- Do not replace `|shell_quote` or generated command assembly with `eval`.
- Do not change a template variable without updating every render context and its runtime-contract test.

## CHECKS

```bash
bazel run //bin:simmer -- --help
bazel test //tests:check_test_test //tests:normalize_runfiles_flist_test
bazel test //tests/vcs_filelist_validation:vcs_runtime_contract_test
```
