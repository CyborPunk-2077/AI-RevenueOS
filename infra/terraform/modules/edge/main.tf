# CloudFront, WAF and the public ALB. TLS policy is TLSv1.2_2021 at the edge.
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "alb_security_group_id" { type = string }
variable "certificate_arn" { type = string }
variable "alarm_topic_arn" { type = string }

locals {
  name = "airevenueos-${var.environment}"
  tags = { environment = var.environment, service = "edge", owner = "platform-team" }
}

resource "aws_wafv2_web_acl" "this" {
  name  = local.name
  scope = "REGIONAL"
  default_action { allow {} }

  rule {
    name     = "AWSManagedCommonRuleSet"
    priority = 1
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedSQLi"
    priority = 2
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesSQLiRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "sqli"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedBotControl"
    priority = 3
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesBotControlRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "bot"
      sampled_requests_enabled   = true
    }
  }

  # 2,000 requests per five minutes per source IP.
  rule {
    name     = "RateLimit"
    priority = 10
    action { block {} }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ratelimit"
      sampled_requests_enabled   = true
    }
  }

  # Public form and webchat endpoints get a tighter budget.
  rule {
    name     = "PublicEndpointRateLimit"
    priority = 11
    action { block {} }
    statement {
      rate_based_statement {
        limit              = 300
        aggregate_key_type = "IP"
        scope_down_statement {
          byte_match_statement {
            positional_constraint = "STARTS_WITH"
            search_string         = "/v1/public/"
            field_to_match { uri_path {} }
            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "publicratelimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }

  tags = local.tags
}

resource "aws_lb" "this" {
  name                       = local.name
  internal                   = false
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [var.alb_security_group_id]
  drop_invalid_header_fields = true
  enable_deletion_protection = true
  idle_timeout               = 65
  tags                       = local.tags
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"success\":false,\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"Not found.\"}}"
      status_code  = "404"
    }
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.this.arn
  web_acl_arn  = aws_wafv2_web_acl.this.arn
}

resource "aws_cloudwatch_metric_alarm" "waf_blocked_requests" {
  alarm_name          = "${local.name}-waf-blocked-requests"
  alarm_description   = "Warning; owner=security-team; runbook=docs/runbooks/alerts.md#waf-events"
  namespace           = "AWS/WAFV2"
  metric_name         = "BlockedRequests"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 100
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    Region = "ap-south-1"
    Rule   = "ALL"
    WebACL = local.name
  }
  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = [var.alarm_topic_arn]
  tags          = local.tags
}

output "web_acl_arn" { value = aws_wafv2_web_acl.this.arn }
output "alb_arn" { value = aws_lb.this.arn }
output "alb_dns_name" { value = aws_lb.this.dns_name }
