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
  description = "CIDRs allowed to use key-only SSH. Empty by default (SSM Session Manager is the administration path). Every entry must have a prefix length of at least /8; Internet-scale entries (0.0.0.0/0, ::/0, /1 halves, /2 quarters, anything shorter than /8) are rejected unless allow_public_ssh_break_glass is explicitly true."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for cidr in var.ssh_cidrs : can(cidrhost(cidr, 0))])
    error_message = "Every ssh_cidrs entry must be a valid IPv4 or IPv6 CIDR."
  }

  validation {
    # The prefix length is parsed numerically so "/00" normalises to 0 and a
    # malformed entry (no "/", non-numeric prefix) evaluates to -1 and fails.
    condition = var.allow_public_ssh_break_glass || alltrue([
      for cidr in var.ssh_cidrs : try(tonumber(element(split("/", cidr), 1)), -1) >= 8
    ])
    error_message = "ssh_cidrs entries must be narrow: prefix length /8 or longer. 0.0.0.0/0, ::/0, /1 halves, /2 quarters and any prefix shorter than /8 are Internet-scale. Use narrow CIDRs (a /32 for the current location) or SSM; set allow_public_ssh_break_glass = true only as a documented emergency exception."
  }
}

variable "allow_public_ssh_break_glass" {
  description = "Emergency-only acknowledgement that ssh_cidrs may contain an Internet-wide CIDR. Leave false. Record the reason and revert to narrow CIDRs or [] afterwards."
  type        = bool
  default     = false
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
