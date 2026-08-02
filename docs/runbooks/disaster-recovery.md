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

Set `AWS_DR_ENABLED=true` only after an in-VPC runner carrying the `dr` label and
the `production-dr` environment are approved. Configure
`SOURCE_DB_INSTANCE_ID`, `RESTORE_DB_SUBNET_GROUP`,
`RESTORE_DB_SECURITY_GROUP_IDS`, `RESTORE_DATABASE_NAME`, `AWS_DR_ROLE_ARN`, and
`SOURCE_DATABASE_SECRET_ARN`; the role needs RDS PITR/describe/delete, tag-read,
and source-secret read permissions. Then dispatch the nightly workflow. A hosted
public runner cannot reach the private restore and is intentionally unsupported.

`infra/scripts/verify-restore.sh` then:

1. Restores the latest snapshot into an isolated VPC.
2. Runs `alembic current` and confirms the schema matches head.
3. Verifies row counts for `tenants`, `contacts`, `leads`, `payments` and
   `consent_records` against the source within tolerance.
4. Runs the RLS allow and deny suite against the restored instance - **isolation
   must hold after a restore, not only in production**.
5. Refuses recovery points older than 15 minutes or completion beyond four hours.
6. Uploads `dr-evidence.json` as a one-year workflow artifact. The artifact is
   created only by an actual run and contains timings/counts, never credentials or
   endpoints.
7. Deletes only a scratch instance whose `purpose=restore-verification` and
   `run-id` tags exactly match this run. Set `KEEP_FAILED_RESTORE=true` only when
   an incident owner accepts the retained-instance cost for investigation.

A restore that has not been verified in the last quarter is a release blocker.
The existence of this script or a skipped workflow is not restore evidence.

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
