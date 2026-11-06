# Règles de tflint (LOC-06). Lancé par `dev.py terraform-check` ; le plugin AWS est téléchargé depuis GitHub
# à la première exécution (réseau nécessaire). Aucune règle ne contacte AWS : pas de « deep checking ».
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.50.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
