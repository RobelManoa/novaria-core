# Un dépôt d'images par service. Les images sont des **données persistantes** : un dépôt protégé ne se détruit pas
# (`prevent_destroy`), un dépôt jetable (environnement demo, détruit après chaque séance) se détruit même plein.
# Terraform ne sait pas rendre `prevent_destroy` conditionnel : il y a donc deux blocs, un seul est créé selon `var.protected`.
locals {
  protected_services  = var.protected ? toset(var.services) : toset([])
  disposable_services = var.protected ? toset([]) : toset(var.services)
}

resource "aws_ecr_repository" "protected" {
  for_each = local.protected_services

  name                 = "${var.prefix}-${each.key}"
  image_tag_mutability = "IMMUTABLE" # une étiquette = une révision (le déploiement étiquette avec le commit)
  force_delete         = false       # jamais de purge des images à la destruction

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "disposable" {
  for_each = local.disposable_services

  name                 = "${var.prefix}-${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

locals {
  repositories = merge(aws_ecr_repository.protected, aws_ecr_repository.disposable)
}

resource "aws_ecr_lifecycle_policy" "service" {
  for_each = local.repositories

  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Conserver les ${var.keep_images} dernières images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.keep_images
      }
      action = { type = "expire" }
    }]
  })
}
