output "alb_dns_name" {
  value = module.edge.alb_dns_name
}

output "db_endpoint" {
  value     = module.data.db_endpoint
  sensitive = true
}

output "redis_endpoint" {
  value     = module.data.redis_endpoint
  sensitive = true
}

output "bucket_names" {
  value = module.data.bucket_names
}

output "alert_topic_arn" {
  description = "Subscribe the on-call integration here during activation."
  value       = aws_sns_topic.alerts.arn
}

output "vpc_id" {
  value = module.network.vpc_id
}
