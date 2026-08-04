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
- P2-6 is complete and committed. This tree was transferred to a new host without
  `.git`, so history restarts at a baseline commit; see `docs/TRANSFER-HANDOFF.md`.
  Do not redo completed modules.

## Exact next task

**P2-7: end-to-end OpenTelemetry tracing and tests, without leaking tenant data or
secrets.**

P2-6 is finished: `mypy tests --no-incremental` measured 178 errors in 23 files and
now reports zero, `tests` joined the `packages` list so bare `mypy` covers 264 source
files, and the pre-existing `# type: ignore` suppressions in the test tree were
removed rather than extended.

Then proceed in dependency order through P2-8 Storybook,
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

## Local Git and toolchain

The repository was re-initialised on this host, so the old `GIT_WORK_TREE` /
`GIT_INDEX_FILE` workaround is obsolete and plain Git is correct. Never reset, stash,
clean, discard, or rewrite history.

Python is CPython 3.12.13 (installed by `uv`) in
`D:\PAISA HAI TO\AI-RevenueOS-master\.venv312`, built from
`backend/requirements-dev.lock` with `--require-hashes --no-deps`.
