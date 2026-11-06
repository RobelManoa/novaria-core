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
