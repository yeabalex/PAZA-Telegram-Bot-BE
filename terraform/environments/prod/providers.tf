terraform {
  required_version = ">= 1.5.0"

  # Configure backend for prod environment (e.g. S3 / local)
  # backend "s3" {
  #   bucket = "addis-event-bot-tfstate-prod"
  #   key    = "prod/terraform.tfstate"
  #   region = "us-east-1"
  # }
}
