# The tailnet policy file is deliberately not managed here. See docs/policy-additions.hujson.
#
# tailscale_acl is a whole-file resource, and so is the underlying API: there is
# no PATCH, only GET and POST. Any repository that manages it must therefore hold
# a complete policy, which means shipping the author's own rules and replacing
# whatever the operator already had. The API can guard against that with
# If-Match: ts-default, which refuses the write unless the policy is still the
# untouched default, but the provider exposes no way to send it.
#
# So the boundary sits here instead: this configuration owns the auth keys, which
# it creates and destroys cleanly, and the operator owns their policy file.

# One key per node, each tagged for its role.
#
# ephemeral: Tailscale removes the device from the tailnet once it goes offline,
#   so terraform destroy leaves nothing behind across repeated cycles. The
#   trade-off: stopping rather than terminating an instance can also drop it.
# reusable = false: a key that registers one node and is then spent.
# expiry = 3600: comfortably covers a full apply, worthless an hour later.
resource "tailscale_tailnet_key" "subnet_router" {
  description   = "${var.project} subnet router created by terraform"
  tags          = ["tag:aws-subnet-router"]
  reusable      = false
  ephemeral     = true
  preauthorized = true
  expiry        = 3600
}

resource "tailscale_tailnet_key" "app" {
  description   = "${var.project} app node created by terraform"
  tags          = ["tag:aws-app"]
  reusable      = false
  ephemeral     = true
  preauthorized = true
  expiry        = 3600
}
