"""Routing boundaries and source lifecycle for multi-profile client output."""
import copy
import json
import os
import ipaddress
import re
import shutil
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import client_aggregate as aggregate
import ordinary_policy
from client_snapshot import import_snapshot

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
        self.current_target = kwargs.get('target') or 'stash'
        return aggregate.generate(self.root, 'routing', **kwargs)

    def output(self, device='mac', target=None):
        name = 'routing.yaml' if 'credential_identity' in self.plan else f'routing-{device}.yaml'
        return self.root / 'clash-configs' / (target or getattr(self, 'current_target', 'stash')) / name

    def shared_plan(self):
        self.plan.pop('devices')
        self.plan.pop('client')
        self.plan['credential_identity'] = 'mac'
        self.save_plan()

    def test_shared_plan_defaults_to_two_clients_without_device_labels(self):
        # Given one existing identity, both clients share nodes but not their schema/files.
        self.shared_plan()
        legacy = self.root / 'clash-configs/routing-mac.yaml'
        legacy.parent.mkdir()
        legacy.write_text('existing distribution copy')
        self.assertEqual(self.generate(), 0)
        for target in ('stash', 'mihomo'):
            path = self.output(target=target)
            self.assertEqual([p.name for p in path.parent.glob('*.yaml')], ['routing.yaml'])
            text = path.read_text()
            self.assertIn('mac-only', text)
            self.assertNotIn('phone-only', text)
            self.assertNotIn('device: mac', text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(legacy.read_text(), 'existing distribution copy')
        self.assertEqual(self.generate(check=True), 0)
        self.output(target='mihomo').write_text('drift')
        self.assertEqual(self.generate(check=True), 1)

    @unittest.skipUnless(yaml, 'PyYAML required')
    def test_standalone_files_cover_main_nodes_and_share_routing(self):
        # Given a shared main plan, every server must have an independently usable
        # client file with exactly its main-config credentials and all transports.
        self.shared_plan()
        self.plan['standalone'] = True
        self.save_plan()
        self.assertEqual(self.generate(), 0)
        for target in ('stash', 'mihomo'):
            directory = self.root / 'clash-configs' / target
            main = yaml.safe_load((directory / 'routing.yaml').read_text())
            self.assertEqual({p.name for p in directory.glob('*.yaml')},
                             {'routing.yaml', 'routing-cstone.yaml', 'routing-lax.yaml', 'routing-gcloud.yaml'})
            for alias in ('cstone', 'lax', 'gcloud'):
                child = yaml.safe_load((directory / f'routing-{alias}.yaml').read_text())
                self.assertEqual(child['proxies'], [n for n in main['proxies'] if n['name'].startswith(alias + '/')])
                self.assertEqual(child['rules'], main['rules'])
                self.assertEqual(child['dns'], main['dns'])
                groups = {g['name']: g for g in child['proxy-groups']}
                self.assertEqual(groups[aggregate.SENSITIVE]['proxies'],
                                 [alias + ('/CDN' if alias == 'gcloud' else '/Reality')])
                allowed = {n['name'] for n in child['proxies']} | set(groups) | {'DIRECT', 'REJECT'}
                for group in groups.values():
                    self.assertTrue(group['proxies'])
                    self.assertTrue(set(group['proxies']) <= allowed)
        self.assertEqual(self.generate(check=True), 0)
        child = self.root / 'clash-configs/mihomo/routing-lax.yaml'
        child.write_text(child.read_text() + '# drift')
        self.assertEqual(self.generate(check=True), 1)

    def test_standalone_requires_shared_identity(self):
        self.plan['standalone'] = True
        self.save_plan()
        with self.assertRaisesRegex(ValueError, '共享'):
            self.generate()

    def test_one_target_does_not_replace_other_client(self):
        self.shared_plan()
        self.generate()
        other = self.output(target='stash')
        other.write_text(other.read_text() + '# local edit\n')
        original = other.read_bytes()
        self.generate(target='mihomo')
        self.assertEqual(other.read_bytes(), original)

    def test_second_client_failure_preserves_both_outputs(self):
        self.shared_plan()
        self.generate()
        originals = {t: self.output(target=t).read_bytes() for t in ('stash', 'mihomo')}
        original_collect = aggregate.collect_nodes
        def fail_mihomo(root, plan, target):
            if target == 'mihomo':
                raise ValueError('second client failed')
            return original_collect(root, plan, target)
        with mock.patch.object(aggregate, 'collect_nodes', side_effect=fail_mihomo):
            with self.assertRaisesRegex(ValueError, 'second client failed'):
                self.generate()
        for target, text in originals.items():
            self.assertEqual(self.output(target=target).read_bytes(), text)

    def test_shared_identity_must_exist_on_sensitive_sources(self):
        self.shared_plan()
        self.plan['credential_identity'] = 'missing'
        self.save_plan()
        with self.assertRaisesRegex(ValueError, 'missing 缺少指定'):
            self.generate()
        self.assertFalse(self.output().exists())

    def test_publish_stash_only_and_refuse_stale_or_unowned_destination(self):
        self.shared_plan()
        self.generate()
        destination = self.root / 'icloud'
        destination.mkdir()
        unrelated = destination / 'personal.yaml'
        unrelated.write_text('keep me')
        self.assertEqual(aggregate.publish_stash(self.root, 'routing', destination), 0)
        published = destination / 'routing.yaml'
        self.assertEqual(published.read_bytes(), self.output(target='stash').read_bytes())
        self.assertEqual(published.stat().st_mode & 0o777, 0o600)
        self.assertEqual(unrelated.read_text(), 'keep me')
        self.assertEqual(len(list(destination.glob('routing*.yaml'))), 1)
        self.output(target='stash').write_text('stale')
        original = published.read_bytes()
        with self.assertRaisesRegex(ValueError, '过期'):
            aggregate.publish_stash(self.root, 'routing', destination)
        self.assertEqual(published.read_bytes(), original)
        self.generate()
        published.write_text('someone else')
        with self.assertRaisesRegex(ValueError, '归属'):
            aggregate.publish_stash(self.root, 'routing', destination)
        self.assertEqual(published.read_text(), 'someone else')

    def test_publish_refuses_symlink_destination(self):
        self.shared_plan()
        self.generate()
        destination = self.root / 'icloud'
        destination.mkdir()
        victim = self.root / 'victim'
        victim.write_text('do not replace')
        (destination / 'routing.yaml').symlink_to(victim)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            aggregate.publish_stash(self.root, 'routing', destination)
        self.assertEqual(victim.read_text(), 'do not replace')

    def test_publication_uses_verified_bytes_not_a_second_read(self):
        self.shared_plan()
        self.generate()
        source = self.output(target='stash')
        verified = source.read_bytes()
        destination = self.root / 'icloud'
        destination.mkdir()
        original_write = aggregate.write_outputs
        def concurrent_edit(*args, **kwargs):
            result = original_write(*args, **kwargs)
            source.write_text('changed after validation')
            return result
        with mock.patch.object(aggregate, 'write_outputs', side_effect=concurrent_edit):
            aggregate.publish_stash(self.root, 'routing', destination)
        self.assertEqual((destination / 'routing.yaml').read_bytes(), verified)

    @unittest.skipUnless(yaml, 'PyYAML required')
    def test_imported_snapshot_preserves_node_identity_and_uses_new_rules(self):
        self.generate(target='stash')
        source = self.output()
        original = yaml.safe_load(source.read_text())
        self.assertEqual(import_snapshot(self.root, 'imported', source), 0)
        self.assertEqual(aggregate.generate(self.root, 'imported'), 0)
        for target in ('stash', 'mihomo'):
            data = yaml.safe_load((self.root / 'clash-configs' / target / 'imported.yaml').read_text())
            self.assertEqual([n['name'] for n in data['proxies']], [n['name'] for n in original['proxies']])
            for before, after in zip(original['proxies'], data['proxies']):
                for key in ('server', 'port', 'uuid', 'reality-opts', 'ws-opts'):
                    self.assertEqual(after.get(key), before.get(key))
                if before['type'] == 'hysteria2':
                    self.assertEqual(after['auth' if target == 'stash' else 'password'], before['auth'])
                elif before['type'] == 'anytls':
                    self.assertEqual(after['password'], before['password'])
            self.assertEqual(data['rules'][-1], f'MATCH,{aggregate.SENSITIVE}')
        self.assertEqual((self.root / 'profiles/imported/nodes.json').stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(ValueError, '已存在'):
            import_snapshot(self.root, 'imported', source)

    @unittest.skipUnless(yaml, 'PyYAML required')
    def test_snapshot_rejects_udp_unsupported_sensitive_exit_without_exposing_credentials(self):
        self.generate(target='stash')
        data = yaml.safe_load(self.output().read_text())
        data['proxies'][0]['udp'] = False
        source = self.root / 'unsupported.yaml'
        source.write_text(yaml.safe_dump(data))
        with self.assertRaisesRegex(ValueError, '不符合导入契约') as error:
            import_snapshot(self.root, 'imported', source)
        self.assertNotIn('mac-only', str(error.exception))
        self.assertFalse((self.root / 'profiles/imported').exists())

    @unittest.skipUnless(yaml, 'PyYAML required')
    def test_only_explicit_ordinary_services_can_use_auto(self):
        # Given overlapping service categories, sensitive/CN rules win and
        # unknown services must never inherit a broad overseas AUTO default.
        self.shared_plan()
        self.generate()
        for target in ('stash', 'mihomo'):
            data = yaml.safe_load(self.output(target=target).read_text())
            rules = data['rules']
            auto_rules = [r for r in rules if len(r.split(',')) >= 3
                          and r.split(',')[2] == aggregate.OVERSEAS]
            self.assertTrue(auto_rules)
            self.assertTrue(all(r.startswith(('DOMAIN,', 'DOMAIN-SUFFIX,', 'IP-CIDR,', 'IP-CIDR6,', 'RULE-SET,ordinary-'))
                                for r in auto_rules))
            for host in ('youtube.com', 'googlevideo.com', 'netflix.com', 'telegram.org',
                         'interactivebrokers.com', 'ibkr.com', 'tradingview.com', 'spotify.com',
                         'twitch.tv', 'reddit.com', 'wikipedia.org'):
                self.assertIn(f'DOMAIN-SUFFIX,{host},{aggregate.OVERSEAS}', rules)
            first_auto = min(rules.index(r) for r in auto_rules)
            for protected in (f'DOMAIN-SUFFIX,openai.com,{aggregate.AI}',
                              f'DOMAIN,accounts.google.com,{aggregate.AI}',
                              f'RULE-SET,ai,{aggregate.AI}', f'RULE-SET,cn,{aggregate.CN}',
                              f'RULE-SET,ads-lite,{aggregate.ADS}'):
                self.assertLess(rules.index(protected), first_auto)
            for host in ('google.com', 'googleapis.com', 'cloudfront.net', 'amazonaws.com',
                         'cloudflare.com', 'googleusercontent.com'):
                self.assertNotIn(f'DOMAIN-SUFFIX,{host},{aggregate.OVERSEAS}', rules)
            self.assertEqual(rules[-1], f'MATCH,{aggregate.SENSITIVE}')
            self.assertNotIn('google', data['rule-providers'])
            # Default DNS stays sensitive even for an unrecognized AI dependency.
            self.assertIn(f'IP-CIDR,9.9.9.9/32,{aggregate.SENSITIVE},no-resolve', rules)

    def test_unsafe_ordinary_catalog_fails_before_replacing_outputs(self):
        self.shared_plan()
        self.generate()
        originals = {t: self.output(target=t).read_bytes() for t in ('stash', 'mihomo')}
        catalog = self.root / 'ordinary.json'
        for suffix, message in (('openai.com', '敏感域名重叠'), ('googleapis.com', '共享云'),
                                ('tiktokshop.com', '敏感域名重叠'), ('applovin.com', '敏感域名重叠')):
            catalog.write_text(json.dumps({'test': {'domains': [], 'suffixes': [suffix], 'ip_cidrs': []}}))
            with mock.patch.object(ordinary_policy, 'DATA', catalog):
                with self.assertRaisesRegex(ValueError, message):
                    self.generate()
            for target, content in originals.items():
                self.assertEqual(self.output(target=target).read_bytes(), content)

    @unittest.skipUnless(yaml, 'PyYAML required')
    def test_expanded_catalog_preserves_ai_meta_and_commerce_boundary(self):
        # Given reviewed public service lists, media/games/news/learning/downloads
        # may use AUTO, including the user's Threads exception. AI, Meta business
        # and advertising/commerce must beat CN and AUTO.
        self.shared_plan()
        self.generate()
        for target in ('stash', 'mihomo'):
            rules = yaml.safe_load(self.output(target=target).read_text())['rules']
            data = yaml.safe_load(self.output(target=target).read_text())
            for service in ('disney', 'steam', 'discord', 'reuters', 'coursera', 'python',
                            'docker', 'rust', 'threads'):
                name = 'ordinary-' + service
                self.assertIn(f'RULE-SET,{name},{aggregate.OVERSEAS}', rules)
                provider = data['rule-providers'][name]
                self.assertEqual(provider['behavior'], 'domain')
                self.assertRegex(provider['url'], rf'/[a-f0-9]{{40}}/geo/geosite/{service}[.]mrs$')
                self.assertEqual(provider.get('proxy'), aggregate.SENSITIVE if target == 'mihomo' else None)
            # Main routing remains a short, ordered policy, not a domain dump.
            self.assertLess(len(rules), 450)
            first_auto = next(i for i, r in enumerate(rules) if aggregate.OVERSEAS in r)
            cn_index = rules.index(f'RULE-SET,cn,{aggregate.CN}')
            for domain in ('facebook.com', 'tiktokshop.com', 'tiktokglobalshop.com',
                           'tiktok.com', 'applovin.com', 'ads.google.com', 'line.biz', 'brightline.tv'):
                matches = [i for i, r in enumerate(rules)
                           if r in (f'DOMAIN-SUFFIX,{domain},{aggregate.AI}',
                                    f'DOMAIN-SUFFIX,{domain},{aggregate.SENSITIVE}')]
                self.assertTrue(matches, domain)
                self.assertLess(min(matches), min(first_auto, cn_index))
            for domain in ('x.com', 'twitter.com', 'github.com', 'notion.so', 'google.com',
                           'microsoft.com', 'openai.com', 'facebook.com', 'tiktok.com'):
                self.assertNotIn(f'DOMAIN-SUFFIX,{domain},{aggregate.OVERSEAS}', rules)
            self.assertEqual(rules[-1], f'MATCH,{aggregate.SENSITIVE}')

    def test_mutable_or_broad_ordinary_rulesets_cannot_replace_outputs(self):
        # An unreviewed moving branch or all-overseas category must not silently
        # expand AUTO's scope; existing generated files survive validation failure.
        self.shared_plan()
        self.generate()
        before = {t: self.output(target=t).read_bytes() for t in ('stash', 'mihomo')}
        path = self.root / 'rulesets.json'
        for revision, services in (('meta', ['steam']), ('a' * 40, ['category-dev']),
                                   ('a' * 40, ['google']), ('a' * 40, ['steam', 'steam'])):
            path.write_text(json.dumps({'revision': revision, 'categories': {'test': services}}))
            with mock.patch.object(ordinary_policy, 'RULESETS', path):
                with self.assertRaises(ValueError):
                    self.generate()
            for target, text in before.items():
                self.assertEqual(self.output(target=target).read_bytes(), text)

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
                    'api.replicate.com', 'fal.run', 'v0.app', 'api.githubcopilot.com',
                    'platform.claude.com', 'mcp-proxy.anthropic.com', 'downloads.claude.ai',
                    'bridge.claudeusercontent.com', 'a.frame.claudeusercontent.com',
                    'assets-proxy.anthropic.com', 'a.livepreview.claude.app',
                    'http-intake.logs.us5.datadoghq.com', 'cdnjs.cloudflare.com',
                    'cdn.jsdelivr.net', 'cdn.tailwindcss.com', 'code.jquery.com',
                    'unpkg.com', 'fonts.googleapis.com', 'fonts.gstatic.com')
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
        if os.environ.get('MIHOMO_DATA_DIR'):
            for name in ('geoip.dat', 'geosite.dat', 'ASN.mmdb', 'Country.mmdb'):
                source = Path(os.environ['MIHOMO_DATA_DIR']) / name
                if source.is_file():
                    shutil.copyfile(source, self.root / name)
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
                self.assertEqual(set(groups[aggregate.AUTO]['proxies']), set(proxies))
                self.assertNotIn('DIRECT', groups[aggregate.AUTO]['proxies'])
                if target == 'mihomo':
                    self.assertEqual(groups[aggregate.AUTO]['tolerance'], 50)
                self.assertEqual(groups[aggregate.AI]['proxies'], [aggregate.SENSITIVE])
                self.assertEqual(groups[aggregate.OVERSEAS]['proxies'], [aggregate.AUTO, aggregate.SENSITIVE, aggregate.MANUAL])
                self.assertEqual(groups[aggregate.APPLE]['proxies'][0], aggregate.SENSITIVE)
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
                self.assertEqual(rules[-1], f'MATCH,{aggregate.SENSITIVE}')
                self.assertNotIn('DOMAIN-KEYWORD,spotify,DIRECT', rules)
                self.assertNotIn('DOMAIN-SUFFIX,scdn.co,DIRECT', rules)
                self.assertNotIn(f'DOMAIN-SUFFIX,cn,{aggregate.CN}', rules)
                self.assertNotIn(f'GEOIP,CN,{aggregate.CN},no-resolve', rules)
                self.assertNotIn(f'RULE-SET,cn-ip,{aggregate.CN},no-resolve', rules)
                self.assertIn(f'RULE-SET,apple-cn,{aggregate.CN}', rules)
                self.assertLess(rules.index(f'RULE-SET,apple-cn,{aggregate.CN}'),
                                rules.index(f'RULE-SET,icloud,{aggregate.APPLE}'))
                self.assertFalse(any(r.startswith(('NETWORK,', 'PROTOCOL,')) for r in rules))
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
                if target == 'mihomo':
                    exclusions = data['tun']['route-exclude-address']
                    for ip in ('127.0.0.1', '10.0.0.1', '192.168.1.1', '100.64.0.1'):
                        self.assertTrue(any(ipaddress.ip_address(ip) in ipaddress.ip_network(net)
                                            for net in exclusions if ':' not in net))
                    self.assertFalse(any(ipaddress.ip_address('8.8.8.8') in ipaddress.ip_network(net)
                                         for net in exclusions if ':' not in net))
                if target == 'stash':
                    self.assertNotIn('url', groups[aggregate.SENSITIVE])


if __name__ == '__main__':
    unittest.main()
