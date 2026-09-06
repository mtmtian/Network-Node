#!/usr/bin/env python3
"""Generate Stash-first, Mihomo-compatible YAML configs, one per device.

Reads deploy.conf (DEVICES, REALITY_PORT, REALITY_SNI, PROJECT_ID, REGION) and
.secrets.env (STATIC_IP, REALITY_PUBLIC, REALITY_SHORTID, HY2_PORT,
ANYTLS_PORT, ANYTLS_PASS, and per-device REALITY_UUID_<dev> / HY2_PASS_<dev>).

Reality/Hysteria2 use per-device credentials. AnyTLS uses one automatically
managed password per profile; removing a device rotates it during deployment.
Strict routing uses Reality/CDN only; daily routing also offers HY2/AnyTLS.
"""
import pathlib
import os
import re
import sys
import argparse
import hashlib
from settings import load_settings, validate
from client_output import write_outputs
from client_policy import adapt_config
from sensitive_policy import domain_rules, app_rules

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true", help="只检查输出是否与当前配置一致，不写文件")
parser.add_argument("--client", choices=("stash", "mihomo"), help="客户端目标，默认读取 CLIENT_TARGET/stash")
args = parser.parse_args()

ROOT = pathlib.Path(os.environ.get("NETWORK_NODE_ROOT", pathlib.Path(__file__).resolve().parent.parent))
PROFILE = os.environ.get("NETWORK_NODE_PROFILE", "").strip()
STATE_DIR = pathlib.Path(
    os.environ.get(
        "NETWORK_NODE_STATE_DIR",
        ROOT / "profiles" / PROFILE if PROFILE else ROOT,
    )
)
OUT_DIR = pathlib.Path(os.environ.get("NETWORK_NODE_CLIENTS_DIR", ROOT / "clash-configs"))


try:
    env = load_settings(STATE_DIR)
    if args.client:
        env["CLIENT_TARGET"] = args.client
    validate(env)
except (ValueError, OSError) as exc:
    sys.exit(f"ERROR: {exc}")
if env.get("CLIENT_CONFIG_ENABLE", "true") == "false":
    print("此 profile 已停用客户端配置输出，跳过生成和一致性检查")
    sys.exit(0)
CLIENT_TARGET = env.get("CLIENT_TARGET", "stash")
AI_STRICT_MODE = env.get("AI_STRICT_MODE", "false") == "true"
FILE_PREFIX = env.get("CLIENT_FILE_PREFIX", "").strip() or PROFILE

devices = env.get("DEVICES", "mac iphone").split()
safe_name = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
if not FILE_PREFIX or not safe_name.fullmatch(FILE_PREFIX):
    sys.exit(
        "ERROR: CLIENT_FILE_PREFIX（或 profile 名）只能包含 1-64 位字母、数字、点、下划线和连字符"
    )
if not devices or len(devices) != len(set(devices)):
    sys.exit("ERROR: DEVICES 不能为空或包含重复设备名")
unsafe_devices = [device for device in devices if not safe_name.fullmatch(device)]
if unsafe_devices:
    sys.exit(f"ERROR: DEVICES 包含不安全设备名 {unsafe_devices}")

# ── CDN 套娃出口（可选）──
# 启用条件：CDN_ENABLE=true 且 CF/WS 参数齐全。启用时把 US-CDN 作为一个普通节点
# 加入现有节点池（节点策略 / 自动测速 / 手动选择），分流规则完全不变；
# 关闭时所有 CDN 占位符为空，与历史行为完全一致（向后兼容）。
CDN_HOSTNAME = env.get("CDN_HOSTNAME", "")
CDN_WS_PATH = env.get("CDN_WS_PATH", "").lstrip("/")
CDN_ONLY = env.get("CDN_ONLY", "false") == "true"
cdn_on = env.get("CDN_ENABLE", "false") == "true" and bool(CDN_HOSTNAME) and bool(CDN_WS_PATH)
if CDN_ONLY and not cdn_on:
    sys.exit("ERROR: CDN_ONLY=true 但 CDN_ENABLE/CDN_HOSTNAME/CDN_WS_PATH 不完整")

WARP_ENABLE = env.get("WARP_ENABLE", "false") == "true"
WARP_REALITY_PORT = env.get("WARP_REALITY_PORT", "").strip()
PRIVACY_MODE = env.get("PRIVACY_MODE", "false") == "true"
if WARP_ENABLE and CDN_ONLY:
    sys.exit("ERROR: WARP_ENABLE=true 不能与 CDN_ONLY=true 同时使用（会重新暴露 VPS 入口）")

