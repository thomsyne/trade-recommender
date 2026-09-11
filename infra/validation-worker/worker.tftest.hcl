# Mock provider only: these tests create no AWS resources.
mock_provider "aws" {
  override_during = plan
  mock_data "aws_ami" {
    defaults = { id = "ami-00000000000000000" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::phase55-validation-test-artifacts" }
  }
}

variables { aws_account_id = "000000000000" }

run "isolated_worker" {
  command = plan

  assert {
    condition     = aws_instance.worker.instance_type == "m7i.2xlarge" && aws_instance.worker.instance_initiated_shutdown_behavior == "stop"
    error_message = "Use the reviewed dedicated worker type and preserve it on OS shutdown."
  }
  assert {
    condition     = length(aws_security_group.worker.ingress) == 0 && length(aws_security_group.worker.egress) == 1 && one(aws_security_group.worker.egress).from_port == 443 && one(aws_security_group.worker.egress).to_port == 443
    error_message = "Worker must have no inbound ports and only HTTPS egress in its security group."
  }
  assert {
    condition     = one(aws_instance.worker.root_block_device).encrypted && !one(aws_instance.worker.root_block_device).delete_on_termination && one(aws_instance.worker.root_block_device).volume_size == 100
    error_message = "Keep encrypted checkpoints on a retained 100-GiB volume."
  }
  assert {
    condition     = one(aws_instance.worker.metadata_options).http_tokens == "required" && one(aws_instance.worker.metadata_options).http_put_response_hop_limit == 1
    error_message = "Require IMDSv2 with one hop."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.artifacts.block_public_acls && aws_s3_bucket_public_access_block.artifacts.block_public_policy && aws_s3_bucket_public_access_block.artifacts.ignore_public_acls && aws_s3_bucket_public_access_block.artifacts.restrict_public_buckets && !aws_s3_bucket.artifacts.force_destroy
    error_message = "Artifact storage must remain private and protected against bulk destruction."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.artifacts.policy).Statement[0].Effect == "Deny" && contains(jsondecode(aws_iam_role_policy.artifacts.policy).Statement[0].Action, "ssm:GetParameter") && contains(jsondecode(aws_iam_role_policy.artifacts.policy).Statement[0].Action, "ssm:GetParameters") && contains(jsondecode(aws_iam_role_policy.artifacts.policy).Statement[0].Action, "ssm:GetParametersByPath") && contains(jsondecode(aws_iam_role_policy.artifacts.policy).Statement[0].Action, "secretsmanager:*")
    error_message = "SSM administration must not grant production Parameter Store or secret access."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.artifacts.policy).Statement[1].Resource == "${aws_s3_bucket.artifacts.arn}/inputs/*" && jsondecode(aws_iam_role_policy.artifacts.policy).Statement[2].Resource == "${aws_s3_bucket.artifacts.arn}/outputs/*" && length(jsondecode(aws_iam_role_policy.artifacts.policy).Statement) == 4
    error_message = "Artifact permissions must remain confined to the new worker bucket."
  }
}
