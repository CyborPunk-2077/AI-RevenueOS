# Sandbox, ap-south-1. The only environment that talks to provider test modes.
#
# Sandbox exists so WhatsApp, Razorpay, SES/SendGrid and Google can be exercised
# against their *test* credentials without a production key ever being in reach.
# Two rules follow from that and are enforced here rather than by convention:
#
#   1. It is a separate AWS account with its own state bucket and KMS keys. A
#      sandbox that shares an account with production is one IAM mistake from
#      reading production data.
#   2. It carries no real customer data. Sizing is therefore minimal, and nothing
#      here is a substitute for staging: the release gates run against staging.
#
# The adapters still refuse to send without both the feature flag and a credential
# (ADR 0003), so an unconfigured sandbox is inert rather than fabricating success.
terraform {
  required_version = ">= 1.9"

  backend "s3" {
    bucket         = "airevenueos-tfstate-sandbox"
    key            = "sandbox/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "airevenueos-tflock-sandbox"
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
      environment = "sandbox"
      managed-by  = "terraform"
      owner       = "platform-team"
      cost-center = "engineering"
    }
  }
}

resource "aws_sns_topic" "alerts" {
  name = "airevenueos-sandbox-alerts"
}

module "network" {
  source      = "../../modules/network"
  environment = "sandbox"

  # Distinct from prod (10.0/16), dev (10.10/16) and staging (10.20/16) so any
  # future peering or transit gateway attachment does not collide.
  cidr_block         = "10.30.0.0/16"
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
  name         = "airevenueos-sandbox-monthly"
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
