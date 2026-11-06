output "repository_urls" {
  description = "Adresse de chaque dépôt, par service."
  value       = { for service, repository in aws_ecr_repository.service : service => repository.repository_url }
}
