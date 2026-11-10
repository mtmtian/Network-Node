"""Given the existing outputs, opt in only the approved Mihomo main behaviors.

Acceptance: agy uses an explicit sensitive node; Apple AI precedes the basic
whitelist; defaults/ordinary DNS use Google+Cloudflare; other files stay equal.
"""
import copy
import unittest

import test_aggregate as fixtures


@unittest.skipUnless(fixtures.yaml, 'PyYAML required')
class AggregateBalancedTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AggregateTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.shared_plan()
        self.fixture.plan['standalone'] = True
        self.fixture.save_plan()

    def outputs(self):
        return {str(p.relative_to(self.fixture.root / 'clash-configs')): fixtures.yaml.safe_load(p.read_text())
                for p in (self.fixture.root / 'clash-configs').rglob('*.yaml')}

    def test_balanced_main_and_other_outputs(self):
        self.fixture.generate()
        before = self.outputs()
        self.fixture.plan.update(mihomo_main_policy='balanced', mihomo_agy_proxy='gcloud/CDN')
        self.fixture.save_plan()
        self.fixture.generate()
        after = self.outputs()
        for name in before:
            if name != 'mihomo/routing.yaml':
                self.assertEqual(before[name], after[name], name)
        main = after['mihomo/routing.yaml']
        old = before['mihomo/routing.yaml']
        self.assertEqual(main['proxies'], old['proxies'])
        self.assertEqual(main['rule-providers'], old['rule-providers'])
        self.assertEqual(main['rules'][-1], 'MATCH,🌐 普通海外')
        groups = {g['name']: g for g in main['proxy-groups']}
        self.assertEqual(groups['🛡 敏感服务'], dict(name='🛡 敏感服务', type='select',
                                               proxies=['cstone/Reality', 'gcloud/CDN']))
        self.assertEqual(groups['🍎 Apple 基础服务']['proxies'], ['DIRECT', '🌐 普通海外', '🛡 敏感服务'])
        for process in ('agy_acp_server.par', 'localharness_external'):
            rule = f'AND,((PROCESS-NAME,{process}),(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN'
            self.assertEqual(main['rules'].count(rule), 1)
            self.assertLess(main['rules'].index(rule), main['rules'].index('DOMAIN,oauth2.googleapis.com,🤖 AI / Meta 服务'))
        for host in ('apple-relay.apple.com', 'apple-relay.cloudflare.com',
                     'apple-relay.fastly-edge.com', 'cp4.cloudflare.com'):
            rule = f'DOMAIN,{host},🤖 AI / Meta 服务'
            self.assertEqual(main['rules'].count(rule), 1)
            self.assertLess(main['rules'].index(rule), main['rules'].index('RULE-SET,apple-cn,🇨🇳 国内流量'))
        self.assertIn('DOMAIN-SUFFIX,smoot.apple.com,🤖 AI / Meta 服务', main['rules'])
        self.assertIn('RULE-SET,siri,🛡 敏感服务', main['rules'])
        self.assertIn('RULE-SET,icloud-private-relay,🛡 敏感服务', main['rules'])
        self.assertEqual(main['rules'][:10], old['rules'][:10])
        expected_dns = ['https://8.8.8.8/dns-query', 'https://8.8.4.4/dns-query',
                        'https://1.1.1.1/dns-query', 'https://1.0.0.1/dns-query']
        self.assertEqual(main['dns']['nameserver'], expected_dns)
        self.assertEqual(main['dns']['nameserver-policy']['+.youtube.com'], expected_dns)
        for key in ('cloudcode-pa.googleapis.com', 'oauth2.googleapis.com', 'geosite:cn',
                    'geosite:apple-cn', '+.appsflyer.com'):
            self.assertEqual(main['dns']['nameserver-policy'][key], old['dns']['nameserver-policy'][key])
        self.assertNotIn('+.apple.com', main['dns']['nameserver-policy'])
        self.assertEqual(self.fixture.generate(check=True), 0)

    def test_invalid_agy_selection_preserves_outputs(self):
        self.fixture.generate()
        before = self.outputs()
        original = copy.deepcopy(self.fixture.plan)
        for value in ('lax/Reality', 'missing/CDN', '', 'gcloud/CDN,REJECT', True):
            with self.subTest(value=value):
                self.fixture.plan = original | dict(mihomo_main_policy='balanced', mihomo_agy_proxy=value)
                self.fixture.save_plan()
                with self.assertRaisesRegex(ValueError, 'mihomo_agy_proxy'):
                    self.fixture.generate()
                self.assertEqual(before, self.outputs())
        self.fixture.plan = original | dict(mihomo_main_policy='strict', mihomo_agy_proxy='gcloud/CDN')
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, 'balanced'):
            self.fixture.generate()

    def test_balanced_requires_shared_plan_and_allows_no_agy_override(self):
        self.fixture.plan.update(mihomo_main_policy='balanced')
        self.fixture.save_plan()
        self.fixture.generate()
        self.assertFalse(any('PROCESS-NAME,agy_acp_server.par' in r
                             for r in self.outputs()['mihomo/routing.yaml']['rules']))
        self.fixture.plan.pop('credential_identity')
        self.fixture.plan.update(devices=['mac'], client='mihomo', standalone=False)
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, '共享身份'):
            self.fixture.generate()


if __name__ == '__main__':
    unittest.main()
