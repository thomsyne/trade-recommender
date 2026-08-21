#!/bin/bash
set -Eeuo pipefail

version="${1:?Terraform version is required}"
destination="${2:?Installation directory is required}"
case "$version" in
  ""|*[!0-9.]*) echo "Invalid Terraform version: $version" >&2; exit 2 ;;
esac

archive="terraform_${version}_linux_amd64.zip"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT INT TERM

curl --fail --silent --show-error --location \
  "https://releases.hashicorp.com/terraform/${version}/${archive}" \
  --output "$workdir/$archive"
curl --fail --silent --show-error --location \
  "https://releases.hashicorp.com/terraform/${version}/terraform_${version}_SHA256SUMS" \
  --output "$workdir/SHA256SUMS"

checksum="$(awk -v archive="$archive" '$2 == archive { print }' "$workdir/SHA256SUMS")"
[ -n "$checksum" ]
[ "$(printf '%s\n' "$checksum" | wc -l)" -eq 1 ]
printf '%s\n' "$checksum" > "$workdir/archive.sha256"
(
  cd "$workdir"
  sha256sum --check archive.sha256
)

mkdir -p "$destination"
unzip -q "$workdir/$archive" -d "$destination"
