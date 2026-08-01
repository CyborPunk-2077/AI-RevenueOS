# Production, ap-south-1. State is a private, versioned S3 bucket with DynamoDB locking.
terraform {
  required_version = ">= 1.9"

  backend "s3" {
    bucket         = "airevenueos-tfstate-prod"
    key            = "prod/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "airevenueos-tflock-prod"
    encrypt        = true
  }

  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

provider "aws" {
  region = "ap-south-1"   # Mumbai: data residency is a compliance requirement
  default_tags {
    tags = {
      environment = "prod"
      managed-by  = "terraform"
      owner       = "platform-team"
      cost-center = "engineering"
    }
  }
}

variable "image_digest" {
  type        = string
  description = "Immutable image digest promoted from CI. Images are never rebuilt per environment."
}

variable "certificate_arn" { type = string }

module "network" {
  source      = "../../modules/network"
  environment = "prod"
}

module "data" {
  source                 = "../../modules/data"
  environment            = "prod"
  vpc_id                 = module.network.vpc_id
  data_subnet_ids        = module.network.private_data_subnet_ids
  data_security_group_id = module.network.data_security_group_id
  instance_class         = "db.r6g.xlarge"
  multi_az               = true
}

module "edge" {
  source                = "../../modules/edge"
  environment           = "prod"
  vpc_id                = module.network.vpc_id
  public_subnet_ids     = module.network.public_subnet_ids
  alb_security_group_id = module.network.alb_security_group_id
  certificate_arn       = var.certificate_arn
}

# Cost guardrails.
resource "aws_budgets_budget" "monthly" {
  name         = "airevenueos-prod-monthly"
  budget_type  = "COST"
  limit_amount = "5000"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = ["platform@airevenueos.io"]
  }
}

output "alb_dns_name" { value = module.edge.alb_dns_name }
output "db_endpoint" { value = module.data.db_endpoint, sensitive = true }
