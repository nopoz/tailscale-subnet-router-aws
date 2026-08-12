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


class ArchitectureDiagramTests(unittest.TestCase):
    """Mermaid renderers disagree about the diagram in three ways that are all
    invisible until someone looks at the rendered page, so each one is pinned
    here. Every rule below was established by rendering candidates through
    GitHub itself and comparing them against a local previewer.

    Line breaks are written as \\n, which is what GitHub understands, because
    GitHub is where this file is read. Previewers that keep HTML labels enabled
    print the two characters instead; configuring htmlLabels off locally makes
    them agree. Relying on mermaid's own word wrapping instead was tried and
    rejected: it breaks wherever the width happens to run out, which differs per
    renderer and split --accept-routes across two lines."""

    def diagram(self):
        with open(os.path.join(ROOT, "README.md")) as handle:
            block = re.search(r"```mermaid\n(.*?)```", handle.read(), re.S)
        self.assertIsNotNone(block, "the architecture diagram is missing")
        return block.group(1)

    def test_no_html_line_breaks(self):
        # GitHub renders mermaid with HTML labels disabled, so <br/> is neither a
        # break nor whitespace: the words either side are joined outright, giving
        # "subnet router10.100.1.10". Local previewers handle it fine, which is
        # why it survived review.
        self.assertNotIn("<br", self.diagram())

    def test_labels_break_where_they_are_told_to(self):
        # Every place the diagram means a new line. Pinned individually because
        # a single missing break is easy to miss in a rendered picture, and an
        # init directive re-enabling htmlLabels does not help: GitHub ignores it.
        diagram = self.diagram()
        for label in (
            "your device\\n--accept-routes",
            "subnet router 10.100.1.10\\nelastic IP\\nadvertises 10.100.0.0/16",
            "app node 10.100.2.20\\nno public IP, no SSH key",
            "subnet route in\\ndefault route out",
        ):
            self.assertIn(label, diagram)

    def test_no_direction_statement_inside_the_subgraphs(self):
        # With an explicit direction, GitHub clips edges that cross a cluster
        # boundary to the boundary itself, so every arrow appears to connect to
        # the VPC box rather than to the host inside it.
        self.assertNotRegex(self.diagram(), r"\n\s*direction\s")


class ProviderLockTests(unittest.TestCase):
    """The lock file is committed on purpose, so that everyone resolves the same
    provider builds. It records one h1 hash per platform it was generated for,
    and a plain terraform init only ever adds the platform it happens to run on.

    A lock covering only Linux still works on a Mac, but terraform init silently
    rewrites this tracked file to add the missing hash, so the first thing a new
    reader sees is a dirty working tree they did not cause. Refresh it with
    terraform providers lock -platform=... rather than with init."""

    PLATFORMS = 4  # darwin_arm64, darwin_amd64, linux_amd64, linux_arm64

    def test_every_provider_is_locked_for_every_supported_platform(self):
        with open(os.path.join(ROOT, ".terraform.lock.hcl")) as handle:
            lock = handle.read()
        providers = re.findall(r'provider "([^"]+)" \{(.*?)\n\}', lock, re.S)
        self.assertTrue(providers, "the lock file records no providers")
        for name, body in providers:
            self.assertGreaterEqual(
                body.count("h1:"),
                self.PLATFORMS,
                f"{name} is locked for fewer than {self.PLATFORMS} platforms, so "
                "init will rewrite the lock file for anyone on the others",
            )


class ReadmeBadgeTests(unittest.TestCase):
    """The version badge states a constraint that also lives in versions.tf. A
    badge drifts more quietly than most duplication, because nobody renders the
    README while editing Terraform and the stale value still looks authoritative
    to everyone arriving at the repository."""

    def test_ci_badge_points_at_a_workflow_that_exists(self):
        # The badge names the workflow file in its URL. Renaming the file leaves
        # a badge that 404s to an image GitHub renders as nothing in particular,
        # which is easy to miss because the page still looks fine.
        with open(os.path.join(ROOT, "README.md")) as handle:
            readme = handle.read()
        badge = re.search(r"actions/workflows/([^/\s]+\.ya?ml)/badge\.svg", readme)
        self.assertIsNotNone(badge, "the CI badge is missing from README.md")
        workflow = os.path.join(ROOT, ".github", "workflows", badge.group(1))
        self.assertTrue(
            os.path.isfile(workflow),
            f"the badge points at {badge.group(1)}, which does not exist",
        )

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