required = ["DEVICES"]
if not CDN_ONLY:
    required += [
        "STATIC_IP",
        "REALITY_PORT", "REALITY_PUBLIC", "REALITY_SHORTID",
        "HY2_PORT",
        "ANYTLS_PORT", "ANYTLS_PASS",
    ]
else:
    required += ["CDN_HOSTNAME", "CDN_WS_PATH"]
if WARP_ENABLE:
    required.append("WARP_REALITY_PORT")
missing = [k for k in required if not env.get(k)]
if missing:
    sys.exit(f"ERROR: 缺少必要变量 {missing}（应由部署入口自动生成，请检查 profile 状态）")
for device in devices:
    if not CDN_ONLY and (
        not env.get(f"REALITY_UUID_{device}") or not env.get(f"HY2_PASS_{device}")
    ):
        sys.exit(
            f"ERROR: 设备 {device} 缺少 REALITY_UUID_{device} / HY2_PASS_{device}"
        )
    if cdn_on and not env.get(f"CDN_UUID_{device}"):
        sys.exit(f"ERROR: CDN_ENABLE=true 但设备 {device} 缺少 CDN_UUID_{device}")
    if WARP_ENABLE and not env.get(f"WARP_REALITY_UUID_{device}"):
        sys.exit(
            f"ERROR: WARP_ENABLE=true 但设备 {device} 缺少 WARP_REALITY_UUID_{device}"
        )

HY2_PORT_RANGE = env.get("HY2_PORT_RANGE", "").strip()
HY2_HOP_INTERVAL = env.get("HY2_HOP_INTERVAL", "").strip()
HY2_SNI = env.get("HY2_SNI", "www.bing.com").strip() or "www.bing.com"
HY2_ACME_ENABLE = env.get("HY2_ACME_ENABLE", "false") == "true"
HY2_ACME_DOMAIN = env.get("HY2_ACME_DOMAIN", "").strip()
if HY2_ACME_ENABLE and not HY2_ACME_DOMAIN:
    sys.exit("ERROR: HY2_ACME_ENABLE=true 但缺少 HY2_ACME_DOMAIN")
HY2_CLIENT_SNI = HY2_ACME_DOMAIN if HY2_ACME_ENABLE else HY2_SNI
HY2_SKIP_CERT_VERIFY = "false" if HY2_ACME_ENABLE else "true"
HY2_CERT_SHA256 = env.get("HY2_CERT_SHA256", "").replace(":", "").lower()
if HY2_CERT_SHA256 and not re.fullmatch(r"[0-9a-f]{64}", HY2_CERT_SHA256):
    sys.exit("ERROR: HY2_CERT_SHA256 必须是 64 位 SHA256 指纹")
HY2_PIN = ""
if not HY2_ACME_ENABLE and HY2_CERT_SHA256:
    pin_field = "server-cert-fingerprint" if CLIENT_TARGET == "stash" else "fingerprint"
    HY2_PIN = f'    {pin_field}: "{HY2_CERT_SHA256}"\n'
HY2_OBFS_ENABLE = env.get("HY2_OBFS_ENABLE", "false") == "true"
HY2_OBFS_PASSWORD = env.get("HY2_OBFS_PASSWORD", "").strip()
if HY2_OBFS_ENABLE and not HY2_OBFS_PASSWORD:
    sys.exit("ERROR: HY2_OBFS_ENABLE=true 但缺少 HY2_OBFS_PASSWORD")
CDN_REF = '\n      - "US-CDN"' if cdn_on else ""

# ── Hysteria2 Brutal 拥塞控制（可选）──
# 只有同时设置 HY2_UP / HY2_DOWN 才注入 up/down，激活 Brutal（无视丢包按固定带宽发送），
# 这是 Hysteria2 在跨太平洋丢包链路上提速的核心。值必须填你实测速度的 ~80%——填太高会
# 自伤丢包反而更慢。留空 = 保持 Hysteria2 默认动态 CC（向后兼容，与历史行为一致）。
HY2_UP = env.get("HY2_UP", "").strip()
HY2_DOWN = env.get("HY2_DOWN", "").strip()
HY2_BW = f'    up: "{HY2_UP}"\n    down: "{HY2_DOWN}"\n' if HY2_UP and HY2_DOWN else ""
if CLIENT_TARGET == "stash" and HY2_UP and HY2_DOWN:
    def mbps(value):
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmg]?bps)?", value, re.I)
        return float(match[1]) * {None: 1, "bps": 0.000001, "kbps": 0.001, "mbps": 1, "gbps": 1000}[match[2].lower() if match[2] else None]
    HY2_BW = f"    up-speed: {mbps(HY2_UP):g}\n    down-speed: {mbps(HY2_DOWN):g}\n"


