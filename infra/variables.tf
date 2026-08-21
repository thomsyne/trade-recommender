variable "aws_region" {
  description = "AWS region; Slice 6 is designed and tested for us-east-1."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "This deployment must remain in us-east-1."
  }
}

variable "name_prefix" {
  type    = string
  default = "trade-recommender"
}

variable "instance_type" {
  type    = string
  default = "t4g.small"
}

variable "root_volume_gb" {
  type    = number
  default = 25

  validation {
    condition     = var.root_volume_gb >= 20 && var.root_volume_gb <= 30
    error_message = "The root gp3 volume must stay between 20 and 30 GB."
  }
}

variable "ssh_public_key" {
  description = "Optional owner SSH public key. Leave empty to use SSM only. Never supply a private key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "ssh_cidrs" {
  description = "CIDRs allowed to use key-only SSH. Empty by default. Set [\"0.0.0.0/0\"] explicitly only when travel requires it; prefer narrow CIDRs and SSM."
  type        = list(string)
  default     = []
}

variable "backup_retention_days" {
  type    = number
  default = 35
}

variable "production_env_parameter" {
  type    = string
  default = "/trade-recommender/production-env"
}

variable "route53_zone_id" {
  description = "ID of the existing public Route 53 hosted zone authoritative for public_hostname."
  type        = string

  validation {
    condition     = can(regex("^Z[A-Z0-9]+$", var.route53_zone_id))
    error_message = "route53_zone_id must be an explicit Route 53 hosted zone ID beginning with Z."
  }
}

variable "public_hostname" {
  description = "Public application hostname managed as an A record in the supplied Route 53 zone."
  type        = string
  default     = "fx-forecast.thomsyne.dev"

  validation {
    condition     = var.public_hostname == lower(trimsuffix(var.public_hostname, ".")) && can(regex("^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", var.public_hostname))
    error_message = "public_hostname must be a lowercase fully-qualified DNS hostname without a trailing dot."
  }
}
