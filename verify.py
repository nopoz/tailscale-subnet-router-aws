#!/usr/bin/env python3
"""Assert that the tailnet converged after terraform apply.

Terraform succeeding proves the AWS resources exist. It does not prove the
subnet router registered, got its tag, or had its route approved. That happens
out of band, after the instance boots. This closes that gap.

Usage:
    export TS_API_TOKEN='tskey-api-...'
    ./verify.py 10.100.0.0/16
"""

import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.tailscale.com/api/v2"
ROUTER_TAG = "tag:aws-subnet-router"
APP_TAG = "tag:aws-app"
POLL_SECONDS = 10
DEADLINE_SECONDS = 300

# The two things being waited on, and what it means when each one passes.
ROUTER = "subnet router"
APP = "app node"
PASSED = {
    ROUTER: "advertising and routing {cidr}",
    APP: "registered with Tailscale SSH enabled",
}


class FatalAPIError(Exception):
    """An API failure that waiting cannot fix, such as a rejected token."""


def fetch_devices(token):
    """Return the tailnet's devices. '-' resolves to the token's own tailnet."""
    request = urllib.request.Request(
        f"{API}/tailnet/-/devices?fields=all",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)["devices"]
    except urllib.error.HTTPError as error:
        # A token that is missing or unscoped answers 403 on every attempt.
        # HTTPError is a URLError, so without this it lands in the retry path
        # and burns the whole deadline before the reason reaches anyone. 429 is
        # the one 4xx that waiting does fix, so it stays retryable.
        if 400 <= error.code < 500 and error.code != 429:
            raise FatalAPIError(f"HTTP {error.code} {error.reason}") from error
        raise


def check(devices, cidr, router_tag, app_tag):
    """Return a list of (subject, failure) pairs. Empty means everything passed.

    The subject is which of the two nodes the failure is about, so a caller
    watching this converge can report each one clearing as it happens.

    Only devices currently connected to the control plane are considered. An
    ephemeral device is not removed the moment its instance terminates, so for a
    few minutes after a destroy the tailnet still lists the dead node, complete
    with the routes it used to advertise. Counting those is wrong in both
    directions: on its own a ghost reports success against infrastructure that no
    longer exists, and alongside its replacement it reports "found 2" for a
    tailnet that is perfectly healthy.
    """
    failures = []

    devices = [d for d in devices if d.get("connectedToControl")]

    routers = [d for d in devices if router_tag in (d.get("tags") or [])]
    if len(routers) != 1:
        failures.append(
            (ROUTER, f"expected exactly 1 device tagged {router_tag}, found {len(routers)}")
        )
    else:
        node = routers[0]
        name = node.get("hostname", "unknown")
        if not node.get("authorized"):
            failures.append((ROUTER, f"{name} is not authorized"))

        advertised = set(node.get("advertisedRoutes") or [])
        enabled = set(node.get("enabledRoutes") or [])

        if cidr not in advertised:
            failures.append(
                (
                    ROUTER,
                    f"{name} does not advertise {cidr} "
                    f"(advertises {sorted(advertised) or 'nothing'})",
                )
            )
        elif cidr not in enabled:
            failures.append(
                (
                    ROUTER,
                    f"{cidr} is advertised by {name} but not approved; "
                    "autoApprovers did not fire",
                )
            )

        # Anything else the router offers that the policy has not approved. The
        # expected CIDR is excluded because the branch above already reported it,
        # in the terms that point at autoApprovers.
        unapproved = advertised - enabled - {cidr}
        if unapproved:
            failures.append(
                (ROUTER, f"{name} advertises {sorted(unapproved)}, which is not approved")
            )

    apps = [d for d in devices if app_tag in (d.get("tags") or [])]
    if len(apps) != 1:
        failures.append(
            (APP, f"expected exactly 1 device tagged {app_tag}, found {len(apps)}")
        )
    else:
        node = apps[0]
        name = node.get("hostname", "unknown")
        # Checked on both nodes for the same reason: preauthorized keys make an
        # unauthorized device unlikely rather than impossible, and a tailnet with
        # device approval switched on fails here rather than at SSH time.
        if not node.get("authorized"):
            failures.append((APP, f"{name} is not authorized"))
        if not node.get("sshEnabled"):
            failures.append((APP, f"{name} does not have Tailscale SSH enabled"))

    return failures


def main():
    if len(sys.argv) != 2:
        print("usage: verify.py <expected-cidr>", file=sys.stderr)
        return 2

    cidr = sys.argv[1]

    # The documented invocation is ./verify.py "$(terraform output -raw
    # advertised_route)". Against an empty state that substitution yields an empty
    # string rather than an error, and the quotes keep it as one argument, so the
    # argument-count check above lets it through. Without this guard the script
    # then polls for the full deadline before failing for the wrong reason.
    try:
        ipaddress.ip_network(cidr, strict=False)
    except ValueError as error:
        print(f"not a CIDR: {cidr!r} ({error})", file=sys.stderr)
        print(
            "if you used terraform output, check that state exists in this directory",
            file=sys.stderr,
        )
        return 2

    token = os.environ.get("TS_API_TOKEN")
    if not token:
        print("TS_API_TOKEN is not set", file=sys.stderr)
        return 2

    started = time.time()
    deadline = started + DEADLINE_SECONDS
    failures = [(ROUTER, "no attempt completed")]
    pending = {ROUTER, APP}
    reported = {}

    def log(subject, message):
        print(f"  [{int(time.time() - started):>3}s] {subject}: {message}", file=sys.stderr)

    print(
        f"waiting up to {DEADLINE_SECONDS // 60} minutes for {len(pending)} checks "
        f"against {cidr}",
        file=sys.stderr,
    )

    while time.time() < deadline:
        try:
            devices = fetch_devices(token)
        except FatalAPIError as error:
            print(f"FAIL: Tailscale API: {error}", file=sys.stderr)
            print("check TS_API_TOKEN and its scopes", file=sys.stderr)
            return 2
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
            # A 5xx, a rate limit, a dropped connection, a body that is not the
            # JSON the API promised. TimeoutError and ValueError are named
            # because neither arrives wrapped: urlopen's timeout fires on the
            # socket read rather than through URLError, and a non-JSON body
            # reaches json.load as a ValueError. Omitting them ends the run in a
            # traceback. Reporting flows through the same path as any other
            # failure below, so a persistent outage is printed once, not once a
            # poll.
            failures = [(s, f"API request failed: {error}") for s in sorted(pending)]
        else:
            failures = check(devices, cidr, ROUTER_TAG, APP_TAG)

        failing = {subject for subject, _ in failures}

        # Announce each check the moment it starts passing, so progress is visible
        # as a line of its own rather than only as an absence from the list below.
        for subject in sorted(pending - failing):
            log(subject, "OK, " + PASSED[subject].format(cidr=cidr))
        pending = failing

        if not failures:
            print(f"converged in {int(time.time() - started)}s")
            return 0

        # Reprint a subject's reasons only when that subject's reasons change.
        # Tracking the whole list instead would reprint an unchanged reason every
        # time some other check cleared.
        outstanding = {}
        for subject, failure in failures:
            outstanding.setdefault(subject, []).append(failure)
        for subject in sorted(outstanding):
            if outstanding[subject] != reported.get(subject):
                for failure in outstanding[subject]:
                    log(subject, failure)
        reported = outstanding

        time.sleep(POLL_SECONDS)

    for subject, failure in failures:
        print(f"FAIL: {subject}: {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
