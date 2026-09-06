"""Compose only our own generated node blocks with the shared daily rules.

Source YAML is rendered afresh in a private temporary directory, never read from
distribution copies. This is a section composer, not a general YAML parser.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from client_output import write_outputs
from client_policy import adapt_config
from profile_lock import profile_lock
from settings import DEVICE, NAME, load_settings, validate

CORE = Path(__file__).resolve().parent
AI = '🤖 AI / Meta 服务'
SENSITIVE = '🛡 敏感服务'
AUTO = '⚡ 自动测速'
MANUAL = '🔧 手动选择'
OVERSEAS = '🌐 海外流量'
CN = '🇨🇳 国内流量'
APPLE = '🍎 Apple 基础服务'
ADS = '🛑 屏蔽流量'
META_DOMAINS = ('facebook.com', 'facebook.net', 'fb.com', 'fb.me', 'fbcdn.net',
                'fbsbx.com', 'instagram.com', 'cdninstagram.com', 'whatsapp.com',
                'whatsapp.net', 'wa.me', 'messenger.com', 'meta.com', 'meta.ai')
DNS = {
    AI: ('1.1.1.1', '1.0.0.1'),
    OVERSEAS: ('9.9.9.9', '149.112.112.112'),
    CN: ('223.5.5.5', '120.53.53.53'),
}


def quote(value):
    return json.dumps(value, ensure_ascii=False)


def load_plan(root, profile):
    if not NAME.fullmatch(profile):
        raise ValueError('汇总 profile 名称无效')
    path = root / 'profiles' / profile / 'aggregate.json'
    try:
        plan = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError('无法读取汇总 profile 的 aggregate.json（未显示内容）') from None
    if not isinstance(plan, dict) or set(plan) != {'sources', 'sensitive', 'devices', 'client'}:
        raise ValueError('aggregate.json 需要 sources、sensitive、devices、client 四个字段')
    if plan['client'] not in ('stash', 'mihomo'):
        raise ValueError('client 必须为 stash/mihomo')
    devices = plan['devices']
    if (not isinstance(devices, list) or not devices
            or any(not isinstance(d, str) or not DEVICE.fullmatch(d) for d in devices)
            or len(devices) != len(set(devices))):
        raise ValueError('devices 必须是非空且不重复的有效设备名列表')
    sources = plan['sources']
    if not isinstance(sources, list) or not sources:
        raise ValueError('sources 不能为空')
    names, profiles = set(), set()
    for source in sources:
        if (not isinstance(source, dict) or set(source) != {'profile', 'name'}
                or any(not isinstance(v, str) or not NAME.fullmatch(v) for v in source.values())):
            raise ValueError('每个 source 需要有效的 profile 和 name')
        if source['name'] in names or source['profile'] in profiles or source['profile'] == profile:
            raise ValueError('source 别名/profile 不得重复，也不能引用汇总 profile 自身')
        names.add(source['name'])
        profiles.add(source['profile'])
    sensitive = plan['sensitive']
    if (not isinstance(sensitive, list) or not sensitive
            or any(not isinstance(n, str) or '/' not in n or n.split('/')[0] not in names
                   or n.split('/', 1)[1] not in ('Reality', 'CDN') for n in sensitive)
            or len(set(sensitive)) != len(sensitive)):
        raise ValueError('sensitive 必须按优先顺序列出 source 别名/Reality 或 source 别名/CDN')
    return plan


def node_blocks(text, alias):
    """Accept only the generator's known section and node-name contract."""
    try:
        section = text.split('\nproxies:\n', 1)[1].split('\nproxy-groups:\n', 1)[0]
    except IndexError:
        raise ValueError('节点生成器输出结构改变，已停止汇总') from None
    matches = list(re.finditer(r'^  - name: "US-([A-Za-z0-9-]+)"\n', section, re.M))
    if not matches or section[:matches[0].start()].strip():
        raise ValueError('节点生成器未提供可识别节点')
    result = {}
    for i, match in enumerate(matches):
        protocol = match[1]
        if protocol not in ('Reality', 'HY2', 'AnyTLS', 'CDN', 'Reality-WARP'):
            raise ValueError('节点类型尚未纳入汇总策略')
        name = f'{alias}/{protocol}'
        if name in result:
            raise ValueError('生成器返回重复节点名称')
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        body = section[match.end():end].rstrip()
        result[name] = f'  - name: {quote(name)}\n{body}\n'
    return result


