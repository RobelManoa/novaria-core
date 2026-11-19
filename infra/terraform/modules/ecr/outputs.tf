output "repository_urls" {
  description = "Adresse de chaque dépôt, par service."
  value       = { for service, repository in local.repositories : service => repository.repository_url }
}
