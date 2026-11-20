# Squelette sans compte : se valide (fmt, validate, tflint, Snyk IaC) mais ne se planifie pas
# et ne s'applique pas (ADR-023). Aucun état distant : le bucket S3 est l'objet de CLD-10 (différée).
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      projet       = "novaria"
      env          = "dev"
      proprietaire = var.owner
    }
  }
}

module "ecr" {
  source = "../../modules/ecr"

  prefix    = "novaria-dev"
  services  = var.services
  protected = true # dépôts d'images protégés : `terraform destroy` échoue
}

module "observability" {
  source = "../../modules/observability"

  environment    = "dev"
  services       = var.services
  retention_days = 14
  protected      = true # les journaux survivent à une destruction
}
