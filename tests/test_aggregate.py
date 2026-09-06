"""Routing boundaries and source lifecycle for multi-profile client output."""
import copy
import json
import os
import ipaddress
import re
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import client_aggregate as aggregate

try:
    import yaml
except ImportError:
    yaml = None


class AggregateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = {
            'sources': [{'profile': 'primary', 'name': 'cstone'},
                        {'profile': 'backup', 'name': 'gcloud'},
                        {'profile': 'fast', 'name': 'lax'}],
            'sensitive': ['cstone/Reality', 'gcloud/CDN'],
            'devices': ['mac', 'iphone'], 'client': 'stash',
        }
        for name in ('primary', 'backup', 'fast'):
            path = self.root / 'profiles' / name
            path.mkdir(parents=True)
            (path / 'deploy.conf').write_text(
                'DEVICES=mac iphone\nREALITY_PORT=443\nAI_STRICT_MODE=true\n'
                'CDN_ENABLE=' + ('true' if name == 'backup' else 'false') + '\n'
                'CDN_HOSTNAME=cdn.example.com\nCDN_WS_PATH=ws-test\n')
            (path / '.secrets.env').write_text(
                'STATIC_IP=203.0.113.10\nREALITY_PUBLIC=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n'
                'REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\nANYTLS_PORT=21000\n'
                'ANYTLS_PASS=test-anytls-' + name + '\n'
                'REALITY_UUID_mac=00000000-0000-4000-8000-000000000001\nHY2_PASS_mac=mac-only\n'
                'REALITY_UUID_iphone=00000000-0000-4000-8000-000000000002\nHY2_PASS_iphone=phone-only\n'
                'CDN_UUID_mac=00000000-0000-4000-8000-000000000003\n'
                'CDN_UUID_iphone=00000000-0000-4000-8000-000000000004\n')
        state = self.root / 'profiles' / 'routing'
        state.mkdir()
        self.plan_path = state / 'aggregate.json'
        self.save_plan()

    def save_plan(self):
        self.plan_path.write_text(json.dumps(self.plan))

    def generate(self, **kwargs):
        return aggregate.generate(self.root, 'routing', **kwargs)

    def output(self, device='mac'):
        return self.root / 'clash-configs' / f'routing-{device}.yaml'

    @unittest.skipUnless(yaml, 'PyYAML required')
    def test_ai_core_domains_have_matching_sensitive_dns(self):
        self.generate()
        data = yaml.safe_load(self.output().read_text())
        rules = [r.split(',') for r in data['rules']]
        def sensitive(host):
            for fields in rules:
                if len(fields) < 3 or fields[2] != aggregate.AI:
                    continue
                kind, value = fields[:2]
                if ((kind == 'DOMAIN' and host == value) or
                    (kind == 'DOMAIN-SUFFIX' and (host == value or host.endswith('.' + value)))):
                    return True
            return False
        # Product acceptance examples, independent of the generated data file.
        required = ('api.openai.com', 'ws.chatgpt.com', 'api.anthropic.com',
                    'rum.browser-intake-datadoghq.com', 'o207216.ingest.sentry.io',
                    'antigravity.google', 'antigravity-pa.googleapis.com',
                    'daily-cloudcode-pa.googleapis.com', 'aicode.googleapis.com',
                    'businessaicode.googleapis.com', 'generativelanguage.googleapis.com',
                    'accounts.google.com', 'oauth2.googleapis.com', 'www.googleapis.com',
                    'antigravity-unleash.goog', 'us-central1-aiplatform.googleapis.com',
                    'global-aiplatform.googleapis.com', 'api.dev.runwayml.com',
                    'api.replicate.com', 'fal.run', 'v0.app', 'api.githubcopilot.com')
        dns = data['dns']['nameserver-policy']
        for host in required:
            with self.subTest(host=host):
                self.assertTrue(sensitive(host))
                candidates = [(key, value) for key, value in dns.items() if key == host or
                              (key.startswith('+.') and (host == key[2:] or host.endswith(key[1:])))]
                self.assertTrue(candidates, 'missing sensitive DNS policy')
                for key, value in candidates:
                    self.assertEqual(value, ['https://1.1.1.1/dns-query', 'https://1.0.0.1/dns-query'])
        for host in ('storage.googleapis.com', 'maps.googleapis.com', 'www.gstatic.com',
                     'unrelated.sentry.io', 'datadog-unrelated.example', 'sift-example.com',
                     'api.deepseek.com', 'doubao.com', 'api.spotify.com'):
            self.assertFalse(sensitive(host), host)
        for keyword in ('datadog', 'sentry', 'sift'):
            self.assertFalse(any(r[:2] == ['DOMAIN-KEYWORD', keyword] for r in rules))

    @unittest.skipUnless(yaml, 'PyYAML required')
    def test_antigravity_bundle_routes_are_mac_only_and_client_specific(self):
        paths = ('/Applications/Antigravity.app/Contents/MacOS/Antigravity',
                 '/Applications/Antigravity.app/Contents/Resources/bin/language_server',
                 '/Applications/Antigravity IDE.app/Contents/Frameworks/Helper.app/Contents/MacOS/Helper')
        for target in ('stash', 'mihomo'):
            self.generate(target=target)
            data = yaml.safe_load(self.output().read_text())
            rules = data['rules']
            processes = [r for r in rules if r.startswith('PROCESS-')]
            self.assertTrue(processes)
            def matches(path):
                return any(path.startswith(r.split(',')[1]) if target == 'stash' else
                           re.fullmatch(r.split(',')[1], path) for r in processes)
            for path in paths:
                self.assertTrue(matches(path), path)
            for path in ('/usr/bin/curl', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                         '/Applications/Antigravity.app.backup/Contents/MacOS/Antigravity'):
                self.assertFalse(matches(path), path)
            for rule in processes:
                self.assertEqual(rule.split(',')[2], aggregate.AI)
                self.assertLess(rules.index('IP-CIDR,192.168.0.0/16,DIRECT,no-resolve'), rules.index(rule))
                self.assertLess(rules.index(rule), rules.index(f'RULE-SET,ads-lite,{aggregate.ADS}'))
                self.assertLess(rules.index(rule), rules.index(f'RULE-SET,cn,{aggregate.CN}'))
            iphone = yaml.safe_load(self.output('iphone').read_text())
            self.assertFalse(any(r.startswith('PROCESS-') for r in iphone['rules']))
            if target == 'stash':
                for address in data['dns']['default-nameserver']:
                    ipaddress.ip_address(address)
                self.assertFalse(any(r.startswith('PROCESS-PATH-REGEX,') for r in processes))

    def test_sources_are_fresh_devices_isolated_and_outputs_owned(self):
        self.assertEqual(self.generate(), 0)
        text = self.output().read_text()
        self.assertIn('mac-only', text)
        self.assertNotIn('phone-only', text)
        self.assertIn('gcloud/CDN', text)
        self.assertNotIn('phone-only', text)
        self.assertIn('phone-only', self.output('iphone').read_text())
        self.assertEqual(self.output().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output().parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.generate(check=True), 0)
        # Distribution copies have no authority over a subsequent render.
        unrelated = self.output().parent / 'primary-mac.yaml'
        unrelated.write_text('manual distribution copy')
        secret = self.root / 'profiles/fast/.secrets.env'
        secret.write_text(secret.read_text().replace('203.0.113.10', '203.0.113.11'))
        self.assertEqual(self.generate(check=True), 1)
        self.generate()
        self.assertIn('203.0.113.11', self.output().read_text())
        self.assertEqual(unrelated.read_text(), 'manual distribution copy')

    def test_missing_sensitive_cdn_fails_without_replacing_existing_files(self):
        self.generate()
        original = self.output().read_bytes()
        path = self.root / 'profiles/backup/deploy.conf'
        path.write_text(path.read_text().replace('CDN_ENABLE=true', 'CDN_ENABLE=false'))
        with self.assertRaisesRegex(ValueError, '缺少指定的敏感'):
            self.generate()
        self.assertEqual(self.output().read_bytes(), original)

    def test_disabled_source_is_removed_but_sensitive_source_cannot_disappear(self):
        path = self.root / 'profiles/fast/deploy.conf'
        path.write_text(path.read_text() + 'CLIENT_CONFIG_ENABLE=false\n')
        self.generate()
        self.assertNotIn('lax/', self.output().read_text())
        backup = self.root / 'profiles/backup/deploy.conf'
        backup.write_text(backup.read_text() + 'CLIENT_CONFIG_ENABLE=false\n')
        with self.assertRaisesRegex(ValueError, '缺少指定的敏感'):
            self.generate()

    def test_missing_device_on_sensitive_source_fails(self):
        path = self.root / 'profiles/backup/deploy.conf'
        path.write_text(path.read_text().replace('DEVICES=mac iphone', 'DEVICES=mac'))
        with self.assertRaisesRegex(ValueError, 'iphone 缺少指定'):
            self.generate()
        self.assertFalse(self.output().exists())

    def test_generator_timeout_is_sanitized_and_preserves_files(self):
        self.generate()
        original = self.output().read_bytes()
        failure = subprocess.TimeoutExpired(['private-command'], 60, output='private-output')
        with mock.patch.object(aggregate.subprocess, 'run', side_effect=failure):
            with self.assertRaisesRegex(ValueError, '生成超时') as error:
                self.generate()
        self.assertNotIn('private-', str(error.exception))
        self.assertEqual(self.output().read_bytes(), original)

    def test_bad_plan_and_empty_sensitive_group_rejected(self):
        bad_plans = []
        for field, value in [('sensitive', []), ('sensitive', ['gcloud/HY2']),
                             ('devices', ['../mac']), ('sources', [])]:
            plan = copy.deepcopy(self.plan)
            plan[field] = value
            bad_plans.append(plan)
        duplicate = copy.deepcopy(self.plan)
        duplicate['sources'][1]['name'] = 'cstone'
        bad_plans.append(duplicate)
        for plan in bad_plans:
            self.plan_path.write_text(json.dumps(plan))
            with self.assertRaises(ValueError):
                self.generate()

    def test_mihomo_engine_accepts_bundle(self):
        binary = os.environ.get('MIHOMO_BIN')
        if not binary or not Path(binary).is_file():
            self.skipTest('MIHOMO_BIN is not available')
        self.generate(target='mihomo')
        result = subprocess.run([binary, '-t', '-d', str(self.root), '-f', str(self.output())],
                                capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(yaml, 'PyYAML unavailable; install requirements-test.txt for independent YAML validation')
    def test_routing_graph_dns_defaults_and_client_schema(self):
        for target in ('stash', 'mihomo'):
            with self.subTest(target=target):
                self.generate(target=target)
                data = yaml.safe_load(self.output().read_text())
                proxies = {p['name']: p for p in data['proxies']}
                groups = {g['name']: g for g in data['proxy-groups']}
                self.assertEqual(len(proxies), 10)
                self.assertEqual(len(groups), 8)
                self.assertEqual(groups[aggregate.SENSITIVE]['proxies'], ['cstone/Reality', 'gcloud/CDN'])
                self.assertEqual(groups[aggregate.SENSITIVE]['type'], 'fallback')
                self.assertFalse(groups[aggregate.SENSITIVE]['lazy'])
                self.assertEqual(groups[aggregate.AUTO]['type'], 'url-test')
                self.assertEqual(groups[aggregate.AUTO]['interval'], 300)
                self.assertEqual(groups[aggregate.AI]['proxies'], [aggregate.SENSITIVE, aggregate.MANUAL])
                self.assertEqual(groups[aggregate.OVERSEAS]['proxies'], [aggregate.AUTO, aggregate.MANUAL])
                self.assertEqual(groups[aggregate.CN]['proxies'][0], 'DIRECT')
                self.assertEqual(groups[aggregate.ADS]['proxies'][0], 'REJECT')
                self.assertEqual(set(groups[aggregate.MANUAL]['proxies']), set(proxies))
                allowed = set(proxies) | set(groups) | {'DIRECT', 'REJECT'}
                def visit(name, stack):
                    self.assertNotIn(name, stack, 'strategy cycle')
                    if name in groups:
                        self.assertTrue(groups[name]['proxies'])
                        for child in groups[name]['proxies']:
                            self.assertIn(child, allowed)
                            visit(child, stack | {name})
                for name in groups:
                    visit(name, set())
                rules = data['rules']
                for rule in rules:
                    fields = rule.split(',')
                    self.assertIn(fields[1 if fields[0] == 'MATCH' else 2], allowed)
                    if fields[0] == 'RULE-SET':
                        self.assertIn(fields[1], data['rule-providers'])
                self.assertEqual(rules[-1], f'MATCH,{aggregate.OVERSEAS}')
                self.assertIn('DOMAIN-KEYWORD,spotify,DIRECT', rules)
                self.assertIn('DOMAIN-SUFFIX,scdn.co,DIRECT', rules)
                self.assertFalse(any('Spotify' in name for name in groups))
                meta_rule = f'DOMAIN-SUFFIX,facebook.com,{aggregate.AI}'
                self.assertLess(rules.index(meta_rule), rules.index(f'RULE-SET,ads-lite,{aggregate.ADS}'))
                self.assertLess(rules.index(meta_rule), rules.index(f'RULE-SET,cn,{aggregate.CN}'))
                dns = data['dns']
                self.assertEqual(dns['nameserver'], ['https://9.9.9.9/dns-query', 'https://149.112.112.112/dns-query'])
                self.assertEqual(dns['nameserver-policy']['+.facebook.com'],
                                 ['https://1.1.1.1/dns-query', 'https://1.0.0.1/dns-query'])
                self.assertEqual(dns['nameserver-policy']['+.facebook.com'],
                                 dns['nameserver-policy']['+.openai.com'])
                self.assertFalse(any('💬' in name for name in groups))
                for policy, addresses in aggregate.DNS.items():
                    for ip in addresses:
                        self.assertIn(f'IP-CIDR,{ip}/32,{policy},no-resolve', rules)
                self.assertIn('proxy-server-nameserver', dns)
                for proxy in proxies.values():
                    self.assertEqual('benchmark-url' in proxy, target == 'stash')
                    if proxy['type'] == 'hysteria2':
                        self.assertEqual('auth' in proxy, target == 'stash')
                        self.assertEqual('password' in proxy, target == 'mihomo')
                self.assertEqual('follow-rule' in dns, target == 'stash')
                self.assertEqual('tun' in data, target == 'mihomo')
                if target == 'stash':
                    self.assertNotIn('url', groups[aggregate.SENSITIVE])


if __name__ == '__main__':
    unittest.main()
