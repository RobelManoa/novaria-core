variable "region" {
  description = "Région AWS (ADR-006 : eu-west-1)."
  type        = string
  default     = "eu-west-1"
}

variable "owner" {
  description = "Valeur de l'étiquette « proprietaire » appliquée à chaque ressource."
  type        = string
  default     = "binome-novaria"
}

variable "services" {
  description = "Images construites par la CI (job docker) : un dépôt ECR et un groupe de journaux par entrée."
  type        = list(string)
  default     = ["alerte", "collecte", "reponse", "traitement", "frontend"]
}
