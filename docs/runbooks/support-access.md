# Support access

Support access is tenant-approved, read-only, purpose-bound, and expires after at
most 60 minutes. An owner with a recent MFA step-up creates the grant through
`POST /v1/support-access` with an `Idempotency-Key`; revocation uses
`POST /v1/support-access/{grant_id}/revoke` and also requires a unique key.

The API stores the grant, audit record, durable idempotency result, and outbox
event atomically. A support-role token is rejected unless its user UUID or email
matches an active grant for the token's tenant. Revocation takes effect on the
next request. RLS hides grants from every other tenant.

Write-capable support access and direct database access are intentionally not
available. Do not add a support identity to a tenant as an ordinary member or
mint a support-role token outside the approved identity broker. Grant creation
is authorization evidence; it is not evidence that any support session occurred.
