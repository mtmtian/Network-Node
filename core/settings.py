"""Shared, non-executing parser for local configuration and generated state."""
import argparse
import os
from pathlib import Path
import re
import shlex
import sys

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
DEVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,63}\Z")
GENERATED_OPTIONS = {"HY2_PORT", "ANYTLS_PORT", "WARP_REALITY_PORT", "CDN_WS_PATH"}
CONNECTION_KEYS = (
    "VPS_HOST", "VPS_SSH_PORT", "VPS_SSH_KEY", "VPS_ADMIN_USER",
    "VPS_BOOTSTRAP_USER", "VPS_SSH_INTERFACE",
)


def load_kv(path):
    """Read literal KEY=value; never evaluate shell expansions or commands."""
    path = Path(path)
    if not path.exists():
        return {}
    result = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, raw = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path.name}:{number}: 无效配置键（未显示内容）")
        try:
            result[key] = " ".join(shlex.split(raw, comments=True))
        except ValueError:
            raise ValueError(f"{path.name}:{number}: 引号未闭合（未显示内容）") from None
    return result


def load_settings(state_dir):
    state_dir = Path(state_dir)
    state = load_kv(state_dir / ".secrets.env")
    for key, value in load_kv(state_dir / "deploy.conf").items():
        if key in GENERATED_OPTIONS and not value and state.get(key):
            continue
        state[key] = value
    return state


