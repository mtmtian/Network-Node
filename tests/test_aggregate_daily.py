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
        self.assertEqual(len(main['rules']), 423)
        self.assertEqual(sum('lightpanda' in rule for rule in main['rules']), 10)
        self.assertEqual(main['rules'][-3:], ['RULE-SET,cn-ip,🇨🇳 国内流量',
                                             'GEOIP,CN,🇨🇳 国内流量', 'MATCH,🌐 普通海外'])
        self.assertLess(main['rules'].index('DOMAIN-SUFFIX,smoot.apple.com,🤖 AI / Meta 服务'),
                        main['rules'].index('DOMAIN-SUFFIX,apple.com,🍎 Apple 基础服务'))
        self.assertIn('AND,((PROCESS-NAME,agy),(DOMAIN-SUFFIX,googleapis.com)),🤖 AI / Meta 服务', main['rules'])
        self.assertIn('AND,((PROCESS-PATH,/Applications/Antigravity.app/Contents/Resources/bin/language_server),(DOMAIN-SUFFIX,googleapis.com)),🤖 AI / Meta 服务', main['rules'])
        for dependency in ('DOMAIN,maps.googleapis.com,🤖 AI / Meta 服务',
                           'DOMAIN-SUFFIX,withpersona.com,🤖 AI / Meta 服务',
                           'DOMAIN-SUFFIX,frompersona.com,🤖 AI / Meta 服务',
                           'DOMAIN-SUFFIX,sentry.io,🤖 AI / Meta 服务',
                           'DOMAIN-KEYWORD,sentry,🤖 AI / Meta 服务',
                           'DOMAIN-KEYWORD,datadog,🤖 AI / Meta 服务',
                           'DOMAIN-KEYWORD,sift,🤖 AI / Meta 服务'):
            self.assertIn(dependency, main['rules'])
        self.assertLess(main['rules'].index('AND,((PROCESS-NAME,agy),(DOMAIN-SUFFIX,googleapis.com)),🤖 AI / Meta 服务'),
                        main['rules'].index('RULE-SET,cn-ip,🇨🇳 国内流量'))
        self.assertLess(main['rules'].index('AND,((PROCESS-PATH,/Applications/Antigravity.app/Contents/Resources/bin/language_server),(DOMAIN-SUFFIX,googleapis.com)),🤖 AI / Meta 服务'),
                        main['rules'].index('RULE-SET,cn-ip,🇨🇳 国内流量'))
        self.assertEqual(main['dns']['nameserver'], ['https://8.8.8.8/dns-query', 'https://8.8.4.4/dns-query'])

        # Independent 2026-11-04 production baseline, captured BEFORE implementation.
        # 2026-11-09: rules/DNS add only muse.ai, grokbot.com and grokipedia.com;
        # fixed-fixture comparison verified all other fields and rule order unchanged.
        # 2026-11-10: adds only two DNS.SB IP-CIDR rules and appends DNS.SB to each sensitive
        # resolver list; fixed-fixture comparison verified nothing else changed.
        # Canonical JSON hashes cover every field and rule position, not credentials.
        expected = {
            'rules': '99d91076eeaeebafc959d8218cdca2dd6754ff922126f79e987524061a5a0325',
            'dns': 'fbc31c6853f6afb15d40586daad4815a7783622775a1dbdaded566d90e906076',
            'rule-providers': '33888f3e51d297f73cfb603dab7b7d31ae5c559264eab07a4cf9b46bffb3a770',
            'proxy-groups': '09d5331a573248ae6c1e7d46a9be127f08ab5b68f1518cd0d151f35228a87503',
        }
        for section, digest in expected.items():
            actual = json.dumps(main[section], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(), digest, section)
        self.assertEqual(self.fixture.generate(check=True), 0)

    def test_daily_google_ai_proxy_changes_only_the_six_precise_rules(self):
        self.fixture.plan['mihomo_main_policy'] = 'daily'
        self.fixture.save_plan()
        self.fixture.generate()
        before = self.outputs()
        self.fixture.plan['mihomo_agy_proxy'] = 'gcloud/CDN'
        self.fixture.save_plan()
        self.fixture.generate()
        after = self.outputs()
        main = after['mihomo/routing.yaml']
        before_main = before['mihomo/routing.yaml']
        self.assertTrue(
            {name: config for name, config in after.items() if name != 'mihomo/routing.yaml'}
            == {name: config for name, config in before.items() if name != 'mihomo/routing.yaml'},
            'non-Mihomo outputs changed')

        expected_rules = [
            'AND,((PROCESS-NAME,agy_acp_server.par),(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN',
            'AND,((PROCESS-NAME,localharness_external),(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN',
            'AND,((PROCESS-NAME,agy),(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN',
            'AND,((PROCESS-PATH,/Applications/Antigravity.app/Contents/Resources/bin/language_server),'
            '(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN',
            'DOMAIN-SUFFIX,gemini.google.com,gcloud/CDN',
            'DOMAIN,geminiweb-pa.clients6.google.com,gcloud/CDN',
        ]
        rules = main['rules']
        indexes = [rules.index(rule) for rule in expected_rules]
        self.assertEqual([rules.count(rule) for rule in expected_rules], [1] * 6)
        self.assertEqual(indexes, list(range(indexes[0], indexes[0] + 6)))
        old_ai_rules = [rule.replace('gcloud/CDN', '🤖 AI / Meta 服务') for rule in expected_rules]
        baseline_other_rules = list(before_main['rules'])
        for rule in old_ai_rules:
            reverse_index = baseline_other_rules[::-1].index(rule)
            del baseline_other_rules[len(baseline_other_rules) - reverse_index - 1]
        self.assertTrue(
            [rule for rule in rules if rule not in expected_rules] == baseline_other_rules,
            'daily rules other than the six Google AI routes changed')
        for section in main.keys() - {'rules'}:
            self.assertTrue(main[section] == before_main[section], f'{section} changed')
        app_rule = next(i for i, rule in enumerate(rules) if rule.startswith('PROCESS-PATH-REGEX,'))
        ai_rule = rules.index('RULE-SET,ai,🤖 AI / Meta 服务')
        self.assertLess(indexes[-1], app_rule)
        self.assertLess(indexes[-1], ai_rule)
        self.assertIn('DOMAIN-SUFFIX,anthropic.com,🤖 AI / Meta 服务', rules)
        self.assertIn('DOMAIN,maps.googleapis.com,🤖 AI / Meta 服务', rules)
        self.assertIn('RULE-SET,cn-ip,🇨🇳 国内流量', rules[-3])
        self.assertEqual(main['rules'][-3:], ['RULE-SET,cn-ip,🇨🇳 国内流量',
                                             'GEOIP,CN,🇨🇳 国内流量', 'MATCH,🌐 普通海外'])
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
