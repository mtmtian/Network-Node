#!/usr/bin/env python3
import pathlib
import subprocess
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


class ProviderScriptTest(unittest.TestCase):
    def test_optional_warp_reality_port_is_opened_by_both_providers(self):
        gcp = (PROJECT_ROOT / "providers" / "gcp-provision.sh").read_text()
        vps = (PROJECT_ROOT / "providers" / "vps.sh").read_text()
        self.assertIn('FW_RULES="${FW_RULES},tcp:${WARP_REALITY_PORT}"', gcp)
        self.assertIn('printf \'%s/tcp\\n\' "$WARP_REALITY_PORT" >> "$expected"', vps)

    def test_xray_direct_outbounds_prefer_ipv4(self):
        setup = (PROJECT_ROOT / "core" / "setup-server.sh").read_text()
        self.assertIn(
            "XRAY_OUTBOUNDS='{\"protocol\":\"freedom\",\"settings\":{\"domainStrategy\":\"UseIPv4\"}}'",
            setup,
        )
        self.assertNotIn('"domainStrategy": "UseIPv6v4"', setup)

    def test_server_setup_uses_isolated_installer_directory(self):
        setup = (PROJECT_ROOT / "core" / "setup-server.sh").read_text()
        self.assertIn('INSTALL_TMP="$(mktemp -d)"', setup)
        self.assertNotIn('download_file /tmp/', setup)
        self.assertIn('flock -n 9', setup)

    def test_gcloud_retry_propagates_final_failure(self):
        script = (PROJECT_ROOT / "providers" / "gcp-provision.sh").read_text()
        retry_function = script[script.index('gcloud_retry() {'):script.index('\n}', script.index('gcloud_retry() {')) + 2]
        command = f"""
        set -euo pipefail
        PROJECT_DIR={str(PROJECT_ROOT)!r}
        . "$PROJECT_DIR/core/common.sh"
        {retry_function}
        GC=(false)
        sleep() {{ :; }}
        set +e
        gcloud_retry
        status=$?
        set -e
        test "$status" -eq 1
        """
        result = subprocess.run(
            ["bash", "-c", command],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
