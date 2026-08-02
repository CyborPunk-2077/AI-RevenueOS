# Runbook: alert response

Every rule has an explicit owner, severity and runbook target. Warning alerts must
be acknowledged within 30 minutes. Critical alerts page the on-call immediately.
Never close an alert by disabling the rule; mitigate the customer impact, preserve
correlation IDs and audit evidence, then correct or tune the signal in code.

## API latency or error rate

Check readiness, database and Redis latency, then group API metrics and logs by
route and correlation ID. Scale the affected service if saturation is confirmed.
Roll back the current task definition if the increase began with a release.

## Queue depth or age

Run `make queues`, identify the affected pool and compare depth with live worker
concurrency. Pause non-critical bulk work before scaling the isolated pool. Do not
purge queued tenant work.

## Dead letters

Run `make dlq`, classify the error and inspect the original tenant/correlation
context. Fix the consumer before using the single-use replay command. Never edit or
delete the dead-letter row to make the alert green.

## Worker heartbeat

Check the named pool's readiness probe, broker connectivity and database access.
Restart only the affected pool; verify its queues drain before resolving.

## Provider circuit or AI errors

Confirm the provider status and that the product exposes the documented degraded
manual path. Leave the circuit open during an outage. Disable the feature flag if
degradation is not safe, and reconcile queued effects after recovery.

## AI budget

Identify the tenant label and compare usage records to its entitlement. Notify the
tenant owner before changing an entitlement. The 100% hard stop remains in force;
never reset usage counters to bypass it.

## Tenant isolation

Declare a P1 security incident immediately and follow the suspected cross-tenant
exposure procedure in `docs/runbooks/incident-response.md`. Preserve all evidence.

## Backup failure or RPO

Inspect the AWS Backup job and RDS events, verify that continuous recovery points
remain available, and initiate the restore verification runbook. A successful job
is not restore evidence; do not resolve until recovery points and RPO are known.

## WAF events

Inspect sampled requests without copying sensitive payloads into chat or tickets.
Identify the rule, source distribution and affected public route. Tighten the
specific rule or rate limit; do not disable the web ACL wholesale.

## Activation

Application rules can be evaluated locally with:

```bash
docker compose --profile monitoring up -d prometheus
```

The profile is optional so `RUN_DEMO.cmd` continues to start its established
nine-service stack. Production alert delivery requires a real PagerDuty/SNS
subscription and must be tested during AWS activation; this repository does not
pretend that a receiver exists.
