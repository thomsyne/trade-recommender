terraform {
  required_version = ">= 1.10.0"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = var.name_prefix
      ManagedBy   = "Terraform"
      Environment = "research"
    }
  }
}
