"""Acceptance of process-scoped private destination blocking in generated YAML."""
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

import test_aggregate as fixtures


# Independent acceptance values: do not import the production list.
EXPECTED = [
    f'AND,((PROCESS-NAME,lightpanda),({kind},{cidr})),REJECT'
    for kind, cidr in (
        ('IP-CIDR', '0.0.0.0/8'), ('IP-CIDR', '127.0.0.0/8'),
        ('IP-CIDR', '10.0.0.0/8'), ('IP-CIDR', '172.16.0.0/12'),
        ('IP-CIDR', '192.168.0.0/16'), ('IP-CIDR', '169.254.0.0/16'),
        ('IP-CIDR', '100.64.0.0/10'), ('IP-CIDR6', '::1/128'),
        ('IP-CIDR6', 'fc00::/7'), ('IP-CIDR6', 'fe80::/10'),
    )
]
ROOT = Path(__file__).resolve().parents[1]


def render_single(fixture, strict):
    state = fixture.root / 'profiles/primary'
    conf = state / 'deploy.conf'
    conf.write_text(re.sub(r'(?m)^AI_STRICT_MODE=.*$',
                          f'AI_STRICT_MODE={str(strict).lower()}', conf.read_text()))
    env = os.environ | {
        'NETWORK_NODE_ROOT': str(fixture.root),
        'NETWORK_NODE_STATE_DIR': str(state),
        'NETWORK_NODE_PROFILE': 'primary',
        'NETWORK_NODE_CLIENTS_DIR': str(fixture.root / 'clash-configs'),
    }
    result = subprocess.run([sys.executable, str(ROOT / 'core/gen-clash.py')],
                            env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return {target: (fixture.root / f'clash-configs/{target}/primary.yaml').read_text()
            for target in ('stash', 'mihomo')}


@unittest.skipUnless(fixtures.yaml, 'PyYAML required')
class LightpandaPolicyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AggregateTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def assert_policy(self, text, target):
        config = fixtures.yaml.safe_load(text)
        rules = config['rules']
        if target == 'stash':
            self.assertFalse(any('lightpanda' in rule for rule in rules))
        else:
            self.assertEqual(rules[:len(EXPECTED)], EXPECTED)
            self.assertEqual(sum('lightpanda' in rule for rule in rules), len(EXPECTED))
            self.assertEqual(config['find-process-mode'], 'strict')
            self.assertGreater(rules.index('IP-CIDR,127.0.0.0/8,DIRECT,no-resolve'),
                               len(EXPECTED) - 1)

    def test_single_server_daily_and_strict_keep_guard_before_direct(self):
        # Given both routing modes, the same guard must survive strict rewriting.
        for strict in (False, True):
            for target, text in render_single(self.fixture, strict).items():
                with self.subTest(strict=strict, target=target):
                    self.assert_policy(text, target)

    def test_aggregate_and_standalone_only_protect_mihomo(self):
        # Given both clients and standalone children, all Mihomo files are protected.
        self.fixture.shared_plan()
        self.fixture.plan['standalone'] = True
        self.fixture.save_plan()
        self.assertEqual(self.fixture.generate(), 0)
        for target in ('stash', 'mihomo'):
            paths = sorted((self.fixture.root / 'clash-configs' / target).glob('*.yaml'))
            self.assertEqual(len(paths), 4)
            for path in paths:
                with self.subTest(target=target, file=path.name):
                    self.assert_policy(path.read_text(), target)


if __name__ == '__main__':
    unittest.main()
