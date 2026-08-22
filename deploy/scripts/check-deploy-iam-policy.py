#!/usr/bin/env python3
import fnmatch
import importlib.util
import json
from pathlib import Path

generator_path = Path(__file__).with_name("render-deploy-iam-policy.py")
spec = importlib.util.spec_from_file_location("deploy_iam_policy", generator_path)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

ACCOUNT_ID = "123456789012"
ZONE_ID = "Z0123456789ABCDEF"
POLICY_LIMIT = generator.POLICY_LIMIT

# Representative calls span every Terraform resource class and workflow AWS CLI
# path. Implicit provider refresh/waiter calls are included deliberately.
REQUIRED_ACTIONS = {
    "identity": {"sts:GetCallerIdentity"},
    "state_and_backup_s3": {
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:GetAccelerateConfiguration",
        "s3:GetReplicationConfiguration",
        "s3:GetEncryptionConfiguration",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketVersioning",
        "s3:GetLifecycleConfiguration",
        "s3:PutBucketPublicAccessBlock",
        "s3:PutEncryptionConfiguration",
        "s3:PutBucketVersioning",
        "s3:PutLifecycleConfiguration",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
    },
    "ecr": {
        "ecr:GetAuthorizationToken",
        "ecr:CreateRepository",
        "ecr:DescribeRepositories",
        "ecr:ListTagsForResource",
        "ecr:TagResource",
        "ecr:PutImageScanningConfiguration",
        "ecr:PutImageTagMutability",
        "ecr:PutLifecyclePolicy",
        "ecr:GetLifecyclePolicy",
        "ecr:DeleteLifecyclePolicy",
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:DeleteRepository",
    },
    "network_and_compute": {
        "ec2:DescribeImages",
        "ec2:GetInstanceUefiData",
        "ec2:CreateVpc",
        "ec2:DescribeVpcs",
        "ec2:ModifyVpcAttribute",
        "ec2:CreateSubnet",
        "ec2:DescribeSubnets",
        "ec2:ModifySubnetAttribute",
        "ec2:CreateInternetGateway",
        "ec2:DescribeInternetGateways",
        "ec2:AttachInternetGateway",
        "ec2:DetachInternetGateway",
        "ec2:CreateRouteTable",
        "ec2:DescribeRouteTables",
        "ec2:CreateRoute",
        "ec2:ReplaceRoute",
        "ec2:AssociateRouteTable",
        "ec2:ReplaceRouteTableAssociation",
        "ec2:CreateSecurityGroup",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeNetworkInterfaces",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:ImportKeyPair",
        "ec2:DescribeKeyPairs",
        "ec2:RunInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:ModifyInstanceMetadataOptions",
        "ec2:AllocateAddress",
        "ec2:DescribeAddresses",
        "ec2:DescribeAddressAttribute",
        "ec2:AssociateAddress",
        "ec2:DisassociateAddress",
        "ec2:DeleteVpc",
        "ec2:DeleteSubnet",
        "ec2:DeleteInternetGateway",
        "ec2:DeleteRouteTable",
        "ec2:DisassociateRouteTable",
        "ec2:DeleteSecurityGroup",
        "ec2:DeleteKeyPair",
        "ec2:TerminateInstances",
        "ec2:ReleaseAddress",
    },
    "instance_iam": {
        "iam:CreateRole",
        "iam:GetRole",
        "iam:UpdateAssumeRolePolicy",
        "iam:TagRole",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:CreateInstanceProfile",
        "iam:GetInstanceProfile",
        "iam:TagInstanceProfile",
        "iam:ListInstanceProfileTags",
        "iam:AddRoleToInstanceProfile",
        "iam:PassRole",
        "iam:DeleteRolePolicy",
        "iam:DetachRolePolicy",
        "iam:RemoveRoleFromInstanceProfile",
        "iam:DeleteInstanceProfile",
        "iam:DeleteRole",
    },
    "ssm": {
        "ssm:PutParameter",
        "ssm:DescribeInstanceInformation",
        "ssm:SendCommand",
        "ssm:GetCommandInvocation",
    },
    "dns": {
        "route53:ListHostedZones",
        "route53:GetHostedZone",
        "route53:ListTagsForResource",
        "route53:ListResourceRecordSets",
        "route53:ChangeResourceRecordSets",
        "route53:GetChange",
    },
}


