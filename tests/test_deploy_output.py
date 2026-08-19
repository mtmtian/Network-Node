#!/usr/bin/env python3
import pathlib
import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


class DeployOutputTest(unittest.TestCase):
    def test_vps_help_documents_one_command_migration(self):
        result = subprocess.run(
            ["bash", str(PROJECT_ROOT / "deploy-vps.sh"), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--copy-config-from", result.stdout)
        self.assertIn("--check-only", result.stdout)
        self.assertIn("--install-key", result.stdout)

    def test_vps_entrypoint_requires_explicit_profile(self):
        result = subprocess.run(
            ["bash", str(PROJECT_ROOT / "deploy-vps.sh")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VPS_PROFILE", result.stderr)

    def test_vps_check_only_uses_flags_without_creating_profile_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_ssh = fake_bin / "ssh"
            fake_ssh.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in *mt@*) exit 1 ;; esac\n"
                "printf 'Debian GNU/Linux 12|x86_64'\n"
            )
            fake_ssh.chmod(0o755)
            private_key = root / "id_ed25519"
            private_key.write_text("test-only-placeholder\n")
            state = root / "state"
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["NETWORK_NODE_STATE_DIR"] = str(state)
            result = subprocess.run(
                [
                    "bash",
                    str(PROJECT_ROOT / "deploy-vps.sh"),
                    "--profile",
                    "cstone-next",
                    "--host",
                    "198.51.100.10",
                    "--ssh-key",
                    str(private_key),
                    "--check-only",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("readiness 检查通过", result.stdout)
            self.assertFalse(state.exists())

    def test_vps_check_only_preserves_remote_readiness_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_ssh = fake_bin / "ssh"
            fake_ssh.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in *mt@*) exit 1 ;; esac\n"
                "printf '只支持 Debian/Ubuntu，当前为 alpine\\n' >&2\n"
                "exit 42\n"
            )
            fake_ssh.chmod(0o755)
            private_key = root / "id_ed25519"
            private_key.write_text("test-only-placeholder\n")
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            result = subprocess.run(
                [
                    "bash",
                    str(PROJECT_ROOT / "deploy-vps.sh"),
                    "--profile",
                    "cstone-next",
                    "--host",
                    "198.51.100.10",
                    "--ssh-key",
                    str(private_key),
                    "--check-only",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("当前为 alpine", result.stderr)

    def test_check_only_rejects_interactive_key_install(self):
        result = subprocess.run(
            [
                "bash",
                str(PROJECT_ROOT / "deploy-vps.sh"),
                "--profile",
                "cstone-next",
                "--host",
                "198.51.100.10",
                "--check-only",
                "--install-key",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("不能同时使用", result.stderr)

    def test_reality_client_password_is_redacted_from_logs(self):
        command = (
            f'. "{PROJECT_ROOT / "core" / "common.sh"}"; '
            f'. "{PROJECT_ROOT / "core" / "deploy.sh"}"; '
            "printf 'before\\nREALITY_PUBLIC_KEY=client-secret\\nafter\\n' | redact_server_output"
        )
        result = subprocess.run(
            ["bash", "-c", command],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "before\nREALITY_PUBLIC_KEY=[redacted]\nafter\n",
        )
        self.assertNotIn("client-secret", result.stdout)

    def test_vps_profile_is_passed_to_secret_generation_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            shutil.copytree(PROJECT_ROOT / "core", root / "core")
            shutil.copytree(PROJECT_ROOT / "config", root / "config")
            command = textwrap.dedent(
                f"""
                set -euo pipefail
                PROJECT_DIR='{root}'
                PROFILE_NAME=frantech
                NETWORK_NODE_STATE_DIR='{root / 'state'}'
                . \"$PROJECT_DIR/core/common.sh\"
                . \"$PROJECT_DIR/core/deploy.sh\"
                PROVIDER_TITLE='Test VPS'
                PROVIDER_DESCRIPTION='provider=test'
                provider_init() {{ :; }}
                provider_preflight() {{ :; }}
                provider_configure() {{
                    mkdir -p \"$STATE_DIR\"
                    cp \"$PROJECT_DIR/config/deploy.conf.example\" \"$CONF_FILE\"
                }}
                provider_provision() {{ setkv STATIC_IP 203.0.113.10; }}
                provider_install() {{ printf 'REALITY_PUBLIC_KEY=test-public-key\\n'; }}
                provider_print_summary() {{ :; }}
                output=\"$(run_deploy)\"
                printf '%s\\n' \"$output\"
                test -f \"$STATE_DIR/.secrets.env\"
                test ! -e \"$PROJECT_DIR/profiles/gcloud/.secrets.env\"
                test -f \"$PROJECT_DIR/clash-configs/frantech-mac.yaml\"
                test -f \"$PROJECT_DIR/clash-configs/frantech-iphone.yaml\"
                grep -F '配置文件  : {root}/clash-configs/frantech-*.yaml' <<<\"$output\" >/dev/null
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_vps_provider_copies_only_non_secret_config_for_new_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source_state = root / "profiles" / "cstone"
            source_state.mkdir(parents=True)
            (source_state / "deploy.conf").write_text(
                "PROJECT_ID=vps\nDEVICES=mac\nREALITY_PORT=443\n"
            )
            (source_state / ".secrets.env").write_text("DO_NOT_COPY=secret\n")
            command = textwrap.dedent(
                f"""
                set -euo pipefail
                PROJECT_DIR={shlex.quote(str(root))}
                PROFILE_NAME=cstone-next
                VPS_CONFIG_FROM_PROFILE=cstone
                VPS_HOST=203.0.113.10
                mkdir -p "$PROJECT_DIR/core" "$PROJECT_DIR/providers" "$PROJECT_DIR/config"
                cp {shlex.quote(str(PROJECT_ROOT / 'core' / 'common.sh'))} "$PROJECT_DIR/core/common.sh"
                cp {shlex.quote(str(PROJECT_ROOT / 'providers' / 'vps.sh'))} "$PROJECT_DIR/providers/vps.sh"
                cp {shlex.quote(str(PROJECT_ROOT / 'config' / 'deploy.conf.example'))} "$PROJECT_DIR/config/deploy.conf.example"
                . "$PROJECT_DIR/core/common.sh"
                . "$PROJECT_DIR/providers/vps.sh"
                provider_configure >/dev/null
                cmp "$PROJECT_DIR/profiles/cstone/deploy.conf" "$CONF_FILE"
                test ! -e "$STATE_DIR/.secrets.env"
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_readiness_runs_before_profile_state_is_created(self):
        deploy = (PROJECT_ROOT / "core" / "deploy.sh").read_text()
        self.assertLess(
            deploy.index("    provider_readiness\n"),
            deploy.index("  provider_configure\n"),
        )

    def test_server_install_fails_when_a_required_service_is_inactive(self):
        setup = (PROJECT_ROOT / "core" / "setup-server.sh").read_text()
        self.assertIn('systemctl is-active --quiet "$service"', setup)
        self.assertIn('echo "服务启动失败：$service"', setup)

    def test_server_env_quotes_special_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            state = root / "state"
            state.mkdir()
            command = textwrap.dedent(
                f"""
                set -euo pipefail
                PROJECT_DIR={shlex.quote(str(PROJECT_ROOT))}
                PROFILE_NAME=test
                NETWORK_NODE_STATE_DIR={shlex.quote(str(state))}
                . "$PROJECT_DIR/core/common.sh"
                . "$PROJECT_DIR/core/deploy.sh"
                DEVICES=mac
                setkv ANYTLS_PASS "a'b\\$c"
                target={shlex.quote(str(root / 'server-env.sh'))}
                build_server_env "$target"
                expected="a'b\\$c"
                . "$target"
                test "$ANYTLS_PASS" = "$expected"
                """
            )
            shutil.copy(PROJECT_ROOT / "core" / "common.sh", root / "common.sh")
            shutil.copy(PROJECT_ROOT / "core" / "deploy.sh", root / "deploy.sh")
            result = subprocess.run(
                ["bash", "-c", command],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_server_env_includes_optional_warp_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            state = root / "state"
            state.mkdir()
            command = textwrap.dedent(
                f"""
                set -euo pipefail
                PROJECT_DIR={shlex.quote(str(PROJECT_ROOT))}
                PROFILE_NAME=test
                NETWORK_NODE_STATE_DIR={shlex.quote(str(state))}
                . "$PROJECT_DIR/core/common.sh"
                . "$PROJECT_DIR/core/deploy.sh"
                DEVICES=mac
                WARP_ENABLE=true
                WARP_SOCKS_PORT=40000
                setkv WARP_REALITY_PORT 42000
                setkv WARP_REALITY_UUID_mac 00000000-0000-4000-8000-000000000004
                target={shlex.quote(str(root / 'server-env.sh'))}
                build_server_env "$target"
                unset WARP_ENABLE WARP_SOCKS_PORT WARP_REALITY_PORT WARP_REALITY_UUID_mac
                . "$target"
                test "$WARP_ENABLE" = true
                test "$WARP_SOCKS_PORT" = 40000
                test "$WARP_REALITY_PORT" = 42000
                test "$WARP_REALITY_UUID_mac" = 00000000-0000-4000-8000-000000000004
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_secret_generation_creates_warp_credentials_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            state = root / "state"
            state.mkdir()
            (state / "deploy.conf").write_text("DEVICES=mac\nWARP_ENABLE=true\n")
            env = os.environ.copy()
            env["PROJECT_DIR"] = str(PROJECT_ROOT)
            env["PROFILE_NAME"] = "test"
            env["NETWORK_NODE_STATE_DIR"] = str(state)
            result = subprocess.run(
                ["bash", str(PROJECT_ROOT / "core" / "secrets.sh")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            secrets = (state / ".secrets.env").read_text()
            self.assertRegex(secrets, r"(?m)^WARP_REALITY_PORT=4[0-9]{4}$")
            self.assertRegex(
                secrets,
                r"(?m)^WARP_REALITY_UUID_mac=[0-9a-f-]{36}$",
            )

    def test_server_setup_contains_opt_in_warp_outbound_contract(self):
        setup = (PROJECT_ROOT / "core" / "setup-server.sh").read_text()
        self.assertIn("warp-cli --accept-tos mode proxy", setup)
        self.assertIn("warp-outbound", setup)
        self.assertIn('"inboundTag": ["warp-reality"]', setup)

    def test_cdn_setup_runs_with_active_profile_before_host_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            shutil.copytree(PROJECT_ROOT / "core", root / "core")
            shutil.copytree(PROJECT_ROOT / "config", root / "config")
            fake_cf = root / "core" / "cloudflare.sh"
            fake_cf.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s' \"$PROFILE_NAME\" > \"$NETWORK_NODE_STATE_DIR/cf-profile\"\n"
                "printf 'CF_TUNNEL_TOKEN=test-tunnel\\n' >> \"$NETWORK_NODE_STATE_DIR/.secrets.env\"\n"
            )
            fake_cf.chmod(0o755)
            command = textwrap.dedent(
                f"""
                set -euo pipefail
                PROJECT_DIR={shlex.quote(str(root))}
                PROFILE_NAME=cdn-test
                NETWORK_NODE_STATE_DIR={shlex.quote(str(root / 'state'))}
                . "$PROJECT_DIR/core/common.sh"
                . "$PROJECT_DIR/core/deploy.sh"
                PROVIDER_TITLE='Test CDN'
                PROVIDER_DESCRIPTION='provider=test'
                provider_init() {{ :; }}
                provider_preflight() {{ :; }}
                provider_configure() {{
                    mkdir -p "$STATE_DIR"
                    cat > "$CONF_FILE" <<'EOF'
DEVICES="mac"
REALITY_TARGET=1.1.1.1:443
REALITY_SNI=
REALITY_PORT=443
CDN_ENABLE=true
CDN_ONLY=false
CDN_HOSTNAME=cdn.example.com
CDN_TUNNEL_NAME=cdn-test
EOF
                    printf 'CF_API_TOKEN=test-api-token\\n' > "$SECRETS_FILE"
                }}
                provider_provision() {{
                    test "$(cat \"$STATE_DIR/cf-profile\")" = "$PROFILE_NAME"
                    setkv STATIC_IP 203.0.113.10
                }}
                provider_install() {{ printf 'REALITY_PUBLIC_KEY=test-public-key\\n'; }}
                provider_print_summary() {{ :; }}
                run_deploy >/dev/null
                test -f "$STATE_DIR/cf-profile"
                test -f "$PROJECT_DIR/clash-configs/cdn-test-mac.yaml"
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
