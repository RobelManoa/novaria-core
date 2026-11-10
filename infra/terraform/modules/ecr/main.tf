resource "aws_ecr_repository" "service" {
  for_each = toset(var.services)

  name                 = "${var.prefix}-${each.key}"
  image_tag_mutability = "IMMUTABLE" # une étiquette = une révision (le déploiement étiquette avec le commit)
  force_delete         = var.force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "service" {
  for_each = aws_ecr_repository.service

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
