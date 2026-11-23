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
        for process in ('agy_acp_server.par', 'localharness_external', 'agy'):
            rule = f'AND,((PROCESS-NAME,{process}),(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN'
            self.assertEqual(main['rules'].count(rule), 1)
            self.assertLess(main['rules'].index(rule), main['rules'].index('DOMAIN,oauth2.googleapis.com,🤖 AI / Meta 服务'))
        google_rules = [
            'AND,((PROCESS-PATH,/Applications/Antigravity.app/Contents/Resources/bin/language_server),'
            '(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN',
            'DOMAIN-SUFFIX,aistudio.google.com,gcloud/CDN',
            'DOMAIN-SUFFIX,ai.google.dev,gcloud/CDN',
            'DOMAIN-SUFFIX,generativelanguage.googleapis.com,gcloud/CDN',
            'DOMAIN,accounts.google.com,gcloud/CDN',
            'DOMAIN,oauth2.googleapis.com,gcloud/CDN',
            'DOMAIN-SUFFIX,gemini.google.com,gcloud/CDN',
            'DOMAIN,geminiweb-pa.clients6.google.com,gcloud/CDN',
            *[f'{match},gcloud/CDN' for match in fixtures.GOOGLE_WEB_RULES],
        ]
        app_rule = next(r for r in main['rules'] if r.startswith('PROCESS-PATH-REGEX,'))
        for rule in google_rules:
            self.assertEqual(main['rules'].count(rule), 1)
            self.assertLess(main['rules'].index(rule), main['rules'].index(app_rule))
        # Given an existing balanced config, selecting a Google AI exit changes
        # only these Google AI rules, not DNS, nodes, groups or other service routing.
        self.fixture.plan.pop('mihomo_agy_proxy')
        self.fixture.save_plan()
        self.fixture.generate()
        without_override = self.outputs()['mihomo/routing.yaml']
        pinned = [r for r in main['rules'] if r not in without_override['rules']]
        self.assertEqual(pinned[:3], [
            f'AND,((PROCESS-NAME,{name}),(DOMAIN-SUFFIX,googleapis.com)),gcloud/CDN'
            for name in ('agy_acp_server.par', 'localharness_external', 'agy')])
        self.assertEqual(pinned[3:], google_rules)
        self.assertEqual([r for r in main['rules'] if r not in pinned], without_override['rules'])
        self.assertEqual({k: v for k, v in main.items() if k != 'rules'},
                         {k: v for k, v in without_override.items() if k != 'rules'})
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

    def test_split_google_exits_only_change_main_google_rules(self):
        # Given two explicitly chosen service exits outside the ordinary sensitive pool,
        # only the three agy processes move to lax; browser/GUI and Studio RPCs stay together.
        self.fixture.plan.update(mihomo_main_policy='daily', mihomo_agy_proxy='gcloud/CDN')
        self.fixture.save_plan()
        self.fixture.generate()
        before = self.outputs()
        del self.fixture.plan['mihomo_agy_proxy']
        self.fixture.plan['mihomo_google_ai_exits'] = {'agy': 'lax/Reality', 'default': 'gcloud/Reality'}
        self.fixture.save_plan()
        self.fixture.generate()
        after = self.outputs()
        main = 'mihomo/routing.yaml'
        expected = copy.deepcopy(before)
        rules = expected[main]['rules']
        for index, rule in enumerate(rules):
            if rule.endswith(',gcloud/CDN'):
                exit_name = 'lax/Reality' if '(PROCESS-NAME,' in rule else 'gcloud/Reality'
                rules[index] = rule.removesuffix('gcloud/CDN') + exit_name
        pos = rules.index('DOMAIN,geminiweb-pa.clients6.google.com,gcloud/Reality') + 1
        rules[pos:pos] = [f'DOMAIN,{host}.clients6.google.com,gcloud/Reality'
                          for host in ('alkalimakersuite-pa', 'waa-pa', 'people-pa')]
        self.assertTrue(after == expected, 'unexpected change outside split Google rules')
        for exits in ({'agy': 'lax/Reality'}, {'default': 'gcloud/Reality', 'agy': 'DIRECT'},
                      {'default': 'gcloud/Reality', 'agy': 'missing/Reality'}):
            with self.subTest(exits=exits):
                self.fixture.plan['mihomo_google_ai_exits'] = exits
                self.fixture.save_plan()
                with self.assertRaisesRegex(ValueError, 'mihomo_google_ai_exits'):
                    self.fixture.generate()
                self.assertTrue(self.outputs() == after)

    def test_stash_google_web_exit_only_changes_stash_main(self):
        self.fixture.generate()
        before = self.outputs()
        self.fixture.plan['stash_google_ai_proxy'] = 'gcloud/Reality'
        self.fixture.save_plan()
        self.fixture.generate()
        after = self.outputs()
        main = 'stash/routing.yaml'
        routes = [f'{match},gcloud/Reality' for match in (
            'DOMAIN-SUFFIX,aistudio.google.com', 'DOMAIN-SUFFIX,ai.google.dev',
            'DOMAIN-SUFFIX,generativelanguage.googleapis.com', 'DOMAIN,accounts.google.com',
            'DOMAIN,oauth2.googleapis.com', 'DOMAIN-SUFFIX,gemini.google.com',
            'DOMAIN,geminiweb-pa.clients6.google.com', 'DOMAIN,alkalimakersuite-pa.clients6.google.com',
            'DOMAIN,waa-pa.clients6.google.com', 'DOMAIN,people-pa.clients6.google.com',
            *fixtures.GOOGLE_WEB_RULES,
        )]
        rules = after[main]['rules']
        self.assertEqual([r for r in rules if r not in before[main]['rules']], routes)
        self.assertLess(rules.index(routes[-1]), rules.index('RULE-SET,ai,🤖 AI / Meta 服务'))
        after[main]['rules'] = [r for r in rules if r not in routes]
        self.assertEqual(after, before)
        for invalid in ('missing/Reality', 'gcloud/Reality,REJECT'):
            with self.subTest(invalid=invalid):
                self.fixture.plan['stash_google_ai_proxy'] = invalid
                self.fixture.save_plan()
                with self.assertRaisesRegex(ValueError, 'stash_google_ai_proxy'):
                    self.fixture.generate(target='stash')
                self.assertEqual(self.outputs()[main]['rules'], rules)

    def test_google_selector_replaces_pins_in_both_main_configs(self):
        self.fixture.plan.update(
            mihomo_main_policy='daily',
            mihomo_google_ai_exits={'agy': 'lax/Reality', 'default': 'gcloud/Reality'},
            stash_google_ai_proxy='gcloud/Reality',
        )
        self.fixture.save_plan()
        self.fixture.generate()
        before = self.outputs()
        self.fixture.plan['google_ai_select'] = True
        self.fixture.save_plan()
        self.fixture.generate()
        after = self.outputs()

        expected = copy.deepcopy(before)
        for target in ('mihomo', 'stash'):
            main = expected[f'{target}/routing.yaml']
            main['proxy-groups'].insert(1, {
                'name': 'Google AI', 'type': 'select',
                'proxies': ['gcloud/Reality', 'cstone/Reality', 'gcloud/CDN', 'lax/Reality'],
            })
            self.assertIn('DOMAIN,flow.google.com,gcloud/Reality', main['rules'])
            self.assertIn('DOMAIN,accounts.google.com,gcloud/Reality', main['rules'])
            for i, rule in enumerate(main['rules']):
                match, _, exit_name = rule.rpartition(',')
                if exit_name in ('gcloud/Reality', 'lax/Reality'):
                    main['rules'][i] = f'{match},Google AI'
        self.assertEqual(after, expected)
        self.assertEqual(self.fixture.generate(check=True), 0)

        self.fixture.plan.pop('mihomo_google_ai_exits')
        self.fixture.plan.pop('stash_google_ai_proxy')
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, 'google_ai_select'):
            self.fixture.generate()
        self.assertEqual(self.outputs(), after)

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
        rules = self.outputs()['mihomo/routing.yaml']['rules']
        for process in ('agy_acp_server.par', 'localharness_external', 'agy'):
            self.assertFalse(any(f'(PROCESS-NAME,{process}),' in r for r in rules), process)
        self.assertFalse(any('PROCESS-PATH,/Applications/Antigravity.app/' in r for r in rules))
        self.assertNotIn('DOMAIN-SUFFIX,aistudio.google.com,gcloud/CDN', rules)
        self.assertNotIn('DOMAIN-SUFFIX,ai.google.dev,gcloud/CDN', rules)
        self.assertNotIn('DOMAIN-SUFFIX,generativelanguage.googleapis.com,gcloud/CDN', rules)
        self.assertNotIn('DOMAIN,accounts.google.com,gcloud/CDN', rules)
        self.assertNotIn('DOMAIN,oauth2.googleapis.com,gcloud/CDN', rules)
        self.assertNotIn('DOMAIN-SUFFIX,gemini.google.com,gcloud/CDN', rules)
        self.assertNotIn('DOMAIN,geminiweb-pa.clients6.google.com,gcloud/CDN', rules)
        self.fixture.plan.pop('credential_identity')
        self.fixture.plan.update(devices=['mac'], client='mihomo', standalone=False)
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, '共享身份'):
            self.fixture.generate()


if __name__ == '__main__':
    unittest.main()
