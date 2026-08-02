# Staging performance and DAST verification

These gates require an approved, isolated staging environment with synthetic data.
The committed harness is not execution evidence. Never point it at production or a
customer tenant without an approved test window and incident owner.

Export an explicit staging URL and short-lived test-user token, then run:

```bash
BASE_URL=https://staging.example.invalid ACCESS_TOKEN=... k6 run infra/k6/normal.js
BASE_URL=https://staging.example.invalid ACCESS_TOKEN=... k6 run infra/k6/peak.js
BASE_URL=https://staging.example.invalid ACCESS_TOKEN=... k6 run infra/k6/spike.js
BASE_URL=https://staging.example.invalid NOISY_TOKEN=... QUIET_TOKEN=... k6 run infra/k6/noisy-tenant.js
```

The peak profile holds the documented 200-user P95 target; spike intentionally
reaches 400 and then measures recovery. Save the raw k6 JSON, service metrics,
database/queue saturation, deployment SHA, and UTC test window. Threshold failure
blocks release; do not edit the artifact into a pass.

The nightly ZAP baseline uses `infra/zap/rules.tsv`, where security controls are
explicit `FAIL` rules. Set the approved HTTPS staging URL in `STAGING_URL`, retain
the raw report, triage every alert, and link accepted false positives to a dated
security exception. A missing URL, skipped workflow, or committed rules file is not
a DAST pass.