def collect_nodes(root, plan, target):
    nodes = {device: {} for device in plan['devices']}
    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='network-node-aggregate-') as tmp:
        sources = []
        # Match the GCP deployment/address-operation lock; fail instead of reading
        # a partially changed profile. Hold all locks until every source is read.
        for source in sorted(plan['sources'], key=lambda s: s['profile']):
            state = root / 'profiles' / source['profile']
            if not (state / 'deploy.conf').is_file():
                raise ValueError(f"源 profile {source['profile']} 不存在")
            stack.enter_context(profile_lock(state))
        for source in plan['sources']:
            state = root / 'profiles' / source['profile']
            settings = load_settings(state)
            settings['CLIENT_TARGET'] = target
            validate(settings)
            if settings.get('CLIENT_CONFIG_ENABLE', 'true') == 'false':
                continue
            fingerprint = tuple((state / name).read_bytes() for name in ('deploy.conf', '.secrets.env'))
            directory = Path(tmp) / source['name']
            env = os.environ | {
                'NETWORK_NODE_ROOT': str(root), 'NETWORK_NODE_STATE_DIR': str(state),
                'NETWORK_NODE_PROFILE': source['profile'], 'NETWORK_NODE_CLIENTS_DIR': str(directory),
            }
            try:
                run = subprocess.run([sys.executable, str(CORE / 'gen-clash.py'), '--client', target],
                                     env=env, capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                raise ValueError(f"源 profile {source['profile']} 生成超时；已保留旧汇总文件") from None
            if run.returncode:
                # Never relay unexpected generator tracebacks containing local state.
                raise ValueError(f"源 profile {source['profile']} 生成失败；请用 node.py validate 检查")
            prefix = settings.get('CLIENT_FILE_PREFIX', '').strip() or source['profile']
            for device in set(settings.get('DEVICES', 'mac iphone').split()) & nodes.keys():
                text = (directory / f'{prefix}-{device}.yaml').read_text()
                nodes[device].update(node_blocks(text, source['name']))
            sources.append((state, fingerprint))
        for state, fingerprint in sources:
            if fingerprint != tuple((state / name).read_bytes() for name in ('deploy.conf', '.secrets.env')):
                raise ValueError('源 profile 在生成期间发生变化，请重新汇总')
    for device, available in nodes.items():
        if not available or any(name not in available for name in plan['sensitive']):
            raise ValueError(f'{device} 缺少指定的敏感服务主线/备用线，已保留旧汇总文件')
    return nodes


def group(name, kind, proxies, target):
    if not proxies:
        raise ValueError('禁止生成空策略组，避免客户端将它视为直连')
    text = f'  - name: {quote(name)}\n    type: {kind}\n'
    if kind != 'select':
        text += f'    interval: {60 if kind == "fallback" else 300}\n    lazy: false\n'
        if target == 'mihomo':
            text += '    url: https://www.gstatic.com/generate_204\n'
            if kind == 'url-test':
                text += '    tolerance: 50\n'
    return text + '    proxies:\n' + ''.join(f'      - {quote(n)}\n' for n in proxies) + '\n'


def groups(nodes, sensitive, target):
    auto = [name for name in nodes if not name.endswith('/Reality-WARP')]
    selections = [(AI, [SENSITIVE, MANUAL]),
                  (OVERSEAS, [AUTO, MANUAL]), (CN, ['DIRECT', AUTO, MANUAL]),
                  (APPLE, ['DIRECT', AUTO, MANUAL]),
                  (ADS, ['REJECT', AUTO, MANUAL, 'DIRECT'])]
    return ('proxy-groups:\n' + ''.join(group(n, 'select', options, target) for n, options in selections)
            + group(SENSITIVE, 'fallback', sensitive, target)
            + group(AUTO, 'url-test', auto, target)
            + group(MANUAL, 'select', list(nodes), target))


def dns_policy(rules):
    """Use separate resolver endpoints so manual selections also apply to DNS."""
    policies = {}
    for line in rules.splitlines():
        if not line.startswith('  - '):
            continue
        fields = line[4:].split(',')
        if len(fields) < 3 or fields[2] != AI:
            continue
        if fields[0] == 'DOMAIN':
            policies[fields[1]] = AI
        elif fields[0] == 'DOMAIN-SUFFIX':
            policies['+.' + fields[1]] = AI
    # Sensitive sets precede CN when a domain belongs to more than one set.
    policies['geosite:category-ai-!cn'] = AI
    for name in ('facebook', 'instagram', 'whatsapp'):
        policies['geosite:' + name] = AI
    policies['+.cn'] = CN
    policies['geosite:cn'] = CN
    return '  nameserver-policy:\n' + ''.join(
        f'    {quote(domain)}:\n' + ''.join(f'      - https://{ip}/dns-query\n' for ip in DNS[policy])
        for domain, policy in policies.items())


def compose(profile, device, target, nodes, sensitive):
    template = (CORE / 'client.yaml.tmpl').read_text()
    values = {name: '' for name in re.findall(r'\{([A-Z0-9_]+)\}', template)}
    revision = hashlib.sha256(template.encode() + Path(__file__).read_bytes()).hexdigest()[:12]
    values.update(DEVICE=device, PROFILE_OWNER=profile, TARGET_LABEL=target,
                  STRICT_LABEL='false', TEMPLATE_REVISION=revision,
                  SERVER_LABEL='Aggregate; per-server credentials remain in source profiles',
                  DNS_FOLLOW_RULE='  follow-rule: true' if target == 'stash' else '  respect-rules: true',
                  STUN_PROTOCOL_RULE=f'  - PROTOCOL,STUN,{AI}' if target == 'stash' else '')
    # Adapt the shared header/rules once, then insert already-adapted node blocks.
    base = adapt_config(template.format(**values), target, False, [])
    header = base.split('\nproxies:\n', 1)[0]
    providers = base.split('\nrule-providers:\n', 1)[1].split('\nrules:\n', 1)[0]
    rules = base.split('\nrules:\n', 1)[1]
    mapping = {'🤖 AI 隐私出口': AI, '🌐 代理流量': OVERSEAS, '↪️ 直连流量': APPLE,
               '🎯 兜底策略': OVERSEAS}
    for old, new in mapping.items():
        rules = rules.replace(old, new)
    rules = '\n'.join(line for line in rules.splitlines() if line.startswith('  - ')) + '\n'
    rules = rules.replace(f'DOMAIN-KEYWORD,spotify,{APPLE}', 'DOMAIN-KEYWORD,spotify,DIRECT')
    rules = rules.replace(f'DOMAIN-SUFFIX,scdn.co,{APPLE}', 'DOMAIN-SUFFIX,scdn.co,DIRECT')
    rules = rules.replace(f'DOMAIN-SUFFIX,raw.githubusercontent.com,{AI}',
                          f'DOMAIN-SUFFIX,raw.githubusercontent.com,{OVERSEAS}')
    # Resolver routes must remain ahead of CN IP rules. Replace inherited endpoints.
    old_resolvers = ('1.1.1.1', '8.8.8.8', '223.5.5.5', '120.53.53.53')
    rules = '\n'.join(line for line in rules.splitlines()
                      if not any(line.startswith(f'  - IP-CIDR,{ip}/32,') for ip in old_resolvers)) + '\n'
    dns_rules = ''.join(f'  - IP-CIDR,{ip}/32,{policy},no-resolve\n'
                        for policy, addresses in DNS.items() for ip in addresses)
    # Static LAN rules remain first. Resolver IPs are public and cannot overlap LAN.
    anchor = '  - DOMAIN-SUFFIX,raw.githubusercontent.com,'
    index = rules.index(anchor)
    rules = rules[:index] + dns_rules + rules[index:]
    meta_rules = ''.join(f'  - DOMAIN-SUFFIX,{domain},{AI}\n' for domain in META_DOMAINS)
    for name in ('facebook', 'instagram', 'whatsapp'):
        providers += (f'\n  {name}:\n    type: http\n    behavior: domain\n    format: mrs\n'
                      f'    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/{name}.mrs"\n'
                      f'    path: ./ruleset/meta_{name}.mrs\n    interval: 86400\n')
        meta_rules += f'  - RULE-SET,{name},{AI}\n'
    # Meta shares the sensitive group, ahead of ads and domestic routing.
    rules = rules.replace(f'  - RULE-SET,ai,{AI}\n', meta_rules + f'  - RULE-SET,ai,{AI}\n')
    header = header.split('  nameserver:\n', 1)[0]
    # Bootstrap remains independent of sensitive resolver endpoints.
    header = header.replace('    - https://1.1.1.1/dns-query', '    - https://1.12.12.12/dns-query')
    header += '  nameserver:\n' + ''.join(f'    - https://{ip}/dns-query\n' for ip in DNS[OVERSEAS])
    header += dns_policy(rules)
    header = '\n'.join(line for line in header.splitlines() if not line.lstrip().startswith('#') or line.startswith('#'))
    return (header + '\n\nproxies:\n' + '\n'.join(nodes.values()) + '\n'
            + groups(nodes, sensitive, target) + 'rule-providers:\n' + providers
            + '\nrules:\n' + rules)


def generate(root, profile, *, target=None, check=False):
    root = Path(root)
    plan = load_plan(root, profile)
    target = target or plan['client']
    if target not in ('stash', 'mihomo'):
        raise ValueError('客户端目标无效')
    nodes = collect_nodes(root, plan, target)
    directory = root / 'clash-configs'
    rendered = {directory / f'{profile}-{device}.yaml': compose(profile, device, target, available, plan['sensitive'])
                for device, available in nodes.items()}
    current = write_outputs(directory, profile, rendered, check=check)
    if check:
        print('汇总配置与所有当前源一致' if current else '汇总配置缺失或已过期，请重新 render')
        return 0 if current else 1
    print(f'已生成 {len(rendered)} 份 {target} 汇总配置；每设备节点数：'
          + '、'.join(f'{device}={len(available)}' for device, available in nodes.items()))
    print('敏感服务使用显式主备顺序；手动选择集中在一个组。未部署或切换客户端。')
    return 0
