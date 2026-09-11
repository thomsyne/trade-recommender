# Standalone local state. Never run the production infra root for this worker.
terraform {
  required_version = ">= 1.12.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
  }
}

variable "aws_account_id" {
  type        = string
  description = "Explicitly approved destination account; provider refuses other accounts."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply a twelve-digit AWS account ID."
  }
}

variable "aws_profile" {
  type    = string
  default = "default"
}

provider "aws" {
  region              = "us-east-1"
  profile             = var.aws_profile
  allowed_account_ids = [var.aws_account_id]
  default_tags {
    tags = {
      Application = "trade-recommender-validation"
      Environment = "offline-research"
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_ami" "worker" {
  most_recent = true
  owners      = ["137112412989"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

resource "aws_vpc" "worker" {
  cidr_block           = "10.88.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "phase55-validation-isolated" }
}

resource "aws_internet_gateway" "worker" { vpc_id = aws_vpc.worker.id }

resource "aws_subnet" "worker" {
  vpc_id                  = aws_vpc.worker.id
  cidr_block              = "10.88.1.0/24"
  map_public_ip_on_launch = true
}

resource "aws_route_table" "worker" {
  vpc_id = aws_vpc.worker.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.worker.id
  }
}

resource "aws_route_table_association" "worker" {
  subnet_id      = aws_subnet.worker.id
  route_table_id = aws_route_table.worker.id
}

resource "aws_security_group" "worker" {
  name        = "phase55-validation-no-inbound"
  description = "No inbound ports; outbound HTTPS for bootstrap, SSM and private artifacts"
  vpc_id      = aws_vpc.worker.id
  ingress     = []
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "phase55-validation-${var.aws_account_id}-"
  force_destroy = false
  lifecycle { prevent_destroy = true }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_policy" "tls" {
  bucket = aws_s3_bucket.artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_iam_role" "worker" {
  name = "phase55-validation-worker"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "artifacts" {
  role = aws_iam_role.worker.id
  name = "isolated-validation-artifacts-no-secrets"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Managed SSM core otherwise includes broad Parameter Store reads.
      { Effect = "Deny", Action = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "secretsmanager:*"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.artifacts.arn}/inputs/*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:AbortMultipartUpload"], Resource = "${aws_s3_bucket.artifacts.arn}/outputs/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.artifacts.arn, Condition = { StringLike = { "s3:prefix" = ["inputs/*", "outputs/*"] } } }
    ]
  })
}

resource "aws_iam_instance_profile" "worker" {
  name = "phase55-validation-worker"
  role = aws_iam_role.worker.name
}

resource "aws_instance" "worker" {
  ami                                  = data.aws_ami.worker.id
  instance_type                        = "m7i.2xlarge"
  subnet_id                            = aws_subnet.worker.id
  vpc_security_group_ids               = [aws_security_group.worker.id]
  iam_instance_profile                 = aws_iam_instance_profile.worker.name
  associate_public_ip_address          = true
  instance_initiated_shutdown_behavior = "stop"
  user_data                            = file("${path.module}/bootstrap.sh")
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 100
    encrypted             = true
    delete_on_termination = false
  }
  depends_on = [aws_iam_role_policy.artifacts, aws_iam_role_policy_attachment.ssm, aws_route_table_association.worker]
  tags       = { Name = "phase55-validation-worker" }
  lifecycle { prevent_destroy = true }
}

output "instance_id" { value = aws_instance.worker.id }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.id }
