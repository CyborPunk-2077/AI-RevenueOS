# Portable transfer handoff — AI RevenueOS

Repository evidence overrides prior chat claims. The product is **not GA-ready**;
provider, cloud, legal, staging, performance, DAST, restore, and production claims
must be backed by real evidence before their status changes.

## Recovery point and protected work

- Branch: `master`
- Exact implementation commit before this docs-only transfer commit:
  `0f8ea027a27e2ef877190506b4df3aa70df278e1` (`P2-5: add fail-closed domain mutation gate`)
- The transfer commit is the commit containing this file; use `git rev-parse HEAD`
  for its exact SHA.
- Canonical specification:
  `docs/AI-REVENUEOS-IMPLEMENTATION-SPECIFICATION.md`, SHA-256
  `61A52924B51792C632C2CA8A8909BBD9263D0F77EBB732F4C8F3F7685570F50F`.

Preserve these uncommitted P2-6 edits exactly until that task is completed:

```text
backend/src/infrastructure/integrations/email.py
backend/tests/conftest.py
backend/tests/contract/test_api_authorization.py
backend/tests/contract/test_provider_adapters.py
backend/tests/integration/test_migrations.py
backend/tests/integration/test_outbox.py
backend/tests/integration/test_rls_isolation.py
backend/tests/unit/test_coverage_policy.py
backend/tests/unit/test_payments_domain.py
backend/tests/unit/test_storage_configuration.py
backend/tests/unit/test_workflow_dsl.py
```

The original untracked sentinel
`_tmp_5_43bb29c7ce5ddd61b5e99cfa69f4daf1` is protected. Never modify, stage, remove,
or clean it. Never reset, stash, discard, or rewrite existing work.

## Verified completed checkpoints

| Commit | Completed behavior and recorded evidence |
|---|---|
| `0f8ea02` | Fail-closed Linux mutation gate for domain/auth, pinned mutmut 3.6, raw-stat artifact and 75% threshold. Ruff/format 288 files, strict mypy 203 source files, import-linter 6/6, 722 unit+contract tests. No mutation score claimed. |
| `744507d` | Durable onboarding state machine with dependencies, RBAC, idempotency, atomic audit/outbox, provider non-activation semantics; 5 unit and 4 real-Postgres E2E tests plus authorization contracts. |
| `c3f0fa8` | Python 3.12 alignment and compatibility-shim removal; 708 unit+contract tests and static/architecture gates passed. |
| `269e7b8` | Fail-closed staging k6, ZAP, restore, and evidence-index assets; 3 asset tests. Assets were not run against staging. |
| `2244187` | Git-backed prompt governance and deterministic offline evaluation; 3 real-Postgres E2E and 2 unit tests. Twelve prompt versions scored 1.0 with `provider_called=false`; no model-quality claim. |
| `d2652df`, `1629a5a`, `444e307` | Encrypted/redacted provider configuration, support-access, and bounded bulk-operation audit paths with focused real-Postgres coverage. Provider frontend lint/typecheck, 14 Vitest tests, and production build passed at that checkpoint. |
| `a2e45df`, `d6b6c03`, `55feae9`, `51ea5c0` | Durable tenant-derived Razorpay ingress, signed outbound webhooks, authorized workflow actions/receipts, event matching and approvals. |
| `cd5df7c`, `bd8ed03` | Immutable consent and scan-gated storage lifecycle with atomic audit/outbox behavior and real-Postgres/TCP-clamd test coverage; no live provider or AWS activation claimed. |

Earlier implementation and test evidence remains in Git history and
`docs/RELEASE-BLOCKERS.md`; inspect it before assuming a module is missing.

## Exact next task and dependency order

1. **P2-6:** finish the preserved strict-mypy test-tree work. Re-run
   `mypy tests --no-incremental`, fix remaining errors without suppressing useful
   checks, include tests in the normal mypy/CI gate, validate, and commit. The last
   completed pre-later-edits measurement was 112 errors in 18 files; the current
   count is unknown and must be measured.
2. **P2-7:** add end-to-end OpenTelemetry tracing and tests without leaking tenant
   data or secrets.
3. **P2-8:** add the declared Storybook surface and accessibility checks, or remove
   only claims the canonical specification permits removing.
4. **P2-9:** add dev, staging, and sandbox Terraform environments; validate without
   claiming deployment.
