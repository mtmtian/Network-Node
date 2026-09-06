import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
from settings import load_kv, load_settings, validate
from client_output import write_outputs


class SafetyRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.output = self.root / "clients"
        self.conf = self.state / "deploy.conf"
        self.conf.write_text("DEVICES=mac phone\nREALITY_PORT=443\nREALITY_SNI=\n")
        self.secrets = self.state / ".secrets.env"
        self.secrets.write_text(
            "STATIC_IP=203.0.113.10\nREALITY_PUBLIC=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
            "REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\nANYTLS_PORT=21000\n"
            "ANYTLS_PASS=test-only-password\n"
            "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001\nHY2_PASS_mac=test-mac\n"
            "REALITY_UUID_phone=00000000-0000-4000-8000-000000000002\nHY2_PASS_phone=test-phone\n"
        )
        self.env = os.environ | {"NETWORK_NODE_ROOT": str(ROOT), "NETWORK_NODE_STATE_DIR": str(self.state),
                                 "NETWORK_NODE_CLIENTS_DIR": str(self.output), "NETWORK_NODE_PROFILE": "alpha",
                                 "PROFILE_NAME": "alpha"}

    def generate(self, *args, success=True):
        result = subprocess.run([sys.executable, str(ROOT / "core/gen-clash.py"), *args],
                                env=self.env, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def add_conf(self, text):
        with self.conf.open("a") as handle:
            handle.write(text)

    def run_secrets(self):
        result = subprocess.run(["bash", str(ROOT / "core/secrets.sh")], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_strict_public_traffic_cannot_select_another_exit(self):
        self.add_conf("AI_STRICT_MODE=true\n")
        self.generate()
        text = (self.output / "alpha-mac.yaml").read_text()
        groups = text.split("\nproxy-groups:\n")[1].split("\nrule-providers:\n")[0]
        self.assertEqual(groups.count("  - name:"), 2)
        self.assertNotIn("- DIRECT", groups)
        self.assertNotIn("US-HY2", groups)
        self.assertNotIn("US-AnyTLS", groups)
        self.assertNotIn("US-Reality-WARP", groups)
        rules = text.split("\nrules:\n")[1]
        self.assertTrue(rules.rstrip().endswith("MATCH,🤖 AI 隐私出口"))
        self.assertLess(rules.index("192.168.0.0/16,DIRECT"), rules.index("DST-PORT,123,"))
        self.assertIn("IP-CIDR,1.1.1.1/32,🤖 AI 隐私出口,no-resolve", rules)
        for rule in rules.splitlines():
            if ",DIRECT" in rule:
                self.assertTrue(rule.startswith(("  - IP-CIDR", "  - DOMAIN,localhost,", "  - DOMAIN-SUFFIX,local,", "  - DOMAIN-SUFFIX,lan,")))
        self.assertNotIn("nameserver-policy:", text)
        providers = text.split("\nrule-providers:\n")[1].split("\nrules:\n")[0]
        self.assertIn("  ai:", providers)
        self.assertIn("  ads-lite:", providers)
        self.assertNotIn("  cn:", providers)
        self.assertNotIn("GEOSITE,", rules)
        self.assertNotIn("IP-ASN,", rules)

    def test_fallback_checks_are_active_and_stash_benchmarks_are_proxy_scoped(self):
        for client in ('stash', 'mihomo'):
            for strict in ('false', 'true'):
                with self.subTest(client=client, strict=strict):
                    self.add_conf('AI_STRICT_MODE=' + strict + '\n')
                    self.generate('--client', client)
                    text = (self.output / 'alpha-mac.yaml').read_text()
                    groups = text.split('\nproxy-groups:\n', 1)[1].split('\nrule-providers:\n', 1)[0]
                    blocks = groups.split('  - name:')
                    for block in blocks:
                        if 'type: fallback' in block:
                            self.assertIn('interval: 60', block)
                            self.assertIn('lazy: false', block)
                    self.assertEqual('benchmark-timeout: 5' in text, client == 'stash')

    def test_cdn_internal_ports_cannot_collide_with_public_services(self):
        for port in ('8080', '20241'):
            with self.assertRaisesRegex(ValueError, '重复'):
                validate({'CDN_ENABLE': 'true', 'ANYTLS_PORT': port})

    def test_default_routes_domestic_direct_without_weakening_ai_priority(self):
        for client in ("stash", "mihomo"):
            with self.subTest(client=client):
                self.generate("--client", client)
                config = (self.output / "alpha-mac.yaml").read_text()
                cn_group = config.split('name: "🇨🇳 国内流量"', 1)[1].split('name: "🛑 屏蔽流量"', 1)[0]
                self.assertLess(cn_group.index("- DIRECT"), cn_group.index('- "🌐 代理流量"'))
                rules = config.split("\nrules:\n", 1)[1]
                for boundary in ("RULE-SET,ads-lite,", "DOMAIN-SUFFIX,cn,", "RULE-SET,cn,", "RULE-SET,cn-ip,"):
                    for dependency in ("DOMAIN-SUFFIX,openai.com,", "DOMAIN,anthropic.auth0.com,",
                                       "DOMAIN,cdn.workos.com,", "DOMAIN-KEYWORD,datadog,", "RULE-SET,ai,"):
                        self.assertLess(rules.index(dependency), rules.index(boundary))
                for resolver in ("223.5.5.5", "120.53.53.53"):
                    route = f"IP-CIDR,{resolver}/32,🇨🇳 国内流量,no-resolve"
                    self.assertLess(rules.index(route), rules.index("RULE-SET,cn-ip,"))
                for resolver in ("1.1.1.1", "8.8.8.8"):
                    self.assertIn(f"IP-CIDR,{resolver}/32,🤖 AI 隐私出口,no-resolve", rules)
                self.assertIn("  nameserver-policy:", config)
                self.assertTrue(rules.rstrip().endswith("MATCH,🎯 兜底策略"))

    def test_domestic_dns_follows_the_domestic_group_in_both_modes(self):
        self.add_conf("PRIVACY_MODE=true\n")
        self.generate()
        config = (self.output / "alpha-mac.yaml").read_text()
        cn_group = config.split('name: "🇨🇳 国内流量"', 1)[1].split('name: "🛑 屏蔽流量"', 1)[0]
        self.assertLess(cn_group.index('- "🌐 代理流量"'), cn_group.index("- DIRECT"))
        self.assertIn("IP-CIDR,223.5.5.5/32,🇨🇳 国内流量,no-resolve", config)
        self.add_conf("AI_STRICT_MODE=true\n")
        self.generate()
        config = (self.output / "alpha-mac.yaml").read_text()
        self.assertNotIn("🇨🇳 国内流量", config)
        self.assertNotIn("nameserver-policy:", config)
        self.assertIn("IP-CIDR,223.5.5.5/32,🤖 AI 隐私出口,no-resolve", config)

    def test_ai_dependencies_are_preserved_before_ad_blocking(self):
        self.generate()
        rules = (self.output / "alpha-mac.yaml").read_text().split("\nrules:\n")[1]
        ads = rules.index("RULE-SET,ads-lite,")
        for dependency in ("DOMAIN-KEYWORD,datadog,", "DOMAIN-KEYWORD,sentry,", "DOMAIN-KEYWORD,sift,",
                           "DOMAIN,cdn.workos.com,", "DOMAIN,humb.apple.com,", "DOMAIN,js.stripe.com,"):
            self.assertLess(rules.index(dependency), ads)

    def test_client_fields_and_anytls_acme_are_independent(self):
        self.add_conf("HY2_UP=30 mbps\nHY2_DOWN=0.2 gbps\nHY2_ACME_ENABLE=true\nHY2_ACME_DOMAIN=hy2.example.com\n")
        self.generate()
        stash = (self.output / "alpha-mac.yaml").read_text()
        self.assertIn("up-speed: 30", stash)
        self.assertIn("down-speed: 200", stash)
        self.assertIn("  follow-rule: true", stash)
        self.assertNotIn("respect-rules:", stash)
        self.assertNotIn("\ntun:", stash)
        self.assertIn("PROTOCOL,STUN,", stash)
        anytls = stash.split('name: "US-AnyTLS"')[1].split("\nproxy-groups:")[0]
        self.assertIn("skip-cert-verify: true", anytls)
        self.assertNotIn("hy2.example.com", anytls)
        self.generate("--client", "mihomo")
        mihomo = (self.output / "alpha-mac.yaml").read_text()
        self.assertIn('up: "30 mbps"', mihomo)
        self.assertIn("respect-rules: true", mihomo)
        self.assertNotIn("follow-rule:", mihomo)
        self.assertNotIn("PROTOCOL,STUN,", mihomo)
        self.assertIn("\ntun:", mihomo)

    def test_certificate_pin_uses_client_specific_field(self):
        with self.secrets.open("a") as handle:
            handle.write("HY2_CERT_SHA256=" + "ab" * 32 + "\n")
        self.generate()
        self.assertIn("server-cert-fingerprint:", (self.output / "alpha-mac.yaml").read_text())
        self.generate("--client", "mihomo")
        text = (self.output / "alpha-mac.yaml").read_text()
        self.assertIn("    fingerprint:", text)
        self.assertNotIn("server-cert-fingerprint:", text)

    def test_prefix_collision_does_not_delete_other_profile(self):
        self.env["NETWORK_NODE_PROFILE"] = "alpha-next"
        self.generate()
        other = self.output / "alpha-next-mac.yaml"
        before = other.read_bytes()
        self.env["NETWORK_NODE_PROFILE"] = "alpha"
        self.generate()
        self.assertEqual(other.read_bytes(), before)
        self.assertTrue((self.output / "alpha-mac.yaml").exists())

    def test_collision_rejected_before_overwriting_existing_owner(self):
        self.generate()
        before = (self.output / "alpha-mac.yaml").read_bytes()
        self.env["NETWORK_NODE_PROFILE"] = "beta"
        self.add_conf("CLIENT_FILE_PREFIX=alpha\n")
        result = self.generate(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.output / "alpha-mac.yaml").read_bytes(), before)

    def test_only_owned_unchanged_stale_files_are_deleted(self):
        self.generate()
        legacy = self.output / "alpha-old.yaml"
        legacy.write_text("unowned\n")
        self.add_conf("DEVICES=mac\n")
        self.assertNotEqual(self.generate("--check", success=False).returncode, 0)
        self.assertTrue((self.output / "alpha-phone.yaml").exists())
        self.generate()
        self.assertFalse((self.output / "alpha-phone.yaml").exists())
        self.assertEqual(legacy.read_text(), "unowned\n")

    def test_check_detects_drift_without_writing(self):
        result = self.generate("--check", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.generate()
        self.generate("--check")
        snapshot = {p.name: p.read_bytes() for p in self.output.iterdir()}
        self.add_conf("AI_STRICT_MODE=true\n")
        self.assertNotEqual(self.generate("--check", success=False).returncode, 0)
        self.assertEqual(snapshot, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_disabled_profile_does_not_recreate_or_change_outputs(self):
        self.add_conf("CLIENT_CONFIG_ENABLE=false\n")
        self.generate()
        self.generate("--check")
        self.assertFalse(self.output.exists())
        self.add_conf("CLIENT_CONFIG_ENABLE=true\n")
        self.generate()
        snapshot = {p.name: p.read_bytes() for p in self.output.iterdir()}
        self.add_conf("CLIENT_CONFIG_ENABLE=false\n")
        self.generate()
        self.assertEqual(snapshot, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_explicit_port_overrides_state_and_empty_reuses_state(self):
        self.add_conf("HY2_PORT=32000\n")
        self.run_secrets()
        self.assertEqual(load_kv(self.secrets)["HY2_PORT"], "32000")
        self.add_conf("HY2_PORT=\n")
        self.run_secrets()
        self.assertEqual(load_settings(self.state)["HY2_PORT"], "32000")

    def test_anytls_rotation_is_automatic_stable_and_never_logged(self):
        first = self.run_secrets()
        before = load_kv(self.secrets)["ANYTLS_PASS"]
        self.run_secrets()
        self.assertTrue(load_kv(self.secrets)["ANYTLS_PASS"] == before)
        self.add_conf("DEVICES=mac\n")
        result = self.run_secrets()
        after = load_kv(self.secrets)["ANYTLS_PASS"]
        self.assertTrue(after != before)
        self.assertNotIn(after, result.stdout + result.stderr)
        self.assertNotIn(before, first.stdout + first.stderr)
        self.run_secrets()
        self.assertTrue(load_kv(self.secrets)["ANYTLS_PASS"] == after)
        saved = load_kv(self.secrets)
        self.assertNotIn("REALITY_UUID_phone", saved)
        self.assertNotIn("HY2_PASS_phone", saved)
        self.add_conf("DEVICES=mac phone\n")
        self.run_secrets()
        self.assertNotEqual(load_kv(self.secrets)["HY2_PASS_phone"], "test-phone")

    def test_kv_values_are_literal_and_errors_do_not_expose_values(self):
        self.conf.write_text("DEVICES='mac phone' # devices\nHY2_PORT=32000 # configured\nX='$(touch /tmp/never-run-network-node)'\n")
        settings = load_settings(self.state)
        self.assertEqual(settings["DEVICES"], "mac phone")
        self.assertEqual(settings["HY2_PORT"], "32000")
        self.assertEqual(settings["X"], "$(touch /tmp/never-run-network-node)")
        self.conf.write_text("HY2_PASS_mac='DO-NOT-PRINT\n")
        with self.assertRaises(ValueError) as caught:
            load_kv(self.conf)
        self.assertNotIn("DO-NOT-PRINT", str(caught.exception))

    def test_preflight_rejects_invalid_config_before_secret_mutation(self):
        before = self.secrets.read_bytes()
        self.add_conf("HY2_ACME_ENABLE=true\n")
        result = subprocess.run(["bash", str(ROOT / "core/secrets.sh")], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.secrets.read_bytes(), before)
        for bad in ({"DEVICES": "phone-2"}, {"PRIVACY_MODE": "flase"}, {"HY2_PORT": "70000"},
                    {"HY2_PORT_RANGE": "40000-30000"}, {"HY2_HOP_INTERVAL": "15-30"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(bad)

    def test_saved_connection_does_not_override_cli_and_does_not_execute_values(self):
        marker = self.root / "should-not-exist"
        value = f"$(touch {marker})"
        (self.state / "connection.conf").write_text(f"VPS_SSH_PORT=2222\nVPS_ADMIN_USER=admin\nVPS_SSH_KEY='{value}'\n")
        script = f'''set -eu
VPS_SSH_PORT=3333
eval "$(python3 {ROOT / 'core/settings.py'} connection-shell {self.state})"
test "$VPS_SSH_PORT" = 3333
test "$VPS_ADMIN_USER" = admin
'''
        # Quote the source path because the real checkout may contain spaces.
        import shlex
        script = script.replace(str(ROOT / "core/settings.py"), shlex.quote(str(ROOT / "core/settings.py")))
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
