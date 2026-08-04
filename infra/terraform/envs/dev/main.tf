# Development, ap-south-1. Same shape as production, sized for a team, not a market.
#
# What is deliberately different from prod, and why:
#   - single NAT gateway: three are billed hourly and dev carries no traffic
#   - single-AZ database, no AWS Backup stream, 7-day PITR: dev data is disposable
#   - deletion protection off and no final snapshot: `terraform destroy` must work
#   - one cache node: no failover to test here
#
# What is NOT different, because these are the things that break silently in prod
# if they are only ever exercised there: three-AZ VPC layout, private data subnets
# with no egress route, KMS encryption at rest, TLS in transit, WAF on the ALB, and
# an immutable image digest promoted from CI.
terraform {
  required_version = ">= 1.9"

  backend "s3" {
    bucket         = "airevenueos-tfstate-dev"
    key            = "dev/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "airevenueos-tflock-dev"
    encrypt        = true
  }

  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

provider "aws" {
  region = "ap-south-1" # Mumbai: data residency is a compliance requirement

  default_tags {
    tags = {
      environment = "dev"
      managed-by  = "terraform"
      owner       = "platform-team"
      cost-center = "engineering"
    }
  }
}

resource "aws_sns_topic" "alerts" {
  name = "airevenueos-dev-alerts"
}

module "network" {
  source      = "../../modules/network"
  environment = "dev"

  # Distinct from prod (10.0/16), staging (10.20/16) and sandbox (10.30/16) so any
  # future peering or transit gateway attachment does not collide.
  cidr_block         = "10.10.0.0/16"
  single_nat_gateway = true
}

module "data" {
  source                 = "../../modules/data"
  environment            = "dev"
  vpc_id                 = module.network.vpc_id
  data_subnet_ids        = module.network.private_data_subnet_ids
  data_security_group_id = module.network.data_security_group_id
  alarm_topic_arn        = aws_sns_topic.alerts.arn

  instance_class        = "db.t4g.medium"
  multi_az              = false
  allocated_storage     = 20
  max_allocated_storage = 100
  backup_retention_days = 7
  deletion_protection   = false
  skip_final_snapshot   = true
  aws_backup_enabled    = false

  performance_insights_enabled = false

  redis_node_type          = "cache.t4g.micro"
  redis_shards             = 1
  redis_replicas_per_shard = 0
  redis_multi_az           = false
}

module "edge" {
  source                = "../../modules/edge"
  environment           = "dev"
  vpc_id                = module.network.vpc_id
  public_subnet_ids     = module.network.public_subnet_ids
  alb_security_group_id = module.network.alb_security_group_id
  certificate_arn       = var.certificate_arn
  alarm_topic_arn       = aws_sns_topic.alerts.arn
}

resource "aws_budgets_budget" "monthly" {
  name         = "airevenueos-dev-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.alerts.arn]
  }
}
