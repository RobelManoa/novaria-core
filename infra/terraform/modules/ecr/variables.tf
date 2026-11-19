variable "prefix" {
  description = "Préfixe des dépôts : un dépôt est nommé <prefix>-<service> (exemple : novaria-dev-collecte)."
  type        = string
}

variable "services" {
  description = "Un dépôt ECR (Elastic Container Registry) par image de service."
  type        = list(string)
}

variable "keep_images" {
  description = "Nombre d'images conservées par dépôt ; les plus anciennes sont supprimées."
  type        = number
  default     = 20
}

variable "force_delete" {
  description = "Vrai : le dépôt se détruit même s'il contient des images (environnement demo, détruit après chaque séance)."
  type        = bool
  default     = false
}

variable "protected" {
  description = "Vrai (défaut) : les dépôts sont protégés, `terraform destroy` échoue (`prevent_destroy`) et les images ne sont jamais purgées. Faux : dépôts jetables (environnement demo)."
  type        = bool
  default     = true

  validation {
    condition     = !(var.protected && var.force_delete)
    error_message = "Un dépôt protégé ne peut pas avoir force_delete à vrai : la protection et la purge des images sont contradictoires."
  }
}
