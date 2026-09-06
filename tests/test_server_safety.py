"""Exercise installer failure paths with fake commands and a temporary filesystem."""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class ServerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_shell(self, script, **env):
        return subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], cwd=self.root,
                              env=os.environ | env, capture_output=True, text=True)

    def test_download_checksum_cache_and_atomic_replacement(self):
        digest = hashlib.sha256(b"release").hexdigest()
        script = f"""
. {shlex.quote(str(ROOT / 'core/download.sh'))}
release_sha256() {{ printf '%s' {digest}; }}
download_file() {{ printf release > "$1"; printf download >> calls; }}
NETWORK_NODE_DOWNLOAD_CACHE="$PWD/cache"
download_release "$PWD/binary" ignored
download_release "$PWD/cached" ignored
test "$(cat calls)" = download
printf corrupt > "cache/{digest}"
download_release "$PWD/cached" ignored
test "$(cat calls)" = downloaddownload
printf old > installed
install_binary binary installed
test "$(cat installed)" = release
test "$(cat installed.previous)" = old
install_binary binary installed
test "$(cat installed.previous)" = old
unset NETWORK_NODE_DOWNLOAD_CACHE
download_file() {{ printf corrupt > "$1"; }}
if download_release "$PWD/rejected" ignored; then exit 90; fi
test ! -e rejected
test "$(cat installed)" = release
"""
        result = self.run_shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_running_cloudflared_without_connections_fails_readiness(self):
        source = (ROOT / 'core/setup-server.sh').read_text()
        start = source.index('if [ "${CDN_ENABLE:-false}" = "true" ]; then\n  echo "=== Waiting')
        fragment = source[start:source.index('\necho "=== [8/8]', start)]
        for connections in ('0', '2'):
            result = self.run_shell('''
sleep() { :; }
curl() { printf 'cloudflared_tunnel_ha_connections %s\n' "$CONNECTIONS"; }
''' + fragment, CDN_ENABLE='true', CONNECTIONS=connections)
            self.assertEqual(result.returncode == 0, connections == '2', result.stderr)

    def test_xray_staging_retains_json_extension_and_validation_precedes_replace(self):
        source = (ROOT / 'core/setup-server.sh').read_text()
        start = source.index('sudo install -o root -g xray -m 640')
        fragment = source[start:source.index('\nsudo mkdir -p /etc/hysteria', start)]
        fragment = fragment.replace('/usr/local/etc/xray', str(self.root / 'xray')).replace('/usr/local/bin/xray', 'mock_xray')
        (self.root / 'xray').mkdir()
        (self.root / 'install').mkdir()
        (self.root / 'install/xray-config.json').write_text('{"new": true}')
        target = self.root / 'xray/config.json'
        for valid in ('false', 'true'):
            target.write_text('{"old": true}')
            result = self.run_shell('''
sudo() { if [ "$1" = -u ]; then shift 2; fi; "$@"; }
install() { cp "$7" "$8"; }
mock_xray() {
  case "$4" in *.json) ;; *) return 2 ;; esac
  [ "$VALID" = true ]
}
''' + fragment, INSTALL_TMP=str(self.root / 'install'), VALID=valid)
            self.assertEqual(result.returncode == 0, valid == 'true', result.stderr)
            self.assertEqual(target.read_text(), '{"new": true}' if valid == 'true' else '{"old": true}')

    def firewall(self, **env):
        script = (ROOT / "providers/vps.sh").read_text().split("<<'REMOTE_FIREWALL'\n", 1)[1].split("\nREMOTE_FIREWALL", 1)[0]
        script = script.replace("/var/lib/network-node", str(self.root / "managed"))
        defaults = dict(SSH_PORT="2222", REALITY_PORT="443", HY2_PORT="31000", HY2_PORT_RANGE="32000-32010",
                        ANYTLS_PORT="21000", WARP_ENABLE="true", WARP_REALITY_PORT="41000", CDN_ONLY="false")
        return self.run_shell('sudo() { "$@"; }\nufw() { printf "%s\\n" "$*" >> "$PWD/ufw.log"; }\n' + script,
                              **(defaults | env))

    def test_firewall_opens_ssh_first_and_only_removes_managed_stale_ports(self):
        result = self.firewall()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = self.root / "managed/ufw-ports"
        self.assertIn("32000:32010/udp", previous.read_text())
        self.assertIn("41000/tcp", previous.read_text())
        (self.root / "ufw.log").write_text("")
        result = self.firewall(WARP_ENABLE="false", HY2_PORT_RANGE="", HY2_PORT="33000")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.root / "ufw.log").read_text()
        self.assertLess(log.index("allow 2222/tcp"), log.index("delete allow"))
        self.assertIn("delete allow 32000:32010/udp", log)
        self.assertIn("delete allow 41000/tcp", log)
        self.assertNotIn("reset", log)
        self.assertNotIn("delete allow 2222/tcp", log)

    def test_cdn_only_never_closes_ssh_on_a_former_proxy_port(self):
        result = self.firewall(SSH_PORT="443", CDN_ONLY="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.root / "ufw.log").read_text()
        self.assertNotIn("delete allow 443/tcp", log)
        self.assertEqual((self.root / "managed/ufw-ports").read_text(), "443/tcp\n")

    def ssh_hardening(self, mode):
        source = (ROOT / "core/setup-server.sh").read_text()
        script = source[source.index("sudo mkdir -p /etc/ssh/sshd_config.d"):source.index('\necho "=== Listening sockets ==="')]
        script = script.replace("/etc/ssh", str(self.root / "ssh")).replace("/usr/sbin/sshd", "mock_sshd")
        return self.run_shell('''
sudo() { "$@"; }
mock_sshd() {
  if [ "$1" = -t ]; then [ "$TEST_MODE" != syntax ]; return; fi
  [ "$TEST_MODE" != effective_error ] || return 1
  [ "$TEST_MODE" != ineffective ] || { printf 'passwordauthentication yes\n'; return; }
  printf 'passwordauthentication no\npermitrootlogin no\nkbdinteractiveauthentication no\npubkeyauthentication yes\n'
}
systemctl() { printf reload >> reload.log; [ "$TEST_MODE" != reload_failure ]; }
''' + script, INSTALL_TMP=str(self.root / "temp"), TEST_MODE=mode)

    def test_ssh_failure_restores_config_and_does_not_reload_invalid_config(self):
        (self.root / "ssh").mkdir()
        (self.root / "temp").mkdir()
        original = "PasswordAuthentication yes\n"
        config = self.root / "ssh/sshd_config"
        for mode in ("syntax", "ineffective", "effective_error", "reload_failure"):
            with self.subTest(mode=mode):
                config.write_text(original)
                (self.root / "reload.log").unlink(missing_ok=True)
                result = self.ssh_hardening(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(config.read_text(), original)
                self.assertFalse((self.root / "ssh/sshd_config.d/00-network-node.conf").exists())
                self.assertEqual((self.root / "reload.log").exists(), mode == "reload_failure")
        result = self.ssh_hardening("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(config.read_text().startswith("Include "))


if __name__ == "__main__":
    unittest.main()
