import http.server
import os
import subprocess
import sys
import threading
import unittest
import urllib.error

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import verify
from verify import check

CIDR = "10.100.0.0/16"
ROUTER_TAG = "tag:aws-subnet-router"
APP_TAG = "tag:aws-app"


def router(**overrides):
    device = {
        "hostname": "tailscale-aws-subnet-router",
        "tags": [ROUTER_TAG],
        "authorized": True,
        "connectedToControl": True,
        "advertisedRoutes": [CIDR],
        "enabledRoutes": [CIDR],
        "sshEnabled": True,
    }
    device.update(overrides)
    return device


def app(**overrides):
    device = {
        "hostname": "tailscale-aws-app",
        "tags": [APP_TAG],
        "authorized": True,
        "connectedToControl": True,
        "sshEnabled": True,
    }
    device.update(overrides)
    return device


class CheckTests(unittest.TestCase):
    def test_healthy_tailnet_has_no_failures(self):
        self.assertEqual(check([router(), app()], CIDR, ROUTER_TAG, APP_TAG), [])

    def test_missing_router_is_reported(self):
        failures = check([app()], CIDR, ROUTER_TAG, APP_TAG)
        self.assertTrue(any("found 0" in m for _, m in failures))

    def test_advertised_but_not_approved_is_reported(self):
        failures = check(
            [router(enabledRoutes=[]), app()], CIDR, ROUTER_TAG, APP_TAG
        )
        self.assertTrue(any("autoApprovers did not fire" in m for _, m in failures))

    def test_route_never_advertised_is_reported(self):
        failures = check(
            [router(advertisedRoutes=[], enabledRoutes=[]), app()],
            CIDR,
            ROUTER_TAG,
            APP_TAG,
        )
        self.assertTrue(any("does not advertise" in m for _, m in failures))

    def test_unauthorized_router_is_reported(self):
        failures = check([router(authorized=False), app()], CIDR, ROUTER_TAG, APP_TAG)
        self.assertTrue(any("not authorized" in m for _, m in failures))

    def test_unauthorized_app_is_reported(self):
        failures = check([router(), app(authorized=False)], CIDR, ROUTER_TAG, APP_TAG)
        self.assertTrue(any(s == "app node" and "not authorized" in m for s, m in failures))

    def test_unapproved_route_is_reported_once(self):
        # The expected CIDR going unapproved is one fault, and should read as one
        # line naming autoApprovers, not as two saying the same thing twice.
        failures = check([router(enabledRoutes=[]), app()], CIDR, ROUTER_TAG, APP_TAG)
        self.assertEqual(len([m for s, m in failures if s == "subnet router"]), 1)

    def test_an_extra_unapproved_route_is_still_reported(self):
        # The expected route approved, something else advertised alongside it and
        # not. Narrowing the check above must not lose this.
        failures = check(
            [router(advertisedRoutes=[CIDR, "192.168.9.0/24"]), app()],
            CIDR,
            ROUTER_TAG,
            APP_TAG,
        )
        self.assertTrue(any("192.168.9.0/24" in m for _, m in failures))

    def test_app_without_ssh_is_reported(self):
        failures = check([router(), app(sshEnabled=False)], CIDR, ROUTER_TAG, APP_TAG)
        self.assertTrue(any("Tailscale SSH" in m for _, m in failures))

    def test_stale_device_from_a_previous_apply_is_ignored(self):
        # Ephemeral devices are not reaped the instant their instance dies, so
        # right after a destroy-and-apply the tailnet briefly holds both the dead
        # node and its replacement. Counting both reports "found 2" and fails a
        # tailnet that is actually healthy.
        stale = router(connectedToControl=False, enabledRoutes=[])
        self.assertEqual(check([stale, router(), app()], CIDR, ROUTER_TAG, APP_TAG), [])

    def test_a_stale_router_alone_counts_as_missing(self):
        # The dangerous direction. Before the replacement registers, the only
        # tagged device present is the dead one, and its recorded routes still
        # look correct. Counting it reports success against infrastructure that
        # no longer exists.
        failures = check(
            [router(connectedToControl=False), app()], CIDR, ROUTER_TAG, APP_TAG
        )
        self.assertTrue(any("found 0" in m for _, m in failures))

    def test_ignores_unrelated_devices(self):
        other = {"hostname": "some-other-device", "tags": [], "authorized": True}
        self.assertEqual(
            check([router(), app(), other], CIDR, ROUTER_TAG, APP_TAG), []
        )


class ArgumentTests(unittest.TestCase):
    """The CIDR argument is usually supplied by command substitution, which can
    silently produce an empty string. These run the script rather than importing
    it, because the guard being tested lives in main() and must reject bad input
    before any network call happens."""

    def run_verify(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "verify.py"), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_empty_cidr_is_rejected_immediately(self):
        result = self.run_verify("")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a CIDR", result.stderr)

    def test_garbage_cidr_is_rejected(self):
        result = self.run_verify("not-a-network")
        self.assertEqual(result.returncode, 2)

    def test_missing_argument_is_rejected(self):
        result = self.run_verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)


class APIFailureTests(unittest.TestCase):
    """Which API failures are worth waiting out and which are not. Getting this
    wrong is expensive in the same way either direction: retrying a rejected
    token spends the whole deadline before the reason appears, and treating a
    rate limit as fatal abandons a run that would have succeeded."""

    def fetch(self, status, body, content_type="application/json"):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(inner):
                payload = body.encode()
                inner.send_response(status)
                inner.send_header("Content-Type", content_type)
                inner.send_header("Content-Length", str(len(payload)))
                inner.end_headers()
                inner.wfile.write(payload)

            def log_message(inner, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        original = verify.API
        verify.API = f"http://127.0.0.1:{server.server_address[1]}/api/v2"
        self.addCleanup(setattr, verify, "API", original)
        return verify.fetch_devices("stub-token")

    def test_rejected_token_is_fatal(self):
        with self.assertRaises(verify.FatalAPIError) as caught:
            self.fetch(403, '{"message":"insufficient permissions"}')
        self.assertIn("403", str(caught.exception))

    def test_rate_limit_is_retryable(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch(429, '{"message":"rate limit exceeded"}')

    def test_server_error_is_retryable(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch(500, '{"message":"internal error"}')

    def test_body_that_is_not_json_raises_what_the_loop_catches(self):
        # A proxy or a gateway can answer 200 with HTML. json.load reports that
        # as a ValueError, which is why main() names ValueError as retryable
        # rather than letting it end the run in a traceback.
        with self.assertRaises(ValueError):
            self.fetch(200, "<html>502 Bad Gateway</html>", "text/html")


if __name__ == "__main__":
    unittest.main()
