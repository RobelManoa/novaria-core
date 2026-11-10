resource "aws_cloudwatch_log_group" "service" {
  for_each = toset(var.services)

  name              = "/${var.project}/${var.environment}/${each.key}"
  retention_in_days = var.retention_days
}
