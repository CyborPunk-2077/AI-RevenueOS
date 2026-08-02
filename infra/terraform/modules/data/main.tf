# RDS PostgreSQL 16 Multi-AZ, ElastiCache Redis 7 and private S3 buckets.
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "data_subnet_ids" { type = list(string) }
variable "data_security_group_id" { type = string }
variable "instance_class" {
  type    = string
  default = "db.r6g.xlarge"
}
variable "multi_az" {
  type    = bool
  default = true
}
variable "alarm_topic_arn" { type = string }

locals {
  name = "airevenueos-${var.environment}"
  tags = {
    environment = var.environment
    service     = "data"
    owner       = "platform-team"
    cost-center = "engineering"
  }
}

resource "aws_kms_key" "data" {
  description             = "${local.name} envelope encryption master key"
  enable_key_rotation     = true            # annual master rotation
  deletion_window_in_days = 30
  tags                    = local.tags
}

resource "aws_db_subnet_group" "this" {
  name       = local.name
  subnet_ids = var.data_subnet_ids
  tags       = local.tags
}

resource "aws_db_parameter_group" "this" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
  parameter {
    name  = "idle_in_transaction_session_timeout"
    value = "60000"
  }

  tags = local.tags
}

resource "aws_db_instance" "primary" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.instance_class

  allocated_storage     = 500
  max_allocated_storage = 2000
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.data_security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false

  # PITR target RPO is 5 minutes; product acceptance permits no worse than 15.
  backup_retention_period   = 30
  backup_window             = "18:00-19:00"   # 23:30 IST
  maintenance_window         = "sun:19:30-sun:20:30"
  copy_tags_to_snapshot      = true
  deletion_protection        = true
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${local.name}-final"
  auto_minor_version_upgrade = true

  performance_insights_enabled          = true
  performance_insights_retention_period = 7
  monitoring_interval                   = 30
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]

  # The master credential is generated and rotated by Secrets Manager. It is never
  # written to Terraform variables, state output or CI logs.
  manage_master_user_password = true
  master_user_secret_kms_key_id = aws_kms_key.data.arn
  username                      = "airevenueos_admin"

  tags = local.tags
}

# AWS Backup provides an independently monitored continuous recovery stream in
# addition to the database's native 30-day PITR configuration.
resource "aws_backup_vault" "database" {
  name        = "${local.name}-database"
  kms_key_arn = aws_kms_key.data.arn
  tags        = local.tags
}

resource "aws_iam_role" "backup" {
  name = "${local.name}-backup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_backup_plan" "database" {
  name = "${local.name}-database"

  rule {
    rule_name                = "continuous-rds-pitr"
    target_vault_name        = aws_backup_vault.database.name
    schedule                 = "cron(0 20 * * ? *)"
    start_window             = 60
    completion_window        = 180
    enable_continuous_backup = true
    lifecycle { delete_after = 30 }
  }
  tags = local.tags
}

resource "aws_backup_selection" "database" {
  iam_role_arn = aws_iam_role.backup.arn
  name         = "${local.name}-database"
  plan_id      = aws_backup_plan.database.id
  resources    = [aws_db_instance.primary.arn]
}

resource "aws_cloudwatch_metric_alarm" "backup_failed" {
  alarm_name          = "${local.name}-backup-job-failed"
  alarm_description   = "Critical; owner=platform-team; runbook=docs/runbooks/alerts.md#backup-failure-or-rpo"
  namespace           = "AWS/Backup"
  metric_name         = "NumberOfBackupJobsFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    ResourceType = "RDS"
    VaultName    = aws_backup_vault.database.name
  }
  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = [var.alarm_topic_arn]
  tags          = local.tags
}

resource "aws_cloudwatch_metric_alarm" "recovery_point_partial" {
  alarm_name          = "${local.name}-recovery-point-partial"
  alarm_description   = "Critical; owner=platform-team; runbook=docs/runbooks/alerts.md#backup-failure-or-rpo"
  namespace           = "AWS/Backup"
  metric_name         = "NumberOfRecoveryPointsPartial"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    ResourceType = "RDS"
    VaultName    = aws_backup_vault.database.name
  }
  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = [var.alarm_topic_arn]
  tags          = local.tags
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = local.name
  description          = "${local.name} cache, coordination and Celery transport"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = "cache.r7g.large"
  port                 = 6379

  num_node_groups         = 3          # 3 shards
  replicas_per_node_group = 1          # 6 nodes total
  automatic_failover_enabled = true
  multi_az_enabled           = true

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [var.data_security_group_id]
  parameter_group_name = aws_elasticache_parameter_group.this.name

  snapshot_retention_limit = 1
  apply_immediately        = false
  tags                     = local.tags
}

resource "aws_elasticache_parameter_group" "this" {
  name   = "${local.name}-redis7"
  family = "redis7"
  # Redis is cache and coordination only; eviction is expected and safe.
  parameter {
    name  = "maxmemory-policy"
    value = "volatile-lru"
  }
}

resource "aws_elasticache_subnet_group" "this" {
  name       = local.name
  subnet_ids = var.data_subnet_ids
}

# --- private object storage --------------------------------------------------
locals {
  buckets = {
    uploads   = { lifecycle_days = 90,  transition = "STANDARD_IA" }
    documents = { lifecycle_days = 365, transition = "STANDARD_IA" }
    exports   = { lifecycle_days = 7,   transition = null }
    backups   = { lifecycle_days = 2555, transition = "GLACIER" }
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = "${local.name}-${each.key}"
  tags     = merge(local.tags, { purpose = each.key })
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  rule {
    id     = "retention"
    status = "Enabled"

    dynamic "transition" {
      for_each = each.value.transition == null ? [] : [each.value.transition]
      content {
        days          = 30
        storage_class = transition.value
      }
    }

    expiration { days = each.value.lifecycle_days }
    noncurrent_version_expiration { noncurrent_days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

output "kms_key_arn" { value = aws_kms_key.data.arn }
output "db_endpoint" { value = aws_db_instance.primary.endpoint }
output "redis_endpoint" { value = aws_elasticache_replication_group.redis.configuration_endpoint_address }
output "bucket_names" { value = { for k, v in aws_s3_bucket.this : k => v.id } }