def validate(settings, *, deployment=False):
    devices = settings.get("DEVICES", "mac iphone").split()
    if not devices or len(set(devices)) != len(devices):
        raise ValueError("DEVICES 不能为空或重复")
    if any(not DEVICE.fullmatch(device) for device in devices):
        raise ValueError("设备 ID 仅支持 1-64 位字母、数字、下划线；不支持点或连字符")
    if any(not DEVICE.fullmatch(device) for device in settings.get("ANYTLS_DEVICES", "").split()):
        raise ValueError("已保存的 AnyTLS 设备清单无效")
    for key in ("CLIENT_CONFIG_ENABLE", "CDN_ENABLE", "CDN_ONLY", "WARP_ENABLE", "PRIVACY_MODE",
                "AI_STRICT_MODE", "HY2_OBFS_ENABLE", "HY2_ACME_ENABLE"):
        if key in settings and settings[key] not in ("true", "false"):
            raise ValueError(f"{key} 只能为 true/false")
    for key in ("REALITY_PORT", "HY2_PORT", "ANYTLS_PORT", "WARP_REALITY_PORT", "WARP_SOCKS_PORT"):
        value = settings.get(key, "")
        if value and (not value.isdecimal() or not 1 <= int(value) <= 65535):
            raise ValueError(f"{key} 必须是 1-65535 的整数")
    tcp = [settings.get(key) for key in ("REALITY_PORT", "ANYTLS_PORT")]
    if settings.get("WARP_ENABLE") == "true":
        tcp += [settings.get("WARP_REALITY_PORT"), settings.get("WARP_SOCKS_PORT", "40000")]
    if settings.get("CDN_ENABLE") == "true":
        tcp += ['8080', '20241']  # Xray WS origin and cloudflared loopback metrics.
    tcp = [int(port) for port in tcp if port]
    if len(set(tcp)) != len(tcp):
        raise ValueError("TCP 监听端口不能重复")
    port_range = settings.get("HY2_PORT_RANGE", "")
    if port_range:
        match = re.fullmatch(r"(\d+)-(\d+)", port_range)
        if not match or not 1 <= int(match[1]) <= int(match[2]) <= 65535:
            raise ValueError("HY2_PORT_RANGE 必须是有效的起止范围，如 30000-30010")
    target = settings.get("CLIENT_TARGET", "stash")
    if settings.get('PROBE_INTERFACE') and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}', settings['PROBE_INTERFACE']):
        raise ValueError('PROBE_INTERFACE 必须是有效网卡名称，如 en0')
    if target not in ("stash", "mihomo"):
        raise ValueError("CLIENT_TARGET 只能为 stash/mihomo")
    hop = settings.get("HY2_HOP_INTERVAL", "")
    if hop:
        match = re.fullmatch(r"([1-9]\d*)(?:-([1-9]\d*))?", hop)
        if not match or (match[2] and int(match[1]) > int(match[2])):
            raise ValueError("HY2_HOP_INTERVAL 必须是正整数或递增范围")
        if target == "stash" and match[2]:
            raise ValueError("Stash 的 HY2_HOP_INTERVAL 需要整数秒；范围仅用于 CLIENT_TARGET=mihomo")
    for key in ("REALITY_SNI", "HY2_SNI", "HY2_ACME_DOMAIN", "CDN_HOSTNAME"):
        if settings.get(key) and not re.fullmatch(r"[A-Za-z0-9.-]+", settings[key]):
            raise ValueError(f"{key} 必须是域名或 IPv4 地址")
    if settings.get("CDN_TUNNEL_NAME") and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", settings["CDN_TUNNEL_NAME"]):
        raise ValueError("CDN_TUNNEL_NAME 仅支持 1-128 位字母、数字、下划线和连字符")
    if settings.get("CDN_WS_PATH") and not re.fullmatch(r"[A-Za-z0-9_./~-]+", settings["CDN_WS_PATH"]):
        raise ValueError("CDN_WS_PATH 只能包含 URL 路径字符，不支持空格、引号或查询参数")
    for key in ("HY2_UP", "HY2_DOWN"):
        if settings.get(key) and not re.fullmatch(r"\d+(?:\.\d+)?(?:\s*[kmg]?bps)?", settings[key], re.I):
            raise ValueError(f"{key} 必须是带宽值，如 30 mbps")
    if bool(settings.get("HY2_UP")) != bool(settings.get("HY2_DOWN")):
        raise ValueError("HY2_UP 与 HY2_DOWN 必须同时设置")
    if settings.get("CDN_ONLY") == "true":
        if settings.get("CDN_ENABLE") != "true":
            raise ValueError("CDN_ONLY=true 必须同时设置 CDN_ENABLE=true")
        if settings.get("WARP_ENABLE") == "true":
            raise ValueError("WARP_ENABLE=true 不能与 CDN_ONLY=true 同时使用")
    if deployment:
        if settings.get("CDN_ENABLE") == "true":
            required = ("CF_API_TOKEN", "CDN_HOSTNAME", "CDN_TUNNEL_NAME")
            if any(not settings.get(key) for key in required):
                raise ValueError("CDN 缺少 CF_API_TOKEN/CDN_HOSTNAME/CDN_TUNNEL_NAME")
        if settings.get("HY2_ACME_ENABLE") == "true":
            required = ("HY2_ACME_DOMAIN", "HY2_ACME_EMAIL", "HY2_ACME_DNS_TOKEN")
            if any(not settings.get(key) for key in required):
                raise ValueError("ACME 缺少域名、邮箱或 DNS token；已在修改服务器前停止")
            if settings.get("HY2_ACME_DNS_PROVIDER", "cloudflare") != "cloudflare":
                raise ValueError("ACME 当前仅支持 cloudflare DNS provider")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("conf-shell", "settings-shell", "validate", "connection-shell", "save-connection"))
    parser.add_argument("state_dir", type=Path)
    args = parser.parse_args()
    if args.action == "validate":
        validate(load_settings(args.state_dir), deployment=True)
        return
    if args.action == "save-connection":
        import tempfile
        path = args.state_dir / "connection.conf"
        with tempfile.NamedTemporaryFile(mode="w", dir=args.state_dir, delete=False) as handle:
            temporary = Path(handle.name)
            for key in CONNECTION_KEYS:
                handle.write(f"{key}={shlex.quote(os.environ.get(key, ''))}\n")
        temporary.chmod(0o600)
        temporary.replace(path)
        return
    if args.action == "connection-shell":
        data = load_kv(args.state_dir / "connection.conf")
        # Only fill absent CLI/environment options. Connection data is never executed.
        for key in CONNECTION_KEYS:
            if data.get(key):
                print(f"{key}=${{{key}:-{shlex.quote(data[key])}}}")
        return
    data = (load_kv(args.state_dir / "deploy.conf") if args.action == "conf-shell"
            else load_settings(args.state_dir))
    for key, value in data.items():
        print(f"export {key}={shlex.quote(value)}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        sys.exit(f"ERROR: {exc}")
