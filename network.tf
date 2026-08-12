resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = var.project }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = var.project }
}

# Public subnet. Holds the subnet router, which needs a route to the internet
# gateway both for its own egress and to NAT the private subnet.
resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.public_subnet_cidr
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = { Name = "${var.project}-public" }
}

# Private subnet. Deliberately has no route to the internet gateway. Its only
# path off the VPC is through the subnet router.
resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.private_subnet_cidr
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = { Name = "${var.project}-private" }
}

data "aws_availability_zones" "available" {
  state = "available"

  # Both subnets take names[0]. Local Zones sort ahead of the standard zones,
  # because the hyphen in us-west-2-lax-1a beats the letter in us-west-2a, so an
  # account opted into one would land the whole stack somewhere t3.micro may not
  # be offered. This filter keeps the list to ordinary zones.
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "${var.project}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# The 0.0.0.0/0 route for this table is created in compute.tf, because it
# targets the subnet router's network interface.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.project}-private" }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}
