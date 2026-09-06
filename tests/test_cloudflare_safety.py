"""Cloudflare ownership and retry tests; every HTTP request is intercepted locally."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
from settings import load_kv


class CloudflareSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "deploy.conf").write_text(
            "CDN_ENABLE=true\nCDN_HOSTNAME=cdn.example.com\nCDN_TUNNEL_NAME=test-cdn\n")
        (self.root / ".secrets.env").write_text("CF_API_TOKEN=test-api-secret\n")
        curl = self.bin / "curl"
        curl.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith("https://api.cloudflare.com/"))
method = args[args.index("-X")+1]
mode = os.environ["CF_TEST_MODE"]
with open("requests.log", "a") as log: log.write(method + " " + url + "\\n")
response = {"success": True, "result": {}}
if "/zones?" in url:
    response["result"] = [{"id": "zone-one", "name": "example.com", "account": {"id": "account-one"}}]
elif "cfd_tunnel?" in url:
    response["result"] = [] if mode == "new-fails" else [{"id": "tunnel-one"}]
elif method == "POST" and url.endswith("cfd_tunnel"):
    response["result"] = {"id": "tunnel-one"}
elif url.endswith("configurations") and mode == "new-fails":
    response = {"success": False, "errors": [{"code": 1000, "message": "test-api-secret"}]}
elif "dns_records?" in url:
    response["result"] = [{"id": "record-one", "content": "other.cfargotunnel.com"}] if mode == "dns-conflict" else []
elif url.endswith("/token"):
    response["result"] = "test-connector-secret"
print(json.dumps(response)); print(200)
''')
        curl.chmod(0o755)
        (self.bin / "sleep").write_text("#!/bin/sh\nexit 0\n")
        (self.bin / "sleep").chmod(0o755)

    def run_cf(self, mode):
        env = os.environ | {"NETWORK_NODE_STATE_DIR": str(self.root), "PROFILE_NAME": "test",
                            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"], "CF_TEST_MODE": mode}
        return subprocess.run(["bash", str(ROOT / "core/cloudflare.sh")], cwd=self.root,
                              env=env, capture_output=True, text=True)

    def claim_tunnel(self):
        with (self.root / ".secrets.env").open("a") as handle:
            handle.write("CDN_TUNNEL_ID=tunnel-one\n")

    def test_new_tunnel_ownership_survives_partial_failure_and_retry(self):
        result = self.run_cf("new-fails")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("test-api-secret", result.stdout + result.stderr)
        self.assertEqual(load_kv(self.root / ".secrets.env")["CDN_TUNNEL_ID"], "tunnel-one")
        result = self.run_cf("retry")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("test-connector-secret", result.stdout + result.stderr)
        self.assertEqual(load_kv(self.root / ".secrets.env")["CF_TUNNEL_TOKEN"], "test-connector-secret")

    def test_unowned_tunnel_cannot_be_overwritten(self):
        result = self.run_cf("existing")
        self.assertNotEqual(result.returncode, 0)
        requests = (self.root / "requests.log").read_text()
        self.assertNotIn("PUT ", requests)
        self.assertNotIn("POST ", requests)

    def test_conflicting_dns_is_not_overwritten(self):
        self.claim_tunnel()
        result = self.run_cf("dns-conflict")
        self.assertNotEqual(result.returncode, 0)
        requests = (self.root / "requests.log").read_text().splitlines()
        self.assertFalse(any(line.startswith("PUT ") and "dns_records/" in line for line in requests))


if __name__ == "__main__":
    unittest.main()
