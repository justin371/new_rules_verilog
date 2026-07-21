# ETX licensed-simulator validation

The `ETX Licensed VCS` workflow runs the full consumer test suite on the ETX
network. A self-hosted GitHub Actions runner submits the licensed work to the
`syn` LSF queue; the compute job sources `env/digital_env.sh` before invoking
Bazel, which is the non-interactive equivalent of the `ss` alias.

## One-time runner registration

Create a dedicated runner directory on the ETX submit host. In the GitHub
repository, open **Settings > Actions > Runners > New self-hosted runner** and
follow the displayed Linux x64 download instructions. Do not save or share the
one-time registration token.

Configure the runner with the dedicated label used by the workflow:

```bash
./config.sh \
  --url https://github.com/justin371/new_rules_verilog \
  --token '<one-time-token>' \
  --name sh-etxn8-vcs \
  --labels etx-vcs \
  --work _work
```

For the first validation, keep the ETX terminal open and start the runner in
the foreground:

```bash
./run.sh
```

The runner itself does not need `ss`; the submitted job sources the project
environment explicitly. If service installation is permitted later, GitHub's
generated `svc.sh` commands can replace the foreground process.

## Validation contract

On a push to `codex/v0.3-review-fixes`, the workflow:

1. routes only to a Linux x64 runner carrying the `etx-vcs` label;
2. locks the shared ETX rules checkout to prevent concurrent updates;
3. refuses to overwrite tracked changes in `/u/lwang/rules_verilog`;
4. fast-forwards that checkout to the exact workflow commit;
5. submits the following command through `bsub -K -q syn`:

   ```bash
   bazel test --config=vcs //... --test_tag_filters=-no_ci_gate \
     --cache_test_results=no --jobs 8 --test_output=all
   ```

6. uploads the Bazel log, failure summary, metadata, LSF log, and compressed
   per-target test logs to the GitHub Actions run for 14 days.

The workflow deliberately does not use the `pull_request` event. This
repository is public, so untrusted fork pull requests must never execute on an
ETX runner with access to the internal network and licensed tools.

If the shared checkout has tracked edits or cannot be advanced without a
non-fast-forward update, validation stops without modifying those changes.
