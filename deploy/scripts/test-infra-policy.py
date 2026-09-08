#!/usr/bin/env python3
"""Static security-group policy assertions for infra/*.tf.

Fails when the proposed infrastructure could expose SSH to the Internet by
default, drops the HTTP/HTTPS ingress the deployment needs, or relaxes the
IMDSv2 requirement. This is a text-level guard that runs without Terraform;
`terraform validate` remains the syntax/type authority. The SSH prefix-length
floor is read numerically from both the variable validation and the
security-group precondition, and a Python mirror of that rule is evaluated on
representative inputs (Internet-wide, /1 halves, /2 quarters, "/00", IPv6
halves, narrow CIDRs, break-glass).
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
PREFIX_FLOOR = re.compile(r'try\(tonumber\(element\(split\("/", cidr\), 1\)\), -1\) >= (\d+)')
MINIMUM_PREFIX_LENGTH = 8


def prefix_floor(text, where):
    found = PREFIX_FLOOR.findall(text)
    check(len(found) == 1, f"{where} must parse the SSH prefix length numerically exactly once")
    return int(found[0]) if len(found) == 1 else None


def rule_allows(cidrs, break_glass, floor):
    """Python mirror of the Terraform rule: every entry's numeric prefix >= floor."""
    if break_glass:
        return True
    for cidr in cidrs:
        parts = cidr.split("/")
        try:
            prefix = int(parts[1]) if len(parts) == 2 else -1
        except ValueError:
            prefix = -1
        if prefix < floor:
            return False
    return True


precondition_floor = prefix_floor(security_group, "security-group precondition")
check(
    "allow_public_ssh_break_glass" in security_group and precondition_floor is not None,
    "security group must carry the break-glass precondition with a numeric SSH prefix floor",
)

ssh_cidrs = block(VARIABLES, 'variable "ssh_cidrs"')
check(re.search(r"default\s*=\s*\[\]", ssh_cidrs), "ssh_cidrs default must be []")
variable_floor = prefix_floor(ssh_cidrs, "ssh_cidrs validation")
check(
    variable_floor is not None and "allow_public_ssh_break_glass" in ssh_cidrs,
    "ssh_cidrs validation must enforce a numeric prefix floor unless the break-glass flag is set",
)
check(
    variable_floor == precondition_floor,
    "ssh_cidrs validation and the security-group precondition must enforce the same floor",
)
check(
    variable_floor is not None and variable_floor >= MINIMUM_PREFIX_LENGTH,
    f"SSH prefix floor must be at least /{MINIMUM_PREFIX_LENGTH}",
)
floor = variable_floor if variable_floor is not None else MINIMUM_PREFIX_LENGTH
for cidrs, with_break_glass, expected in (
    ([], False, True),
    (["203.0.113.10/32"], False, True),
    (["198.51.100.0/24"], False, True),
    (["10.0.0.0/8"], False, True),
    (["0.0.0.0/0"], False, False),
    (["::/0"], False, False),
    (["0.0.0.0/00"], False, False),
    (["0.0.0.0/1", "128.0.0.0/1"], False, False),
    (["0.0.0.0/2", "64.0.0.0/2", "128.0.0.0/2", "192.0.0.0/2"], False, False),
    (["::/1", "8000::/1"], False, False),
    (["10.0.0.0/8", "0.0.0.0/7"], False, False),
    (["0.0.0.0"], False, False),
    (["0.0.0.0/0"], True, True),
):
    check(
        rule_allows(cidrs, with_break_glass, floor) == expected,
        f"prefix rule mirror: {cidrs} break_glass={with_break_glass} expected allowed={expected}",
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
