variable "aws_region" {
  description = "AWS Region to deploy dev environment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
  default     = "paza-event-bot"
}

variable "instance_type" {
  description = "EC2 instance type for dev server"
  type        = string
  default     = "t3.micro"
}

variable "allowed_ssh_cidr" {
  description = "CIDR block allowed for SSH access"
  type        = string
  default     = "0.0.0.0/0"
}

variable "ssh_user" {
  description = "Custom deployment username created on EC2 server"
  type        = string
  default     = "deployer"
}

