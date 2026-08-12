variable "project" {
  description = "Name prefix applied to every resource."
  type        = string
  default     = "tailscale-aws"
}

variable "region" {
  description = "AWS region. us-west-2 is the cheapest West Coast region."
  type        = string
  default     = "us-west-2"
}

variable "vpc_cidr" {
  description = "VPC CIDR. Deliberately not 10.0.0.0/16, so it cannot overlap a home LAN on 10.0.0.0/24 and create an overlapping subnet problem."
  type        = string
  default     = "10.100.0.0/16"
}

variable "public_subnet_cidr" {
  description = "Public subnet. Holds the subnet router."
  type        = string
  default     = "10.100.1.0/24"
}

variable "private_subnet_cidr" {
  description = "Private subnet. No route to the internet gateway."
  type        = string
  default     = "10.100.2.0/24"
}

variable "subnet_router_private_ip" {
  description = "Fixed so the README and the architecture diagram stay accurate across rebuilds."
  type        = string
  default     = "10.100.1.10"
}

variable "app_private_ip" {
  description = "Fixed for the same reason."
  type        = string
  default     = "10.100.2.20"
}

variable "instance_type" {
  description = "x86 rather than the cheaper t4g, because a mismatched AMI architecture is the most common first-time failure and the saving is pennies."
  type        = string
  default     = "t3.micro"
}

variable "ami_name_filter" {
  description = "Canonical AMI name to deploy. Pinned to one build so a rebuild cannot silently pick up an image Canonical published overnight. It is a name rather than an AMI ID so it still resolves in any region. Set it to ubuntu/images/hvm-ssd*/ubuntu-noble-24.04-amd64-server-* to track the latest instead."
  type        = string
  default     = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-20260714"
}

variable "tailnet" {
  description = "Tailnet name, used in outputs and the README."
  type        = string
}

variable "tailscale_oauth_client_id" {
  description = "Set via TF_VAR_tailscale_oauth_client_id."
  type        = string
  sensitive   = true
}

variable "tailscale_oauth_client_secret" {
  description = "Set via TF_VAR_tailscale_oauth_client_secret."
  type        = string
  sensitive   = true
}
