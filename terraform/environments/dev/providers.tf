terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.4"
    }
  }

  # Uncomment and configure if using S3 state backend
  # backend "s3" {
  #   bucket         = "addis-event-bot-tfstate-dev"
  #   key            = "dev/terraform.tfstate"
  #   region         = "us-east-1"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "paza-event-bot"
      Environment = "dev"
      ManagedBy   = "Terraform"
    }
  }
}