5. Finish remaining specification gaps in dependency order, inspecting current
   code first: app-shell/invitation gaps (M05–M06); forms/import/dedupe/assignment
   gaps (M08); webchat (M11); extraction/RAG (M13); calendar/reminders (M14);
   gated channel providers (M15–M16); invoice/payment UX (M17); workflow builder,
   schedules and logs (M18); reporting/export gaps (M20); hardening and evidence
   (M21); then externally gated DR, pilots, and GA (M22–M24).

Do not redo completed CRM, auth, worker, analytics, audit/outbox, provider-config,
workflow, consent, payment-ingress, storage, onboarding, prompt-governance, or
release-harness work. Confirm each gap against repository evidence first.

## Bootstrap, run, and verify

Windows Docker demo (Docker Desktop required):

```powershell
.\RUN_DEMO.cmd
```

`RESET_DEMO.cmd` is destructive and must be used only when explicitly intended.
For a clean Linux clone:

```bash
make bootstrap
make up
make migrate seed
make verify
make test-workers
```

Backend checks on this Windows host:

```powershell
$repo = (Get-Location).Path
$py = 'C:\Users\Administrator\AppData\Local\Temp\airevenueos-recovery-venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $repo 'backend\src'
Push-Location backend
& $py -m ruff check src tests alembic
& $py -m ruff format --check src tests alembic
& $py -m mypy src
& $py -m mypy tests --no-incremental
& 'C:\Users\Administrator\AppData\Local\Temp\airevenueos-recovery-venv\Scripts\lint-imports.exe'
& $py -m pytest tests/unit tests/contract -q
Pop-Location
```

Real-Postgres persistence/RLS tests use the existing local harness:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://airev_app_runtime@127.0.0.1:61174/airevenueos_test'
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:ALEMBIC_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:61174/airevenueos_test'
Remove-Item Env:ADMIN_DATABASE_URL -ErrorAction SilentlyContinue
```

Confirm the specific test marker/command from the existing CI and test config
before running broad persistence suites. Frontend checks:

```powershell
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm --filter @airevenueos/web build
```

Run `make mutation` only on Linux/WSL. A completed raw artifact is required before
claiming any score.

## Local limits and Git workaround

- No Docker daemon, Terraform CLI, k6, standalone Playwright browser, or supported
  WSL environment is available here. Do not claim their execution.
- The real PostgreSQL harness is on port 61174 at migration 0010. The auth E2E
  Redis path skips without a real `REDIS_URL`; CI provides a real service.
- The in-app browser was previously used for browser checks; that does not replace
  standalone Playwright, staging, accessibility, performance, or DAST evidence.
- `.git/config` contains a stale Linux `core.worktree`. Before every Git operation:

```powershell
$env:GIT_WORK_TREE = (Get-Location).Path
$env:GIT_INDEX_FILE = Join-Path $env:TEMP 'airevenueos-codex-index'
```

If a Git lock is stale, preserve it by moving it aside; do not delete it. Stage
only intended paths because the alternate index coexists with protected work.

## External activation checklist — all disabled/unactivated

| Area | Required external evidence before enabling |
|---|---|
| WhatsApp | BSP/direct Cloud API decision, owned credentials, operations owner, Meta-approved templates and legal consent. |
| Email/SMS | SES/SendGrid commercial decision, verified sender domain with SPF/DKIM/DMARC; India DLT approval where applicable. |
| Razorpay | Commercial model, real credentials, collections versus SaaS-billing decision, refunds/reconciliation and subscriptions approval. |
| Voice/signature | Approved provider and number/account ownership, recording consent/disclosures, signature-provider agreement. |
| Google/AI | OAuth/calendar verification, approved model and embeddings providers, retention/privacy approval. |
| AWS/DNS/storage | Separate environment accounts, Route 53/ACM, KMS/Secrets, GitHub OIDC, private S3/task roles, deployed ClamAV and EICAR evidence. |
| Operations | PagerDuty, Sentry/Langfuse, approved staging, k6/ZAP evidence, timed restore drill, pentest, screen-reader passes and soak test. |
| Legal/commercial | DPDP/privacy, retention/legal hold, breach process, industry claims, AI retention, pricing/quotas/entitlements, n8n licensing/ownership. |
| Release | Controlled pilots for every enabled industry and recorded P0/P1/acceptance evidence. |

Keep adapters behind configuration validation, feature flags, truthful disabled
UX, sandbox/mock tests, IaC, and activation runbooks. Never fabricate activation,
delivery, payment, upload, approval, deployment, or production evidence.