def cdn_proxy_block(dev_cdn_uuid):
    """US-CDN 节点（VLESS+WS+TLS，经 Cloudflare）。CDN 关闭时返回空串。"""
    if not cdn_on:
        return ""
    return (
        '  - name: "US-CDN"\n'
        "    type: vless\n"
        f"    server: {CDN_HOSTNAME}\n"
        "    port: 443\n"
        f"    uuid: {dev_cdn_uuid}\n"
        "    network: ws\n"
        "    tls: true\n"
        "    udp: true\n"
        f"    servername: {CDN_HOSTNAME}\n"
        f"    sni: {CDN_HOSTNAME}\n"
        "    client-fingerprint: chrome\n"
        "    ws-opts:\n"
        f'      path: "/{CDN_WS_PATH}"\n'
        "      headers:\n"
        f"        Host: {CDN_HOSTNAME}\n"
    )


def warp_reality_proxy_block(dev_warp_uuid):
    """US-Reality-WARP: direct Reality ingress, WARP-only server egress."""
    if not WARP_ENABLE:
        return ""
    return f'''  - name: "US-Reality-WARP"
    type: vless
    server: {env['STATIC_IP']}
    port: {WARP_REALITY_PORT}
    uuid: {dev_warp_uuid}
    network: tcp
    tls: true
    udp: true
    flow: xtls-rprx-vision
    servername: "{env.get('REALITY_SNI', '')}"
    sni: "{env.get('REALITY_SNI', '')}"
    client-fingerprint: chrome
    reality-opts:
      public-key: {env['REALITY_PUBLIC']}
      short-id: "{env['REALITY_SHORTID']}"
'''


def node_ref_block(names):
    return "\n".join(f'      - "{name}"' for name in names)


def direct_proxy_blocks(dev_uuid, hy2_password):
    if CDN_ONLY:
        return "", "", ""

    hy2_port = (
        f"    ports: {HY2_PORT_RANGE}\n"
        if HY2_PORT_RANGE
        else f"    port: {env['HY2_PORT']}\n"
    )
    hy2_hop = f"    hop-interval: {HY2_HOP_INTERVAL}\n" if HY2_HOP_INTERVAL else ""
    hy2_obfs = ""
    if HY2_OBFS_ENABLE:
        hy2_obfs = (
            "    obfs: salamander\n"
            f"    obfs-password: {HY2_OBFS_PASSWORD}\n"
        )

    reality = f'''  - name: "US-Reality"
    type: vless
    server: {env['STATIC_IP']}
    port: {env['REALITY_PORT']}
    uuid: {dev_uuid}
    network: tcp
    tls: true
    udp: true
    flow: xtls-rprx-vision
    servername: "{env.get('REALITY_SNI', '')}"
    sni: "{env.get('REALITY_SNI', '')}"
    client-fingerprint: chrome
    reality-opts:
      public-key: {env['REALITY_PUBLIC']}
      short-id: "{env['REALITY_SHORTID']}"
'''
    hy2 = f'''  - name: "US-HY2"
    type: hysteria2
    server: {env['STATIC_IP']}
{hy2_port}    password: "{hy2_password}"
    sni: {HY2_CLIENT_SNI}
    skip-cert-verify: {HY2_SKIP_CERT_VERIFY}
    alpn:
      - h3
{HY2_PIN}{HY2_BW}{hy2_hop}{hy2_obfs}'''
    if CLIENT_TARGET == "stash":
        hy2 = hy2.replace("    password:", "    auth:")
    anytls = f'''  - name: "US-AnyTLS"
    type: anytls
    server: {env['STATIC_IP']}
    port: {env['ANYTLS_PORT']}
    password: "{env['ANYTLS_PASS']}"
    sni: {HY2_SNI}
    skip-cert-verify: true
    client-fingerprint: chrome
    udp: true
'''
    return reality, hy2, anytls

TEMPLATE_PATH = pathlib.Path(__file__).with_name("client.yaml.tmpl")
TEMPLATE = TEMPLATE_PATH.read_text()


