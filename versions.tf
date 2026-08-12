terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.29"
    }
  }
}

provider "aws" {
  region = var.region
}

# Credentials come from TF_VAR_tailscale_oauth_client_id and
# TF_VAR_tailscale_oauth_client_secret. Never from a committed file.
provider "tailscale" {
  oauth_client_id     = var.tailscale_oauth_client_id
  oauth_client_secret = var.tailscale_oauth_client_secret
}
