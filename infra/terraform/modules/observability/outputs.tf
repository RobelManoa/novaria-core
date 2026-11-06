output "log_group_names" {
  description = "Nom du groupe de journaux de chaque service."
  value       = { for service, group in aws_cloudwatch_log_group.service : service => group.name }
}
