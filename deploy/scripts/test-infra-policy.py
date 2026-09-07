#!/usr/bin/env python3
"""Static security-group policy assertions for infra/*.tf.

Fails when the proposed infrastructure could expose SSH to the Internet by
default, drops the HTTP/HTTPS ingress the deployment needs, or relaxes the
IMDSv2 requirement. This is a text-level guard that runs without Terraform;
`terraform validate` remains the syntax/type authority.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "infra"
MAIN = (ROOT / "main.tf").read_text()
VARIABLES = (ROOT / "variables.tf").read_text()
EXAMPLE = (ROOT / "terraform.tfvars.example").read_text()
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def block(text, header):
    start = text.index(header)
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError(f"unterminated block for {header}")


security_group = block(MAIN, 'resource "aws_security_group" "instance"')
ingress_blocks = re.findall(r'(?:dynamic "ingress"|ingress)\s*\{.*?\n  \}', security_group, re.S)
check(ingress_blocks, "security group declares no ingress blocks")

for ingress in ingress_blocks:
    ports = re.findall(r"from_port\s*=\s*(\d+)", ingress)
    cidrs = re.findall(r"cidr_blocks\s*=\s*\[([^\]]*)\]", ingress)
    if "22" in ports:
        check(
            "cidr_blocks = var.ssh_cidrs" in ingress,
            "port 22 ingress must derive its CIDRs from var.ssh_cidrs, never a literal",
        )
        check(
            "0.0.0.0/0" not in ingress and "::/0" not in ingress,
            "port 22 ingress must not carry an Internet-wide literal CIDR",
        )
        check(
            "for_each = length(var.ssh_cidrs) == 0 ? [] : [1]" in ingress,
            "port 22 ingress must be absent when ssh_cidrs is empty",
        )
    for port in ports:
        if port not in {"22", "80", "443"}:
            failures.append(f"unexpected ingress port {port}")

for port, protocol in (("80", "tcp"), ("443", "tcp"), ("443", "udp")):
    check(
        re.search(
            rf'from_port\s*=\s*{port}\s*\n\s*to_port\s*=\s*{port}\s*\n\s*protocol\s*=\s*"{protocol}"\s*\n\s*cidr_blocks\s*=\s*\["0\.0\.0\.0/0"\]',
            security_group,
        ),
        f"public {protocol}/{port} ingress must remain",
    )
check(
    "allow_public_ssh_break_glass" in security_group and 'endswith(cidr, "/0")' in security_group,
    "security group must carry the break-glass precondition against /0 SSH CIDRs",
)

ssh_cidrs = block(VARIABLES, 'variable "ssh_cidrs"')
check(re.search(r"default\s*=\s*\[\]", ssh_cidrs), "ssh_cidrs default must be []")
check(
    'endswith(cidr, "/0")' in ssh_cidrs and "allow_public_ssh_break_glass" in ssh_cidrs,
    "ssh_cidrs validation must reject /0 CIDRs unless the break-glass flag is set",
)
check("cidrhost(cidr, 0)" in ssh_cidrs, "ssh_cidrs validation must require valid CIDR syntax")
break_glass = block(VARIABLES, 'variable "allow_public_ssh_break_glass"')
check(re.search(r"default\s*=\s*false", break_glass), "break-glass flag must default to false")
check(
    re.search(r"allow_public_ssh_break_glass\s*=\s*false", EXAMPLE),
    "tfvars example must keep the break-glass flag false",
)
check(
    not re.search(r'ssh_cidrs\s*=\s*\[[^\]]*"0\.0\.0\.0/0"', EXAMPLE),
    "tfvars example must not suggest an Internet-wide SSH CIDR",
)

instance = block(MAIN, 'resource "aws_instance" "app"')
check(
    re.search(r'http_tokens\s*=\s*"required"', instance),
    'IMDSv2 must remain required (http_tokens = "required")',
)
check(
    re.search(r'http_endpoint\s*=\s*"enabled"', instance),
    "instance metadata endpoint must remain enabled for the instance role",
)

if failures:
    for failure in failures:
        print(f"infra policy: {failure}", file=sys.stderr)
    sys.exit(1)
print("infra security-group policy assertions passed")