rendered = {}
template_revision = hashlib.sha256(
    pathlib.Path(__file__).read_bytes() + TEMPLATE_PATH.read_bytes()
    + pathlib.Path(__file__).with_name("settings.py").read_bytes()
    + pathlib.Path(__file__).with_name("client_policy.py").read_bytes()
    + pathlib.Path(__file__).with_name("sensitive_policy.py").read_bytes()
    + pathlib.Path(__file__).with_name("sensitive-services.json").read_bytes()
).hexdigest()[:12]
for dev in devices:
    uuid = env.get(f"REALITY_UUID_{dev}")
    hy2pw = env.get(f"HY2_PASS_{dev}")
    dev_cdn_uuid = env.get(f"CDN_UUID_{dev}", "")
    dev_warp_uuid = env.get(f"WARP_REALITY_UUID_{dev}", "")

    reality_proxy, hy2_proxy, anytls_proxy = direct_proxy_blocks(
        uuid or "", f"{dev}:{hy2pw}" if hy2pw else ""
    )
    warp_proxy = warp_reality_proxy_block(dev_warp_uuid)
    direct_nodes = [] if CDN_ONLY else ["US-Reality", "US-HY2", "US-AnyTLS"]
    warp_nodes = ["US-Reality-WARP"] if WARP_ENABLE else []
    ai_nodes = ["US-CDN"] if CDN_ONLY else ["US-Reality"]
    if cdn_on and not CDN_ONLY:
        ai_nodes.append("US-CDN")
    cn_policy_options = (
        '      - "🌐 代理流量"\n      - DIRECT'
        if PRIVACY_MODE
        else '      - DIRECT\n      - "🌐 代理流量"'
    )
    fallback_nodes = direct_nodes[:1]
    if cdn_on:
        fallback_nodes.append("US-CDN")
    fallback_nodes.extend(direct_nodes[1:])
    auto_nodes = fallback_nodes
    all_nodes = (["US-CDN"] if cdn_on else []) + direct_nodes + warp_nodes
    if not fallback_nodes:
        sys.exit("ERROR: 没有可用的代理节点")

    yaml = TEMPLATE.format(
        DEVICE=dev,
        PROFILE_OWNER=PROFILE or FILE_PREFIX,
        TARGET_LABEL=CLIENT_TARGET,
        STRICT_LABEL=str(AI_STRICT_MODE).lower(),
        TEMPLATE_REVISION=template_revision,
        SENSITIVE_RULES=domain_rules("🤖 AI 隐私出口"),
        APP_RULES=app_rules(CLIENT_TARGET, dev, "🤖 AI 隐私出口"),
        DNS_FOLLOW_RULE="  follow-rule: true" if CLIENT_TARGET == "stash" else "  respect-rules: true",
        STUN_PROTOCOL_RULE="  - PROTOCOL,STUN,🤖 AI 隐私出口" if CLIENT_TARGET == "stash" else "",
        SERVER_LABEL=(
            f"{env['STATIC_IP']} | primary: VLESS+Reality:{env['REALITY_PORT']} | "
            f"{'reserved' if AI_STRICT_MODE else 'fallback'}: Hysteria2:{env['HY2_PORT']}/udp, AnyTLS:{env['ANYTLS_PORT']}/tcp"
            if not CDN_ONLY
            else "Cloudflare Tunnel only"
        ),
        REALITY_PROXY=reality_proxy,
        HY2_PROXY=hy2_proxy,
        ANYTLS_PROXY=anytls_proxy,
        WARP_PROXY=warp_proxy,
        CDN_PROXY=cdn_proxy_block(dev_cdn_uuid),
        CDN_REF=CDN_REF,
        AI_PROXIES=node_ref_block(ai_nodes),
        CN_POLICY_OPTIONS=cn_policy_options,
        FALLBACK_PROXIES=node_ref_block(fallback_nodes),
        AUTO_PROXIES=node_ref_block(auto_nodes),
        MANUAL_PROXIES=node_ref_block(all_nodes),
        ALL_PROXIES=node_ref_block(all_nodes),
        **env,
    )
    yaml = adapt_config(yaml, CLIENT_TARGET, AI_STRICT_MODE, ai_nodes)
    filename = f"{FILE_PREFIX}-{dev}.yaml" if FILE_PREFIX else f"{dev}.yaml"
    rendered[OUT_DIR / filename] = yaml

try:
    current = write_outputs(OUT_DIR, PROFILE or FILE_PREFIX, rendered, check=args.check)
except (ValueError, OSError) as exc:
    sys.exit(f"ERROR: {exc}")
if args.check:
    print("配置与当前源一致" if current else "配置缺失或已过期；请运行 render")
    sys.exit(0 if current else 1)
print(f"全部 {len(devices)} 份 {CLIENT_TARGET} 配置已写入 {OUT_DIR}；AI 严格模式={AI_STRICT_MODE}")
