#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def policy(account_id, zone_id):
    region = "us-east-1"
    prefix = "trade-recommender"
    state_bucket = f"arn:aws:s3:::{prefix}-{account_id}-tfstate"
    backup_bucket = f"arn:aws:s3:::{prefix}-{account_id}-backups"
    instance_role = f"arn:aws:iam::{account_id}:role/{prefix}-instance"
    instance_profile = f"arn:aws:iam::{account_id}:instance-profile/{prefix}-instance"
    zone = f"arn:aws:route53:::hostedzone/{zone_id}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DiscoverAccount",
                "Effect": "Allow",
                "Action": "sts:GetCallerIdentity",
                "Resource": "*",
            },
            {
                "Sid": "DiscoverRoute53HostedZones",
                "Effect": "Allow",
                "Action": "route53:ListHostedZones",
                "Resource": "*",
            },
            {
                "Sid": "DiscoverRegionalResourcesAndCommandStatus",
                "Effect": "Allow",
                "Action": [
                    "ec2:Describe*",
                    "ssm:DescribeInstanceInformation",
                    "ssm:GetCommandInvocation",
                ],
                "Resource": "*",
                "Condition": {"StringEquals": {"aws:RequestedRegion": region}},
            },
            {
                "Sid": "BootstrapAndManageNamedBuckets",
                "Effect": "Allow",
                "Action": [
                    "s3:CreateBucket",
                    "s3:DeleteBucket",
                    "s3:GetBucket*",
                    "s3:ListBucket",
                    "s3:ListBucketVersions",
                    "s3:PutBucketVersioning",
                    "s3:GetEncryptionConfiguration",
                    "s3:PutEncryptionConfiguration",
                    "s3:PutBucketPublicAccessBlock",
                    "s3:GetLifecycleConfiguration",
                    "s3:PutLifecycleConfiguration",
                    "s3:DeleteLifecycleConfiguration",
                    "s3:PutBucketTagging",
                    "s3:DeleteBucketTagging",
                ],
                "Resource": [state_bucket, backup_bucket],
            },
            {
                "Sid": "TerraformStateAndNativeLockfile",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": [
                    f"{state_bucket}/production/terraform.tfstate",
                    f"{state_bucket}/production/terraform.tfstate.tflock",
                ],
            },
            {
                "Sid": "PublishDeploymentManifests",
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject"],
                "Resource": f"{backup_bucket}/deployment/*",
            },
            {
                "Sid": "AuthenticateAndPushApplicationImage",
                "Effect": "Allow",
                "Action": "ecr:GetAuthorizationToken",
                "Resource": "*",
            },
            {
                "Sid": "ManageNamedEcrRepository",
                "Effect": "Allow",
                "Action": [
                    "ecr:CreateRepository",
                    "ecr:DeleteRepository",
                    "ecr:DescribeRepositories",
                    "ecr:ListTagsForResource",
                    "ecr:TagResource",
                    "ecr:UntagResource",
                    "ecr:GetLifecyclePolicy",
                    "ecr:PutLifecyclePolicy",
                    "ecr:DeleteLifecyclePolicy",
                    "ecr:GetRepositoryPolicy",
                    "ecr:PutImageScanningConfiguration",
                    "ecr:PutImageTagMutability",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:ListImages",
                ],
                "Resource": f"arn:aws:ecr:{region}:{account_id}:repository/{prefix}",
            },
            {
                "Sid": "ManageRegionalSingleHostInfrastructure",
                "Effect": "Allow",
                "Action": [
                    "ec2:CreateVpc",
                    "ec2:DeleteVpc",
                    "ec2:ModifyVpcAttribute",
                    "ec2:CreateSubnet",
                    "ec2:DeleteSubnet",
                    "ec2:ModifySubnetAttribute",
                    "ec2:CreateInternetGateway",
                    "ec2:AttachInternetGateway",
                    "ec2:DetachInternetGateway",
                    "ec2:DeleteInternetGateway",
                    "ec2:CreateRouteTable",
                    "ec2:DeleteRouteTable",
                    "ec2:AssociateRouteTable",
                    "ec2:DisassociateRouteTable",
                    "ec2:CreateRoute",
                    "ec2:DeleteRoute",
                    "ec2:CreateSecurityGroup",
                    "ec2:DeleteSecurityGroup",
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:RevokeSecurityGroupIngress",
                    "ec2:AuthorizeSecurityGroupEgress",
                    "ec2:RevokeSecurityGroupEgress",
                    "ec2:AllocateAddress",
                    "ec2:AssociateAddress",
                    "ec2:DisassociateAddress",
                    "ec2:ReleaseAddress",
                    "ec2:ImportKeyPair",
                    "ec2:DeleteKeyPair",
                    "ec2:RunInstances",
                    "ec2:TerminateInstances",
                    "ec2:StartInstances",
                    "ec2:StopInstances",
                    "ec2:ModifyInstanceAttribute",
                    "ec2:ModifyInstanceMetadataOptions",
                    "ec2:CreateTags",
                    "ec2:DeleteTags",
                ],
                "Resource": "*",
                "Condition": {"StringEquals": {"aws:RequestedRegion": region}},
            },
            {
                "Sid": "ManageExactInstanceRole",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateRole",
                    "iam:DeleteRole",
                    "iam:GetRole",
                    "iam:UpdateRole",
                    "iam:UpdateAssumeRolePolicy",
                    "iam:TagRole",
                    "iam:UntagRole",
                    "iam:PutRolePolicy",
                    "iam:GetRolePolicy",
                    "iam:DeleteRolePolicy",
                    "iam:ListRolePolicies",
                    "iam:ListInstanceProfilesForRole",
                    "iam:AttachRolePolicy",
                    "iam:DetachRolePolicy",
                    "iam:ListAttachedRolePolicies",
                ],
                "Resource": instance_role,
            },
            {
                "Sid": "ManageExactInstanceProfile",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateInstanceProfile",
                    "iam:DeleteInstanceProfile",
                    "iam:GetInstanceProfile",
                    "iam:TagInstanceProfile",
                    "iam:UntagInstanceProfile",
                    "iam:AddRoleToInstanceProfile",
                    "iam:RemoveRoleFromInstanceProfile",
                ],
                "Resource": instance_profile,
            },
            {
                "Sid": "PassOnlyExactRoleToEc2",
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": instance_role,
                "Condition": {"StringEquals": {"iam:PassedToService": "ec2.amazonaws.com"}},
            },
            {
                "Sid": "CreateEc2ServiceLinkedRoleIfAccountNeedsIt",
                "Effect": "Allow",
                "Action": "iam:CreateServiceLinkedRole",
                "Resource": "arn:aws:iam::*:role/aws-service-role/ec2.amazonaws.com/AWSServiceRoleForEC2*",
                "Condition": {"StringEquals": {"iam:AWSServiceName": "ec2.amazonaws.com"}},
            },
            {
                "Sid": "WriteOnlyExactProductionEnvironmentParameter",
                "Effect": "Allow",
                "Action": "ssm:PutParameter",
                "Resource": f"arn:aws:ssm:{region}:{account_id}:parameter/trade-recommender/production-env",
            },
            {
                "Sid": "UseAwsRunShellScriptDocument",
                "Effect": "Allow",
                "Action": "ssm:SendCommand",
                "Resource": f"arn:aws:ssm:{region}::document/AWS-RunShellScript",
            },
            {
                "Sid": "SendCommandsOnlyToApplicationInstances",
                "Effect": "Allow",
                "Action": "ssm:SendCommand",
                "Resource": f"arn:aws:ec2:{region}:{account_id}:instance/*",
                "Condition": {"StringEquals": {"ssm:resourceTag/Application": prefix}},
            },
            {
                "Sid": "ReadExactPublicHostedZone",
                "Effect": "Allow",
                "Action": [
                    "route53:GetHostedZone",
                    "route53:ListResourceRecordSets",
                    "route53:ListTagsForResource",
                ],
                "Resource": zone,
            },
            {
                "Sid": "ManageOnlyApplicationARecord",
                "Effect": "Allow",
                "Action": "route53:ChangeResourceRecordSets",
                "Resource": zone,
                "Condition": {
                    "ForAllValues:StringEquals": {
                        "route53:ChangeResourceRecordSetsNormalizedRecordNames": [
                            "fx-forecast.thomsyne.dev"
                        ],
                        "route53:ChangeResourceRecordSetsRecordTypes": ["A"],
                    }
                },
            },
            {
                "Sid": "WaitForDnsChange",
                "Effect": "Allow",
                "Action": "route53:GetChange",
                "Resource": "arn:aws:route53:::change/*",
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Render the GitHub deployment IAM policy")
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--route53-zone-id", required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not re.fullmatch(r"[0-9]{12}", arguments.account_id):
        parser.error("--account-id must be exactly 12 digits")
    if not re.fullmatch(r"Z[A-Z0-9]+", arguments.route53_zone_id):
        parser.error(
            "--route53-zone-id must begin with Z and contain only uppercase letters/digits"
        )
    rendered = json.dumps(policy(arguments.account_id, arguments.route53_zone_id), indent=2) + "\n"
    json.loads(rendered)
    if arguments.output:
        arguments.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
