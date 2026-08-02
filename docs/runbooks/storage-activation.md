# Runbook: object-storage activation

Object storage is **not active**. No AWS account or bucket has been supplied, the
malware-scanner transport is not deployed, and no live upload/download has been
verified. Keep `FEATURE_STORAGE_ENABLED=false` until every gate below has recorded
evidence. The local placeholder bucket names are configuration examples, not
resources that exist.

## What is safe before activation

- File upload intents are validated and stored as tenant-owned metadata.
- The planned object key is opaque and tenant-prefixed.
- `sha256` stays null, `storage_state` is `not_stored`, and downloads fail closed.
- The API returns no upload URL and the UI exposes no upload control.
- Document metadata, CRM links, RBAC, RLS, audit and outbox behavior remain usable.

## Hard prerequisites

1. Obtain the AWS accounts listed as P0-5 and apply the reviewed Terraform in a
   non-production account first.
2. Provision distinct private uploads, documents and exports buckets with public
   access blocked, KMS encryption, versioning and the intended lifecycle rules.
3. Give the application task role only the object operations it needs. Do not use
   an access key in `.env`, CI, an image or Terraform state.
4. Deploy a private ClamAV service and finish the `ClamAvScanner.scan` transport.
   A scanner host string alone is not evidence that scanning works.
5. Complete and test ingest confirmation: `HEAD` the uploaded object, compare the
   actual size and content type, compute the content SHA-256, check magic bytes and
   active content, scan it, and only then move `scan_status` to `clean`.
6. Add cleanup for abandoned upload intents and quarantined objects.

Until steps 4–6 are implemented and verified, this runbook is intentionally a
non-activation runbook: the S3 adapter can be configured and tested, but uploads
must remain disabled.

## Required configuration

Set through the deployment secret/configuration system, never in source:

```text
S3_BUCKET_UPLOADS=<real private bucket>
S3_BUCKET_DOCUMENTS=<different real private bucket>
S3_BUCKET_EXPORTS=<different real private bucket>
S3_REGION=ap-south-1
CLAMAV_HOST=<private service DNS name>
FEATURE_STORAGE_ENABLED=false
```

Production boot rejects enabled storage when these values are incomplete, use a
local placeholder, reuse one bucket for multiple policies, or specify a non-HTTPS
custom endpoint.

## Staging evidence required before enabling

Record command output or screenshots for all of the following:

1. AWS caller identity is the expected task role.
2. All three buckets exist in the expected account and region.
3. Public-access block, KMS encryption, versioning and lifecycle configuration are
   enabled on each bucket.
4. A cross-tenant API attempt returns 404 and never produces an S3 request for the
   other tenant's key.
5. A valid file follows `intent -> uploaded -> scanning -> clean`, the database
   SHA-256 matches the downloaded bytes, and the signed download expires in at
   most five minutes.
6. An executable, MIME mismatch, PDF active content and malware sample are rejected
   or quarantined and never receive a download URL.
7. An interrupted upload and an unavailable scanner leave the file unavailable;
   neither condition fabricates `clean`, a digest or a stored URL.
8. Audit and outbox rows commit with every metadata transition, and the restored
   database still passes the RLS isolation suite.

Only after this evidence is attached to the release record may staging set
`FEATURE_STORAGE_ENABLED=true`. Production activation requires a second review and
the same evidence against production infrastructure.

## Rollback

Set `FEATURE_STORAGE_ENABLED=false`. New upload intents may still be recorded, but
no upload URL is issued. Do not delete buckets or metadata during rollback. Keep
clean existing objects downloadable only if the incident does not affect access
control; otherwise disable downloads at the edge and preserve evidence.
