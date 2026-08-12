output "tailnet" {
  description = "Tailnet the nodes joined."
  value       = var.tailnet
}

output "subnet_router_public_ip" {
  description = "Elastic IP of the subnet router. The app node's egress appears to come from here."
  value       = aws_eip.subnet_router.public_ip
}

output "advertised_route" {
  description = "The CIDR the subnet router advertises. Pass this to verify.py."
  value       = var.vpc_cidr
}

output "app_private_ip" {
  description = "The app node has no public address. Reach it over the tailnet at this address."
  value       = aws_instance.app.private_ip
}

output "app_hostname" {
  description = "Tailnet hostname of the app node, for picking it out of tailscale status."
  value       = "${var.project}-app"
}
