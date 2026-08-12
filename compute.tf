data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = [var.ami_name_filter]
  }
}

resource "aws_instance" "subnet_router" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  private_ip                  = var.subnet_router_private_ip
  vpc_security_group_ids      = [aws_security_group.subnet_router.id]
  associate_public_ip_address = true

  # Required for this instance to forward packets that are neither from nor to
  # itself. Without it, AWS silently drops the NAT traffic.
  source_dest_check = false

  user_data = templatefile("${path.module}/cloud-init/subnet-router.yaml", {
    auth_key     = tailscale_tailnet_key.subnet_router.key
    vpc_cidr     = var.vpc_cidr
    private_cidr = var.private_subnet_cidr
    hostname     = "${var.project}-subnet-router"
  })

  # autoApprovers is evaluated at registration time, so the policy must already
  # carry it before this node comes up. Terraform cannot enforce that here
  # because it does not own the policy file; it is a prerequisite instead, and
  # verify.py is what catches you having skipped it.

  # Nothing above refers to the internet gateway or the public route table, so
  # without this the instance can boot, and cloud-init can reach apt, before the
  # subnet has any path off the VPC. The elastic IP inherits the ordering and
  # needs it too: AWS refuses to associate one until a gateway is attached.
  depends_on = [aws_route_table_association.public]

  tags = { Name = "${var.project}-subnet-router" }
}

resource "aws_eip" "subnet_router" {
  instance = aws_instance.subnet_router.id
  domain   = "vpc"

  tags = { Name = "${var.project}-subnet-router" }
}

# The private subnet's only path off the VPC.
resource "aws_route" "private_default" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = aws_instance.subnet_router.primary_network_interface_id
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.private.id
  private_ip             = var.app_private_ip
  vpc_security_group_ids = [aws_security_group.app.id]

  # No public IP, and no key_name. The only way in is Tailscale SSH.
  associate_public_ip_address = false

  user_data = templatefile("${path.module}/cloud-init/app.yaml", {
    auth_key = tailscale_tailnet_key.app.key
    hostname = "${var.project}-app"
  })

  # This node has no egress until the private subnet's default route exists and
  # points at the router, so it must not launch before that route does. The
  # association is named separately because the route only refers to the route
  # table, not to the subnet being attached to it.
  depends_on = [
    aws_route.private_default,
    aws_route_table_association.private,
  ]

  tags = { Name = "${var.project}-app" }
}
