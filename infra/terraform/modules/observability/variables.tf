variable "project" {
  description = "Nom du projet, premier niveau du nom des groupes de journaux."
  type        = string
  default     = "novaria"
}

variable "environment" {
  description = "Nom de l'environnement (dev ou demo), deuxième niveau du nom."
  type        = string
}

variable "services" {
  description = "Un groupe de journaux CloudWatch par service."
  type        = list(string)
}

variable "retention_days" {
  description = "Durée de conservation des journaux, en jours (valeurs acceptées par CloudWatch : 1, 3, 5, 7, 14, 30, 60, 90…)."
  type        = number
  default     = 14
}
