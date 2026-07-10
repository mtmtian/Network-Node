#!/usr/bin/env python3
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
GENERATOR = PROJECT_ROOT / "core" / "gen-clash.py"


class GenerateClashConfigTest(unittest.TestCase):
    def test_generates_one_config_per_device_from_shared_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "deploy.conf").write_text(
                "\n".join(
                    [
                        "REALITY_PORT=443",
                        "REALITY_TARGET=1.1.1.1:443",
                        "REALITY_SNI=",
                        "DEVICES=mac phone",
                        "CDN_ENABLE=false",
                    ]
                )
                + "\n"
            )
            (root / ".secrets.env").write_text(
                "\n".join(
                    [
                        "STATIC_IP=203.0.113.10",
                        "REALITY_PUBLIC=test-public-key",
                        "REALITY_SHORTID=0123456789abcdef",
                        "HY2_PORT=31000",
                        "ANYTLS_PORT=21000",
                        "ANYTLS_PASS=test-anytls-pass",
                        "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001",
                        "HY2_PASS_mac=test-hy2-mac",
                        "REALITY_UUID_phone=00000000-0000-4000-8000-000000000002",
                        "HY2_PASS_phone=test-hy2-phone",
                    ]
                )
                + "\n"
            )

            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "test"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = sorted((root / "clash-configs").glob("*.yaml"))
            self.assertEqual([path.name for path in outputs], ["test-mac.yaml", "test-phone.yaml"])

            mac_path = root / "clash-configs" / "test-mac.yaml"
            mac = mac_path.read_text()
            self.assertEqual(mac_path.stat().st_mode & 0o777, 0o600)
            self.assertIn("server: 203.0.113.10", mac)
            self.assertIn('name: "US-Reality"', mac)
            self.assertIn('name: "US-HY2"', mac)
            self.assertIn('name: "US-AnyTLS"', mac)
            self.assertIn("test-hy2-mac", mac)
            self.assertNotIn("test-hy2-phone", mac)


if __name__ == "__main__":
    unittest.main()
