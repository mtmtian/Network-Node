"""Preserve the deployed main policy without changing Stash or child policies."""
import hashlib
import json
import unittest

import test_aggregate as fixtures


@unittest.skipUnless(fixtures.yaml, 'PyYAML required')
class AggregateDailyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AggregateTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.shared_plan()
        # Match the independently captured production node ordering using test credentials.
        sources = {s['name']: s for s in self.fixture.plan['sources']}
        self.fixture.plan['sources'] = [sources[name] for name in ('cstone', 'lax', 'gcloud')]
        self.fixture.plan['standalone'] = True
        self.fixture.save_plan()

    def outputs(self):
        return {str(p.relative_to(self.fixture.root / 'clash-configs')): fixtures.yaml.safe_load(p.read_text())
                for p in (self.fixture.root / 'clash-configs').rglob('*.yaml')}

    def test_daily_main_preserves_deployed_policy_and_other_outputs(self):
        # Given the existing strict plan, opt in only the Mihomo main output.
        self.fixture.generate()
        before = self.outputs()
        self.fixture.plan['mihomo_main_policy'] = 'daily'
        self.fixture.save_plan()
        self.fixture.generate()
        after = self.outputs()
        for name in before:
            if name != 'mihomo/routing.yaml':
                self.assertEqual(before[name], after[name], name)
        main = after['mihomo/routing.yaml']
        self.assertEqual(main['proxies'], before['mihomo/routing.yaml']['proxies'])
        self.assertEqual(len(main['rules']), 403)
        self.assertEqual(sum('lightpanda' in rule for rule in main['rules']), 10)
        self.assertEqual(main['rules'][-3:], ['RULE-SET,cn-ip,🇨🇳 国内流量',
                                             'GEOIP,CN,🇨🇳 国内流量', 'MATCH,🌐 普通海外'])
        self.assertLess(main['rules'].index('DOMAIN-SUFFIX,smoot.apple.com,🤖 AI / Meta 服务'),
                        main['rules'].index('DOMAIN-SUFFIX,apple.com,🍎 Apple 基础服务'))
        self.assertEqual(main['dns']['nameserver'], ['https://8.8.8.8/dns-query', 'https://8.8.4.4/dns-query'])
        # Independent 2026-11-04 production baseline, captured BEFORE implementation.
        # Canonical JSON hashes cover every field and rule position, not credentials.
        expected = {
            'rules': '10c79d1bfd10d584423f5cd69b1a88245ada0896bf9b83124ab715571d7f58f9',
            'dns': '438a632a38e692cf715ef70ecd4e079452764838191faa93c880dba40995c4db',
            'rule-providers': '33888f3e51d297f73cfb603dab7b7d31ae5c559264eab07a4cf9b46bffb3a770',
            'proxy-groups': '09d5331a573248ae6c1e7d46a9be127f08ab5b68f1518cd0d151f35228a87503',
        }
        for section, digest in expected.items():
            actual = json.dumps(main[section], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(), digest, section)
        self.assertEqual(self.fixture.generate(check=True), 0)

    def test_unknown_policy_fails_before_writing(self):
        self.fixture.generate()
        before = self.outputs()
        self.fixture.plan['mihomo_main_policy'] = 'typo'
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, 'mihomo_main_policy'):
            self.fixture.generate()
        self.assertEqual(self.outputs(), before)

    def test_daily_requires_shared_identity(self):
        self.fixture.plan.pop('credential_identity')
        self.fixture.plan.update(devices=['mac', 'iphone'], client='stash', standalone=False,
                                 mihomo_main_policy='daily')
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, '共享身份'):
            self.fixture.generate()


if __name__ == '__main__':
    unittest.main()
