# Three-AZ VPC in ap-south-1. Databases and caches are never publicly reachable.
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

variable "environment" { type = string }
variable "cidr_block" {
  type    = string
  default = "10.0.0.0/16"
}
variable "azs" {
  type    = list(string)
  default = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
}

variable "single_nat_gateway" {
  type        = bool
  default     = false
  description = <<-EOT
    Collapse egress onto one NAT gateway. A NAT gateway is billed hourly per AZ,
    so three of them dominate the cost of an environment that carries no traffic.
    Production keeps one per AZ: with a single gateway, losing that AZ takes
    outbound connectivity with it.
  EOT
}

locals {
  name              = "airevenueos-${var.environment}"
  nat_gateway_count = var.single_nat_gateway ? 1 : length(var.azs)
  tags = {
    environment  = var.environment
    service      = "platform"
    owner        = "platform-team"
    cost-center  = "engineering"
    managed-by   = "terraform"
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = local.name })
}

resource "aws_subnet" "public" {
  count                   = length(var.azs)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.cidr_block, 8, count.index)
  availability_zone       = var.azs[count.index]
  map_public_ip_on_launch = false
  tags                    = merge(local.tags, { Name = "${local.name}-public-${count.index}", tier = "public" })
}

resource "aws_subnet" "private_app" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr_block, 8, count.index + 10)
  availability_zone = var.azs[count.index]
  tags              = merge(local.tags, { Name = "${local.name}-app-${count.index}", tier = "application" })
}

resource "aws_subnet" "private_data" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr_block, 8, count.index + 20)
  availability_zone = var.azs[count.index]
  tags              = merge(local.tags, { Name = "${local.name}-data-${count.index}", tier = "data" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = local.tags
}

resource "aws_eip" "nat" {
  count  = local.nat_gateway_count
  domain = "vpc"
  tags   = merge(local.tags, { Name = "${local.name}-nat-${count.index}" })
}

resource "aws_nat_gateway" "this" {
  count         = local.nat_gateway_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = merge(local.tags, { Name = "${local.name}-nat-${count.index}" })

  depends_on = [aws_internet_gateway.this]
}

# --- routing -----------------------------------------------------------------
# Public subnets egress through the internet gateway. Application subnets egress
# through NAT and are unreachable from the internet. Data subnets get no route off
# the VPC at all: PostgreSQL and Redis have no business making outbound calls, and
# the absence of a route is a stronger statement than a security group rule.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${local.name}-public", tier = "public" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private_app" {
  count  = length(var.azs)
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${local.name}-app-${count.index}", tier = "application" })
}

resource "aws_route" "private_app_egress" {
  count                  = length(var.azs)
  route_table_id         = aws_route_table.private_app[count.index].id
  destination_cidr_block = "0.0.0.0/0"

  # With one NAT gateway every AZ shares it; with one per AZ each stays local, so
  # cross-AZ data transfer is not paid for on every outbound byte.
  nat_gateway_id = aws_nat_gateway.this[var.single_nat_gateway ? 0 : count.index].id
}

resource "aws_route_table_association" "private_app" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.private_app[count.index].id
  route_table_id = aws_route_table.private_app[count.index].id
}

resource "aws_route_table" "private_data" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${local.name}-data", tier = "data" })
}

resource "aws_route_table_association" "private_data" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.private_data[count.index].id
  route_table_id = aws_route_table.private_data.id
}

# --- security groups: CloudFront/WAF -> ALB -> ECS -> RDS/Redis only ---------
resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public load balancer"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "HTTPS from the CloudFront managed prefix list only"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    description = "To application tasks"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.cidr_block]
  }

  tags = local.tags
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "ecs" {
  name        = "${local.name}-ecs"
  description = "Application and worker tasks"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "From the load balancer only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "HTTPS to approved provider endpoints and AWS services"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_security_group" "data" {
  name        = "${local.name}-data"
  description = "PostgreSQL and Redis. No public path exists."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "PostgreSQL from application tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  ingress {
    description     = "Redis from application tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  tags = local.tags
}

output "vpc_id" { value = aws_vpc.this.id }
output "private_app_subnet_ids" { value = aws_subnet.private_app[*].id }
output "private_data_subnet_ids" { value = aws_subnet.private_data[*].id }
output "public_subnet_ids" { value = aws_subnet.public[*].id }
output "alb_security_group_id" { value = aws_security_group.alb.id }
output "ecs_security_group_id" { value = aws_security_group.ecs.id }
output "data_security_group_id" { value = aws_security_group.data.id }
output "nat_gateway_ids" { value = aws_nat_gateway.this[*].id }
