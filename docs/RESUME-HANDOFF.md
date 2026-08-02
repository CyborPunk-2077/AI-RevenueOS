# Resume handoff

Repository evidence overrides prior chat claims. Read
`docs/TRANSFER-HANDOFF.md`, `docs/RELEASE-BLOCKERS.md`, and the canonical
`docs/AI-REVENUEOS-IMPLEMENTATION-SPECIFICATION.md` before changing code.

## Recovery point

- Branch: `master`
- Exact implementation commit before this docs-only transfer commit:
  `0f8ea027a27e2ef877190506b4df3aa70df278e1` (`P2-5: add fail-closed domain mutation gate`)
- The transfer commit is the commit containing this file; obtain its exact SHA with
  `git rev-parse HEAD`.
- Product/test work for P2-6 is present but uncommitted. Preserve every path listed
  in `docs/TRANSFER-HANDOFF.md` and do not redo completed modules.

## Exact next task

Finish **P2-6: strict mypy coverage for the full test tree**, starting from the
preserved uncommitted typing edits. Re-run `mypy tests --no-incremental`, fix the
remaining errors without weakening strictness, include tests in the normal mypy/CI
gate, run focused and broader validations, and commit the cohesive change. The last
completed measurement, taken before later preserved edits, was 112 errors in 18
files; it is historical evidence, not the current count.

Then proceed in dependency order through P2-7 OpenTelemetry, P2-8 Storybook,
P2-9 non-production Terraform environments, and the remaining specification gaps
listed in the transfer handoff and release blockers. External provider, AWS, DNS,
payment, production, and legal work stays disabled until real access and approval
exist.

## Most recent verified gates

At implementation commit `0f8ea02`: Ruff and format over 288 files, strict mypy
over 203 source files, import-linter 6/6, and 722 unit+contract tests passed. The
Linux-only mutation gate is configured, pinned, nightly, fail-closed at 75%, and
requires raw statistics; no mutation score was executed or claimed on this host.
See `docs/TRANSFER-HANDOFF.md` for earlier commit evidence and reproducible commands.

## Local Git workaround

`.git/config` has a stale Linux worktree. Set this before every Git operation:

```powershell
$env:GIT_WORK_TREE = (Get-Location).Path
$env:GIT_INDEX_FILE = Join-Path $env:TEMP 'airevenueos-codex-index'
```

Never reset, stash, clean, discard, or rewrite history. Leave the original
untracked `_tmp_5_43bb29c7ce5ddd61b5e99cfa69f4daf1` untouched.
