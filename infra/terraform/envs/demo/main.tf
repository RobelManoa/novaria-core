# Squelette sans compte : se valide (fmt, validate, tflint, Snyk IaC) mais ne se planifie pas
# et ne s'applique pas (ADR-023). L'environnement demo se détruit après chaque séance (CLD-21).
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      projet       = "novaria"
      env          = "demo"
      proprietaire = var.owner
    }
  }
}

module "ecr" {
  source = "../../modules/ecr"

  prefix       = "novaria-demo"
  services     = var.services
  force_delete = true
}

module "observability" {
  source = "../../modules/observability"

  environment    = "demo"
  services       = var.services
  retention_days = 7
}
