#!/usr/bin/env python3
import pathlib
import subprocess
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


class DeployOutputTest(unittest.TestCase):
    def test_reality_client_password_is_redacted_from_logs(self):
        command = (
            f'. "{PROJECT_ROOT / "core" / "common.sh"}"; '
            f'. "{PROJECT_ROOT / "core" / "deploy.sh"}"; '
            "printf 'before\\nREALITY_PUBLIC_KEY=client-secret\\nafter\\n' | redact_server_output"
        )
        result = subprocess.run(
            ["bash", "-c", command],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "before\nREALITY_PUBLIC_KEY=[redacted]\nafter\n",
        )
        self.assertNotIn("client-secret", result.stdout)


if __name__ == "__main__":
    unittest.main()