def actions(policy):
    return [
        action
        for statement in policy["Statement"]
        for action in (
            [statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"]
        )
    ]


def allows(patterns, required):
    return any(fnmatch.fnmatchcase(required, pattern) for pattern in patterns)


def allows_on(policy, action, resource):
    for statement in policy["Statement"]:
        statement_actions = statement["Action"]
        if isinstance(statement_actions, str):
            statement_actions = [statement_actions]
        statement_resources = statement["Resource"]
        if isinstance(statement_resources, str):
            statement_resources = [statement_resources]
        if allows(statement_actions, action) and any(
            fnmatch.fnmatchcase(resource, pattern) for pattern in statement_resources
        ):
            return True
    return False


def main():
    policy = generator.policy(ACCOUNT_ID, ZONE_ID)
    rendered = json.dumps(policy, separators=(",", ":"))
    assert len(rendered) <= POLICY_LIMIT, len(rendered)
    maximum_zone_rendered = json.dumps(
        generator.policy(ACCOUNT_ID, "Z" + ("A" * 31)), separators=(",", ":")
    )
    assert len(maximum_zone_rendered) <= POLICY_LIMIT, len(maximum_zone_rendered)
    patterns = actions(policy)
    missing = {
        group: sorted(action for action in required if not allows(patterns, action))
        for group, required in REQUIRED_ACTIONS.items()
    }
    missing = {group: values for group, values in missing.items() if values}
    assert not missing, missing

    by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
    buckets = by_sid["BootstrapAndManageNamedBuckets"]["Resource"]
    state_bucket = f"arn:aws:s3:::trade-recommender-{ACCOUNT_ID}-tfstate"
    backup_bucket = f"arn:aws:s3:::trade-recommender-{ACCOUNT_ID}-backups"
    assert buckets == [
        state_bucket,
        backup_bucket,
    ]
    assert allows_on(policy, "s3:GetAccelerateConfiguration", backup_bucket)
    assert allows_on(policy, "s3:GetReplicationConfiguration", backup_bucket)
    assert allows_on(policy, "s3:GetObject", f"{state_bucket}/production/terraform.tfstate")
    assert allows_on(policy, "s3:PutObject", f"{backup_bucket}/deployment/Caddyfile")
    assert not allows_on(policy, "s3:GetObject", f"{backup_bucket}/postgres/backup.sql.gz")
    assert allows_on(
        policy,
        "ecr:DescribeRepositories",
        f"arn:aws:ecr:us-east-1:{ACCOUNT_ID}:repository/trade-recommender",
    )
    assert by_sid["ManageRegionalSingleHostInfrastructure"]["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "us-east-1"}
    }
    assert by_sid["PassOnlyExactRoleToEc2"]["Resource"] == (
        f"arn:aws:iam::{ACCOUNT_ID}:role/trade-recommender-instance"
    )
    assert by_sid["ManageOnlyApplicationARecord"]["Resource"] == (
        f"arn:aws:route53:::hostedzone/{ZONE_ID}"
    )
    assert by_sid["ManageOnlyApplicationARecord"]["Condition"] == {
        "ForAllValues:StringEquals": {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames": ["fx-forecast.thomsyne.dev"],
            "route53:ChangeResourceRecordSetsRecordTypes": ["A"],
        }
    }
    assert by_sid["SendCommandsOnlyToApplicationInstances"]["Condition"] == {
        "StringEquals": {"ssm:resourceTag/Application": "trade-recommender"}
    }
    assert by_sid["WriteOnlyExactProductionEnvironmentParameter"]["Action"] == ("ssm:PutParameter")
    parameter = f"arn:aws:ssm:us-east-1:{ACCOUNT_ID}:parameter/trade-recommender/production-env"
    assert allows_on(policy, "ssm:PutParameter", parameter)
    assert not allows_on(policy, "ssm:GetParameter", parameter)
    print(f"deploy IAM policy audit passed ({len(rendered)} compact characters)")


if __name__ == "__main__":
    main()
