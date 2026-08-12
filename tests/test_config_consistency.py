"""The VPC CIDR and the two tag names are spelled out in more than one file, and
nothing in Terraform can enforce that they agree. The policy file is not a
Terraform resource, so a CIDR changed in one place and not the other produces a
route that is advertised and never approved: a healthy-looking apply, then
verify.py sitting through its full five minute deadline before reporting it.
These tests turn that into a failure that takes a fifth of a second.

The same reasoning covers the version constraint advertised in the README, which
is the one duplicated value a reader sees before anything else.
"""

import json
import os
import re
import sys
import unittest
import urllib.parse

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import verify

POLICY = os.path.join(ROOT, "docs", "policy-additions.hujson")


def load_hujson(path):
    """Parse the HuJSON subset this repository uses: JSON with // comments and
    trailing commas. Written out rather than taken as a dependency, because
    verify.py and these tests are deliberately standard library only. Strings
    are tracked so that a // inside one is never mistaken for a comment.
    """
    with open(path) as handle:
        text = handle.read()

    out = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\":
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
        elif char == '"':
            in_string = True
            out.append(char)
            index += 1
        elif text.startswith("//", index):
            while index < len(text) and text[index] != "\n":
                index += 1
        else:
            out.append(char)
            index += 1

    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def terraform_default(filename, variable):
    with open(os.path.join(ROOT, filename)) as handle:
        text = handle.read()
    block = re.search(rf'variable "{variable}" {{(.*?)\n}}', text, re.S).group(1)
    return re.search(r'default\s*=\s*"([^"]+)"', block).group(1)


def terraform_created_tags():
    with open(os.path.join(ROOT, "tailscale.tf")) as handle:
        text = handle.read()
    return sorted(re.findall(r'tags\s*=\s*\["([^"]+)"\]', text))


class PolicyDocumentTests(unittest.TestCase):
    """The policy file ships as documentation for a human to paste, so nothing
    else would notice it going malformed. Parsing it here is the only check it
    gets short of the Tailscale API rejecting the merged result."""

    def setUp(self):
        self.policy = load_hujson(POLICY)
        self.cidr = terraform_default("variables.tf", "vpc_cidr")

    def test_policy_document_is_parseable(self):
        self.assertIsInstance(self.policy, dict)
        for key in ("tagOwners", "autoApprovers", "grants", "ssh"):
            self.assertIn(key, self.policy)

    def test_autoapprovers_covers_the_vpc_cidr(self):
        routes = self.policy["autoApprovers"]["routes"]
        self.assertIn(
            self.cidr,
            routes,
            f"var.vpc_cidr is {self.cidr} but autoApprovers approves {list(routes)}. "
            "The route would be advertised and never approved.",
        )

    def test_autoapprovers_names_the_tag_terraform_applies(self):
        # .get rather than indexing, so a drifted CIDR fails here as a plain
        # assertion instead of a KeyError on top of the test above reporting it.
        approvers = self.policy["autoApprovers"]["routes"].get(self.cidr, [])
        self.assertIn("tag:aws-subnet-router", approvers)

    def test_a_grant_reaches_the_vpc_cidr(self):
        destinations = [d for grant in self.policy["grants"] for d in grant["dst"]]
        self.assertIn(
            self.cidr,
            destinations,
            f"var.vpc_cidr is {self.cidr} but no grant names it, so the approved "
            "route would carry no permitted traffic.",
        )


class TagConsistencyTests(unittest.TestCase):
    """Three files name the same two tags. Terraform applies them to the keys,
    the policy file decides who may, and verify.py counts devices carrying them.
    A rename in one place fails somewhere unrelated to the edit."""

    def setUp(self):
        self.policy = load_hujson(POLICY)
        self.created = terraform_created_tags()

    def test_terraform_creates_exactly_the_two_expected_tags(self):
        self.assertEqual(self.created, ["tag:aws-app", "tag:aws-subnet-router"])

    def test_every_created_tag_owns_itself_in_tagowners(self):
        # An OAuth client belongs to no autogroup, so a tag owned only by
        # autogroup:admin cannot be applied by Terraform. The symptom is
        # "requested tags are invalid or not permitted" at apply time.
        for tag in self.created:
            self.assertIn(tag, self.policy["tagOwners"], f"{tag} has no owners")
            self.assertIn(
                tag,
                self.policy["tagOwners"][tag],
                f"{tag} must list itself as an owner, not only autogroup:admin",
            )

    def test_verify_checks_the_tags_terraform_creates(self):
        self.assertEqual(sorted([verify.ROUTER_TAG, verify.APP_TAG]), self.created)

    def test_ssh_rules_cover_both_tags(self):
        destinations = [d for rule in self.policy["ssh"] for d in rule["dst"]]
        for tag in self.created:
            self.assertIn(tag, destinations)


class ReadmeBadgeTests(unittest.TestCase):
    """The version badge states a constraint that also lives in versions.tf. A
    badge drifts more quietly than most duplication, because nobody renders the
    README while editing Terraform and the stale value still looks authoritative
    to everyone arriving at the repository."""

    def test_terraform_badge_matches_required_version(self):
        with open(os.path.join(ROOT, "README.md")) as handle:
            readme = handle.read()
        badge = re.search(r"img\.shields\.io/badge/terraform-([^-\s)]+)-", readme)
        self.assertIsNotNone(badge, "the Terraform version badge is missing")
        claimed = urllib.parse.unquote(badge.group(1))

        with open(os.path.join(ROOT, "versions.tf")) as handle:
            required = re.search(
                r'required_version\s*=\s*"([^"]+)"', handle.read()
            ).group(1)

        self.assertEqual(
            claimed.replace(" ", ""),
            required.replace(" ", ""),
            f"the README badge advertises {claimed} but versions.tf requires "
            f"{required}",
        )


if __name__ == "__main__":
    unittest.main()
