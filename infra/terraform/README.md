# Terraform

```
modules/
  network/   VPC, three AZs, public + application + data subnets, routing, security groups
  data/      RDS PostgreSQL 16, ElastiCache Redis 7, KMS, S3 buckets, AWS Backup, alarms
  edge/      ALB, HTTPS listener, WAFv2 web ACL and association, alarms
envs/
  prod/      ap-south-1, 10.0.0.0/16
  staging/   ap-south-1, 10.20.0.0/16   <- the release gates run here
  dev/       ap-south-1, 10.10.0.0/16
  sandbox/   ap-south-1, 10.30.0.0/16   <- provider test credentials only
```

Each environment is a separate AWS account with its own state bucket, lock table
and KMS keys. Nothing is shared, including the module defaults: the modules default
to production values, so an environment that forgets to override a setting gets the
safe one and a surprising bill, not a silent downgrade.

## What differs, and why

| | prod | staging | dev | sandbox |
|---|---|---|---|---|
| Database | Multi-AZ, r6g.xlarge | Multi-AZ, r6g.large | single-AZ, t4g.medium | single-AZ, t4g.medium |
| PITR retention | 30 days | 14 days | 7 days | 7 days |
| AWS Backup stream | yes | yes | no | no |
| Deletion protection | yes | yes | **no** | **no** |
| NAT gateways | one per AZ | one per AZ | one | one |
| Redis | 3 shards, replicas | 2 shards, replicas | 1 node | 1 node |
| Monthly budget alert | $5000 | $900 | $300 | $200 |

Staging matches production's *topology* rather than its size. The release gates -
k6 profiles, ZAP baseline, restore drill, acceptance suite - only produce
transferable evidence if the failure modes match: Multi-AZ failover, per-AZ NAT,
a cache that can actually fail over.

Dev and sandbox are disposable by design: deletion protection off and final
snapshots skipped, so `terraform destroy` completes. Do not put anything in them
you would mind losing, and do not put customer data in either.

Sandbox is the only environment permitted to hold provider *test* credentials.
Its separate account is the control: a sandbox sharing an account with production
is one IAM mistake away from production data.

## Running

```bash
cd infra/terraform/envs/<env>
cp terraform.tfvars.example terraform.tfvars   # fill in; gitignored
terraform init
terraform plan
```

Validation without an AWS account, which is what CI runs:

```bash
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/envs/<env> init -backend=false
terraform -chdir=infra/terraform/envs/<env> validate
```

`backend/tests/contract/test_terraform_environments.py` additionally pins the
differences above, so a change that quietly drops Multi-AZ from staging or turns
deletion protection off in production fails the test suite rather than review.

## Not yet true

No AWS account exists for any environment, nothing here has been applied, and no
state bucket has been created. Gates 4.1 through 4.8 in
`docs/GA-ACTIVATION-CHECKLIST.md` are open. These files are reviewed and
statically validated infrastructure code, not deployed infrastructure.
