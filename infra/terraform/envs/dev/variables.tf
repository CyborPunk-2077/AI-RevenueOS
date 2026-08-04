variable "image_digest" {
  type        = string
  description = <<-EOT
    Immutable image digest promoted from CI. Images are never rebuilt per
    environment: the artefact that reaches production is the one dev ran.
  EOT
}

variable "certificate_arn" {
  type        = string
  description = "ACM certificate for the environment hostname. Gate 4.2."
}

variable "monthly_budget_usd" {
  type        = number
  default     = 300
  description = "Forecast alert fires at 80% of this."
}
