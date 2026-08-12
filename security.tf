# Note what is absent: there is no inbound rule for TCP 22 in this file, and no
# aws_key_pair resource anywhere in the repository. SSH access is provided
# entirely by Tailscale SSH.
resource "aws_security_group" "subnet_router" {
  # name_prefix rather than name: a group left behind by an interrupted destroy
  # blocks the next apply on a duplicate name. The Name tag is what the console
  # lists, so nothing readable is lost.
  name_prefix = "${var.project}-subnet-router-"
  description = "Subnet router: Tailscale direct connections and NAT for the private subnet"
  vpc_id      = aws_vpc.this.id

  # Optional but worthwhile. Tailscale works through NAT without this, but an
  # open 41641 improves the odds of a direct connection instead of a DERP relay.
  ingress {
    description = "Tailscale direct connections"
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Required for this instance to act as the NAT for the private subnet.
  ingress {
    description = "All traffic from the private subnet"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.private_subnet_cidr]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-subnet-router" }
}

# This group can be this tight because Tailscale's subnet route masquerading is
# on by default: traffic arriving from the tailnet is rewritten to the router's
# own private address before it reaches this node. Disabling masquerading with
# --snat-subnet-routes=false would break this rule.
resource "aws_security_group" "app" {
  name_prefix = "${var.project}-app-"
  description = "App node: reachable only from the subnet router"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "All traffic from the subnet router"
    from_port       = 0
    to_port         = 0
    protocol        = "-1"
    security_groups = [aws_security_group.subnet_router.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-app" }
}
