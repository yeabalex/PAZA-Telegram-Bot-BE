# Terraform Directory Structure

This directory contains the Terraform configuration structure separated by environment (`dev` and `prod`).

## Directory Layout

```
terraform/
├── environments/
│   ├── dev/
│   │   ├── main.tf
│   │   ├── providers.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── terraform.tfvars.example
│   └── prod/
│       ├── main.tf
│       ├── providers.tf
│       ├── variables.tf
│       ├── outputs.tf
│       └── terraform.tfvars.example
└── modules/
```

## Usage

### Development Environment
```bash
cd terraform/environments/dev
terraform init
terraform plan
```

### Production Environment
```bash
cd terraform/environments/prod
terraform init
terraform plan
```
