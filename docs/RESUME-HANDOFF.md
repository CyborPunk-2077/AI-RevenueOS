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

**The P2 hardening track is complete.** P2-5 through P2-9 are implemented and
recorded in `docs/IMPLEMENTATION-LOG.md`; the externally gated parts of P2-7 and
P2-9 stay unclaimed until real access exists.

Next is the remaining specification gaps, in dependency order, inspecting current
code before assuming anything is missing: app-shell and invitation gaps (M05-M06);
forms, import, dedupe and assignment gaps (M08); webchat (M11); extraction and RAG
(M13); calendar and reminders (M14); gated channel providers (M15-M16); invoice and
payment UX (M17); the workflow builder, schedules and logs (M18); reporting and
export gaps (M20); hardening and evidence (M21); then the externally gated DR,
pilots and GA work (M22-M24).

External provider, AWS, DNS, payment, production and legal work stays disabled
until real access and approval exist.

### What P2-8 and P2-9 changed, in one line each

- **P2-8:** Storybook 8 over the component surface, and `pnpm a11y` now runs
  `@storybook/test-runner` + axe over every story. The CI job of that name
  previously matched no package task and passed by doing nothing.
- **P2-9:** `envs/dev`, `envs/staging`, `envs/sandbox` beside `envs/prod`, with
  isolated state and address space and contract-tested differences. The network
  module had no route tables at all; that is fixed.

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

Python is CPython 3.12.13 (installed by `uv`), built from
`backend/requirements-dev.lock` with `--require-hashes --no-deps`. The working tree
is `D:\PAISA HAI TO\AI-RevenueOS\AI-RevenueOS`; `..\validate.ps1` finds or builds
the venv and runs every gate - backend ruff, mypy and tests, then pnpm lint,
typecheck, tests and the accessibility scan.

Frontend toolchain is pnpm 9 with Node 20. The accessibility gate needs
`pnpm exec playwright install --with-deps chromium` once per machine.

Terraform is validated statically only: `terraform fmt -check -recursive` and
`terraform init -backend=false && terraform validate` per environment. No AWS
account exists and nothing has been applied.
