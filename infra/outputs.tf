output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "instance_id" { value = aws_instance.app.id }
output "elastic_ip" { value = aws_eip.app.public_ip }
output "public_hostname" { value = trimsuffix(aws_route53_record.app.fqdn, ".") }
output "public_url" { value = "https://${trimsuffix(aws_route53_record.app.fqdn, ".")}" }
output "route53_zone_id" { value = data.aws_route53_zone.public.zone_id }
output "backup_bucket" { value = aws_s3_bucket.backups.id }
output "production_env_parameter" { value = var.production_env_parameter }
