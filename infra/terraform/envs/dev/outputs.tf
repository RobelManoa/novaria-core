output "ecr_repository_urls" {
  description = "Adresse de chaque dépôt d'images, par service."
  value       = module.ecr.repository_urls
}

output "log_group_names" {
  description = "Groupe de journaux de chaque service."
  value       = module.observability.log_group_names
}
