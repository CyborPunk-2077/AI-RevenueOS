# Runbook: backup, restore and disaster recovery

## Targets

| Scope | RPO | RTO |
|---|---|---|
| Product acceptance floor | 15 minutes | 4 hours |
| Design target | 5 minutes | 4 hours |
| Local service or AZ failure (replicas provisioned) | under 2 minutes | under 30 minutes |
| Database failover service target | - | 15 minutes |

## What is backed up

| Asset | Mechanism | Retention |
|---|---|---|
| PostgreSQL | RDS PITR plus daily snapshots | 30 days |
| S3 uploads, documents, exports | Versioning, lifecycle to IA and Glacier | Per bucket policy |
| Consent and payment records | Archived to Glacier | 7 years |
| Audit log | Partitioned, archived per legal policy | 24 months minimum |
| Terraform state | Versioned private S3 with DynamoDB locking | Indefinite |
| Container images | ECR with immutable tags | 90 days |

## Quarterly restore verification (mandatory)

Run `infra/scripts/verify-restore.sh`, which:

1. Restores the latest snapshot into an isolated VPC.
2. Runs `alembic current` and confirms the schema matches head.
3. Verifies row counts for `tenants`, `contacts`, `leads`, `payments` and
   `consent_records` against the source within tolerance.
4. Runs the RLS allow and deny suite against the restored instance - **isolation
   must hold after a restore, not only in production**.
5. Records the measured RPO and RTO in `docs/evidence/dr-drills/`.

A restore that has not been verified in the last quarter is a release blocker.

## Regional recovery

1. Declare a regional incident; page the platform lead.
2. Promote the cross-region snapshot copy in the DR account and VPC.
3. Apply `infra/terraform/envs/prod` with the DR region variable.
4. Repoint Route 53 to the DR ALB.
5. Verify: health readiness, an authenticated read, an authenticated write, the RLS
   deny path, and outbox drain.
6. Keep every externally gated provider **off** during recovery until webhook
   endpoints are re-registered - a stale webhook target causes duplicate customer
   contact.

## Restoring a single tenant

Tenant deletion purges after 90 days unless a legal hold applies. Within that window:

1. Restore a snapshot into a scratch instance.
2. Export the tenant's rows with `app.tenant_id` bound - the same RLS path used in
   production, so the export cannot pick up another tenant's data.
3. Re-import through the application service layer so events, audit entries and
   metering are all produced correctly.
