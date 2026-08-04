# Staging, ap-south-1. Production's shape and behaviour at a smaller scale.
#
# Staging is the environment the release gates run against: k6 load profiles, the
# ZAP baseline, the restore drill and the acceptance suite. That only means
# something if staging fails the way production would, so the topology matches:
# Multi-AZ database, NAT per AZ, failover-capable cache, AWS Backup running, and
# deletion protection on. It is smaller, not simpler.
#
# The two deliberate concessions: 14-day PITR rather than 30, and a smaller
# instance class. Neither changes a failure mode.
terraform {
  required_version = ">= 1.9"

  backend "s3" {
    bucket         = "airevenueos-tfstate-staging"
    key            = "staging/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "airevenueos-tflock-staging"
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
      environment = "staging"
      managed-by  = "terraform"
      owner       = "platform-team"
      cost-center = "engineering"
    }
  }
}

resource "aws_sns_topic" "alerts" {
  name = "airevenueos-staging-alerts"
}

module "network" {
  source      = "../../modules/network"
  environment = "staging"

  # Distinct from prod (10.0/16), dev (10.10/16) and sandbox (10.30/16) so any
  # future peering or transit gateway attachment does not collide.
  cidr_block = "10.20.0.0/16"

  # One NAT per AZ, as in production: a load profile run through a single gateway
  # measures that gateway, not the system.
  single_nat_gateway = false
}

module "data" {
  source                 = "../../modules/data"
  environment            = "dev"
  vpc_id                 = module.network.vpc_id
  data_subnet_ids        = module.network.private_data_subnet_ids
  data_security_group_id = module.network.data_security_group_id
  alarm_topic_arn        = aws_sns_topic.alerts.arn

  instance_class        = "db.r6g.large"
  multi_az              = true
  allocated_storage     = 100
  max_allocated_storage = 500
  backup_retention_days = 14
  deletion_protection   = true
  skip_final_snapshot   = false
  aws_backup_enabled    = true

  # Kept on: the P95 latency gate is meaningless without the query statistics that
  # explain a regression.
  performance_insights_enabled = true

  redis_node_type          = "cache.t4g.medium"
  redis_shards             = 2
  redis_replicas_per_shard = 1
  redis_multi_az           = true
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
  name         = "airevenueos-staging-monthly"
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
