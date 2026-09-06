import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GcpAccountTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'profile'
        self.state.mkdir()
        self.conf = self.state / 'deploy.conf'
        self.conf.write_text('GCP_ACCOUNT=saved@example.com\nPROJECT_ID=test-project\nREGION=us-west1\n')
        self.log = self.root / 'calls.jsonl'
        executable = self.root / 'gcloud'
        executable.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['GCLOUD_TEST_LOG'], 'a') as handle:
    handle.write(json.dumps(sys.argv[1:]) + '\\n')
if 'get-value' in sys.argv:
    print('global@example.com')
elif 'print-access-token' in sys.argv:
    print('test-token-must-not-appear')
    sys.exit(int(os.environ.get('GCLOUD_AUTH_FAIL', '0')))
elif 'mktemp' in ' '.join(sys.argv):
    print('/tmp/network-node.test1234')
''')
        executable.chmod(0o755)
        self.env = os.environ | {
            'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
            'NETWORK_NODE_STATE_DIR': str(self.state),
            'GCLOUD_TEST_LOG': str(self.log),
            'PROJECT_DIR': str(ROOT),
        }
        self.env.pop('GCP_ACCOUNT', None)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_local_management_proxy_is_loaded_by_entrypoint(self):
        with self.conf.open('a') as handle:
            handle.write('GCP_HTTP_PROXY=http://127.0.0.1:7890\n')
        command = '''
        . "$PROJECT_DIR/core/common.sh"
        . "$PROJECT_DIR/providers/gcp.sh"
        provider_init
        test "$HTTPS_PROXY" = http://127.0.0.1:7890
        test "$HTTP_PROXY" = http://127.0.0.1:7890
        '''
        subprocess.run(['bash', '-euc', command], env=self.env, capture_output=True, check=True)

    def test_preflight_checks_saved_account_without_showing_token(self):
        for failed in (False, True):
            with self.subTest(expired=failed):
                result = subprocess.run(['bash', str(ROOT / 'providers/gcp-preflight.sh')],
                    env=self.env | {'GCLOUD_AUTH_FAIL': str(int(failed))}, capture_output=True, text=True)
                self.assertEqual(result.returncode, int(failed))
                self.assertNotIn('test-token-must-not-appear', result.stdout + result.stderr)
                self.assertEqual(self.calls()[-1], ['--account', 'saved@example.com', 'auth', 'print-access-token'])

    def test_configure_pins_legacy_account_and_preserves_saved_account(self):
        self.conf.write_text('PROJECT_ID=test-project\nREGION=us-west1\nGCP_ACCOUNT=\n')
        command = '. "$PROJECT_DIR/core/common.sh"; . "$PROJECT_DIR/providers/gcp.sh"; provider_configure'
        subprocess.run(['bash', '-euc', command], env=self.env, capture_output=True, check=True)
        self.assertIn('GCP_ACCOUNT=global@example.com', self.conf.read_text())
        self.conf.write_text(self.conf.read_text().replace('global@example.com', 'saved@example.com'))
        self.log.write_text('')
        subprocess.run(['bash', '-euc', command], env=self.env, capture_output=True, check=True)
        self.assertEqual(self.calls(), [])
        self.assertIn('GCP_ACCOUNT=saved@example.com', self.conf.read_text())
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o600)

    def test_install_uses_saved_account_and_profile_ssh_key_for_every_call(self):
        command = '''
        . "$PROJECT_DIR/core/common.sh"
        . "$PROJECT_DIR/providers/gcp.sh"
        load_conf
        ZONE=us-west1-a INSTANCE_NAME=test-node
        provider_install setup-server.sh download.sh server-env.sh
        '''
        subprocess.run(['bash', '-euc', command], env=self.env, capture_output=True, check=True)
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        for args in calls:
            self.assertEqual(args[:2], ['--account', 'saved@example.com'])
            self.assertEqual(args[args.index('--ssh-key-file') + 1], str(self.state / 'ssh/google_compute_engine'))
        self.assertEqual((self.state / 'ssh').stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()
