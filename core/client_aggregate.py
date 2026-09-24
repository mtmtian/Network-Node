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

from client_output import atomic_write, write_outputs
from client_policy import adapt_config
from client_snapshot import snapshot_nodes
from sensitive_policy import domain_rules, app_rules
from ordinary_policy import ordinary_rules, ordinary_providers
from profile_lock import profile_lock
from settings import DEVICE, NAME, load_settings, validate

CORE = Path(__file__).resolve().parent
AI = '🤖 AI / Meta 服务'
SENSITIVE = '🛡 敏感服务'
AUTO = '⚡ 自动测速'
MANUAL = '🔧 手动选择'
OVERSEAS = '🌐 普通海外'
CN = '🇨🇳 国内流量'
APPLE = '🍎 Apple 基础服务'
ADS = '🛑 屏蔽流量'
META_DOMAINS = ('facebook.com', 'facebook.net', 'fb.com', 'fb.me', 'fbcdn.net',
                'fbsbx.com', 'instagram.com', 'cdninstagram.com', 'whatsapp.com',
                'whatsapp.net', 'wa.me', 'messenger.com', 'meta.com', 'meta.ai')
BUSINESS_DOMAINS = ('tiktok.com', 'tiktokshop.com', 'tiktokglobalshop.com', 'tiktokglobalshopv.com',
                    'line.biz', 'linemyshop.com', 'lineshoppingseller.com', 'brightline.tv')
DNS = {
    AI: ('1.1.1.1', '1.0.0.1'),
    SENSITIVE: ('9.9.9.9', '149.112.112.112'),
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
    if not isinstance(plan, dict):
        raise ValueError('汇总计划必须是对象')
    standalone = plan.pop('standalone', False)
    if not isinstance(standalone, bool):
        raise ValueError('standalone 必须为布尔值')
    shared = {'sources', 'sensitive', 'credential_identity'}
    legacy = {'sources', 'sensitive', 'devices', 'client'}
    snapshot = {'snapshot', 'sensitive'}
    if not isinstance(plan, dict) or set(plan) not in (shared, legacy, snapshot):
        raise ValueError('aggregate.json 需要 sources、sensitive、credential_identity；也接受旧版 devices/client 格式')
    if set(plan) == snapshot:
        if plan['snapshot'] != 'nodes.json':
            raise ValueError('快照必须引用 profile 内的 nodes.json')
        sensitive = plan['sensitive']
        if (not isinstance(sensitive, list) or not sensitive
                or any(not isinstance(name, str) or not name for name in sensitive)
                or len(set(sensitive)) != len(sensitive)):
            raise ValueError('快照敏感主备列表无效')
        return plan | {'sources': [], 'devices': ['shared'], 'credential_identity': 'shared', 'standalone': standalone}
    if set(plan) == shared:
        identity = plan['credential_identity']
        if not isinstance(identity, str) or not DEVICE.fullmatch(identity):
            raise ValueError('credential_identity 必须是已有的有效凭据身份')
        plan['devices'] = [identity]
    elif plan['client'] not in ('stash', 'mihomo'):
        raise ValueError('client 必须为 stash/mihomo')
    if standalone and 'credential_identity' not in plan:
        raise ValueError('单服务器输出需要共享身份计划')
    plan['standalone'] = standalone
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
    with tempfile.TemporaryDirectory(prefix='network-node-aggregate-') as tmp:
        sources = []
        # generate() holds all source locks across both client renders.
        for source in plan['sources']:
            state = root / 'profiles' / source['profile']
            settings = load_settings(state)
            settings['CLIENT_TARGET'] = target
            validate(settings)
            if settings.get('CLIENT_CONFIG_ENABLE', 'true') == 'false':
                continue
            fingerprint = tuple((state / name).read_bytes() for name in ('deploy.conf', '.secrets.env'))
            prefix = settings.get('CLIENT_FILE_PREFIX', '').strip() or source['profile']
            for device in set(settings.get('DEVICES', 'mac iphone').split()) & nodes.keys():
                directory = Path(tmp) / source['name'] / device
                env = os.environ | {
                    'NETWORK_NODE_ROOT': str(root), 'NETWORK_NODE_STATE_DIR': str(state),
                    'NETWORK_NODE_PROFILE': source['profile'], 'NETWORK_NODE_CLIENTS_DIR': str(directory),
                }
                try:
                    run = subprocess.run([sys.executable, str(CORE / 'gen-clash.py'),
                                          '--client', target, '--identity', device],
                                         env=env, capture_output=True, text=True, timeout=60)
                except subprocess.TimeoutExpired:
                    raise ValueError(f"源 profile {source['profile']} 生成超时；已保留旧汇总文件") from None
                if run.returncode:
                    # Never relay unexpected generator tracebacks containing local state.
                    raise ValueError(f"源 profile {source['profile']} 生成失败；请用 node.py validate 检查")
                text = (directory / target / f'{prefix}.yaml').read_text()
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
    selections = [(AI, [SENSITIVE]),
                  (OVERSEAS, [AUTO, SENSITIVE, MANUAL]), (CN, ['DIRECT', SENSITIVE, MANUAL]),
                  (APPLE, [SENSITIVE, MANUAL]),
                  (ADS, ['REJECT', SENSITIVE, MANUAL, 'DIRECT'])]
    return ('proxy-groups:\n' + ''.join(group(n, 'select', options, target) for n, options in selections)
            + group(SENSITIVE, 'fallback', sensitive, target)
            + group(AUTO, 'url-test', auto, target)
            + group(MANUAL, 'select', list(nodes), target))


def dns_policy(rules):
    """Route resolver endpoints through the same sensitive or domestic policy."""
    policies = {}
    for line in rules.splitlines():
        if not line.startswith('  - '):
            continue
        fields = line[4:].split(',')
        if len(fields) < 3 or fields[2] not in (AI, SENSITIVE):
            continue
        if fields[0] == 'DOMAIN':
            policies[fields[1]] = fields[2]
        elif fields[0] == 'DOMAIN-SUFFIX':
            policies['+.' + fields[1]] = fields[2]
    # Sensitive sets precede CN when a domain belongs to more than one set.
    policies['geosite:category-ai-!cn'] = AI
    for name in ('facebook', 'instagram', 'whatsapp'):
        policies['geosite:' + name] = AI
    policies['geosite:apple-cn'] = CN
    policies['geosite:cn'] = CN
    return '  nameserver-policy:\n' + ''.join(
        f'    {quote(domain)}: ' + quote([f'https://{ip}/dns-query' for ip in DNS[policy]]) + '\n'
        for domain, policy in policies.items())


def compose(profile, device, target, nodes, sensitive):
    template = (CORE / 'client.yaml.tmpl').read_text()
    rule_template = (CORE / 'aggregate-rules.yaml.tmpl').read_text()
    revision_files = ('sensitive_policy.py', 'sensitive-services.json', 'ordinary_policy.py',
                      'ordinary-services.json', 'ordinary-rulesets.json', 'client_policy.py')
    revision = hashlib.sha256(template.encode() + rule_template.encode() + Path(__file__).read_bytes()
                              + b''.join((CORE / f).read_bytes() for f in revision_files)).hexdigest()[:12]
    values = {name: '' for name in re.findall(r'\{([A-Z0-9_]+)\}', template)}
    values.update(DEVICE=device, PROFILE_OWNER=profile, TARGET_LABEL=target,
                  STRICT_LABEL='true', TEMPLATE_REVISION=revision,
                  SERVER_LABEL='Aggregate; per-server credentials remain in source profiles',
                  DNS_FOLLOW_RULE='  follow-rule: true' if target == 'stash' else '  respect-rules: true')
    # Share client transport/header and provider definitions with single-server
    # output; aggregate routing has its own ordered, readable policy template.
    base = adapt_config(template.format(**values), target, False, [])
    header = base.split('\nproxies:\n', 1)[0]
    providers = base.split('\nrule-providers:\n', 1)[1].split('\nrules:\n', 1)[0]
    for name in ('facebook', 'instagram', 'whatsapp'):
        providers += (f'\n  {name}:\n    type: http\n    behavior: domain\n    format: mrs\n'
                      f'    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/{name}.mrs"\n'
                      f'    path: ./ruleset/meta_{name}.mrs\n    interval: 86400\n')
    ordinary_provider_text, ordinary_refs = ordinary_providers(OVERSEAS, target=target, download_proxy=SENSITIVE)
    providers += '\n' + ordinary_provider_text
    labels = dict(AI=AI, SENSITIVE=SENSITIVE, OVERSEAS=OVERSEAS, CN=CN, APPLE=APPLE, ADS=ADS)
    values = labels | dict(
        APP_RULES=app_rules(target, device, AI), SENSITIVE_RULES=domain_rules(AI),
        META_RULES='\n'.join(f'  - DOMAIN-SUFFIX,{d},{AI}' for d in META_DOMAINS),
        BUSINESS_RULES='\n'.join(f'  - DOMAIN-SUFFIX,{d},{SENSITIVE}' for d in BUSINESS_DOMAINS),
        # Preserve the previous exclusion of whole branded TLD namespaces.
        ORDINARY_EXCLUSIONS='\n'.join(f'  - DOMAIN-SUFFIX,{d},{SENSITIVE}'
                                      for d in ('bbc', 'bloomberg', 'hbo', 'playstation', 'xbox')),
        ORDINARY_LOCAL_RULES='', ORDINARY_RULESET_RULES=ordinary_refs.rstrip())
    rules = rule_template.format(**values)
    protected = [(fields[0], fields[1]) for line in rules.splitlines() if line.startswith('  - ')
                 and len(fields := line[4:].split(',')) >= 3
                 and fields[0] in ('DOMAIN', 'DOMAIN-SUFFIX') and fields[2] in (AI, SENSITIVE)]
    values['ORDINARY_LOCAL_RULES'] = ordinary_rules(OVERSEAS, protected).rstrip()
    rules = rule_template.format(**values)
    used = set(re.findall(r'RULE-SET,([^,]+),', rules))
    providers = ''.join(f'  {name}:\n{body}' for name, body in re.findall(
        r'(?ms)^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)', providers) if name in used)
    header = header.split('  nameserver:\n', 1)[0]
    header = header.replace('  - captive.apple.com\n', '')
    # Bootstrap remains independent of sensitive resolver endpoints.
    header = header.replace('    - https://1.1.1.1/dns-query', '    - https://1.12.12.12/dns-query')
    header += '  nameserver:\n' + ''.join(f'    - https://{ip}/dns-query\n' for ip in DNS[SENSITIVE])
    header += dns_policy(rules)
    header = '\n'.join(line for line in header.splitlines() if not line.lstrip().startswith('#') or line.startswith('#'))
    if target == 'mihomo':
        # Route exclusions replace Stash's skip-proxy for private address ranges.
        header = header.replace('  dns-hijack:\n',
            '  route-exclude-address:\n'
            '    - 127.0.0.0/8\n    - 10.0.0.0/8\n    - 172.16.0.0/12\n'
            '    - 192.168.0.0/16\n    - 169.254.0.0/16\n    - 100.64.0.0/10\n'
            '    - ::1/128\n    - fc00::/7\n    - fe80::/10\n'
            '  dns-hijack:\n')
    return (header + '\n\nproxies:\n' + '\n'.join(nodes.values()) + '\n'
            + groups(nodes, sensitive, target) + 'rule-providers:\n' + providers
            + '\nrules:\n' + rules)


def standalone_selections(available, sensitive):
    """Partition the exact main-config nodes; never consult stale deploy profiles."""
    partitions = {}
    for name, block in available.items():
        alias, separator, _ = name.partition('/')
        if not separator or not NAME.fullmatch(alias):
            raise ValueError('单服务器输出需要合法的 server/protocol 节点名称')
        partitions.setdefault(alias, {})[name] = block
    result = {}
    for alias, nodes in partitions.items():
        preferred = [name for name in sensitive if name in nodes]
        if not preferred:
            preferred = [alias + '/' + protocol for protocol in ('Reality', 'CDN')
                         if alias + '/' + protocol in nodes]
        if not preferred:
            raise ValueError('单服务器缺少可用的 Reality/CDN 敏感出口；停止生成')
        result[alias] = (nodes, preferred)
    return result


def generate(root, profile, *, target=None, check=False, publish_to=None):
    root = Path(root)
    if not isinstance(profile, str) or not NAME.fullmatch(profile):
        raise ValueError('汇总 profile 名称无效')
    targets = ('stash', 'mihomo') if target in (None, 'both') else (target,)
    if any(t not in ('stash', 'mihomo') for t in targets):
        raise ValueError('客户端目标无效')
    if publish_to is not None and (not check or targets != ('stash',)):
        raise ValueError('发布必须先校验单个 Stash 目标')
    if (root / 'clash-configs').is_symlink():
        raise ValueError('客户端输出目录不能是符号链接')
    state = root / 'profiles' / profile
    if state.is_symlink() or not (state / 'aggregate.json').is_file():
        raise ValueError('汇总 profile 不存在或不是本地目录；先创建计划或 import')
    with ExitStack() as stack:
        stack.enter_context(profile_lock(state))
        plan = load_plan(root, profile)
        snapshot_path = root / 'profiles' / profile / 'nodes.json'
        if 'snapshot' in plan and snapshot_path.is_symlink():
            raise ValueError('节点快照不能是符号链接')
        snapshot_before = snapshot_path.read_bytes() if 'snapshot' in plan else None
        for source in sorted(plan['sources'], key=lambda s: s['profile']):
            state = root / 'profiles' / source['profile']
            if not (state / 'deploy.conf').is_file():
                raise ValueError('源 profile 不存在')
            stack.enter_context(profile_lock(state))
        bundles = []
        for client in targets:
            nodes = (snapshot_nodes(root, profile, client, plan['sensitive']) if 'snapshot' in plan
                     else collect_nodes(root, plan, client))
            directory = root / 'clash-configs' / client
            rendered = {}
            for device, available in nodes.items():
                shared = 'credential_identity' in plan
                filename = f'{profile}.yaml' if shared else f'{profile}-{device}.yaml'
                text = compose(profile, 'mac' if shared else device, client, available, plan['sensitive'])
                if shared:
                    text = text.replace('# Network-Node config — device: mac', '# Network-Node shared client config', 1)
                rendered[directory / filename] = text
                if plan.get('standalone'):
                    for alias, (selected, preferred) in standalone_selections(available, plan['sensitive']).items():
                        # Snapshot labels alone are not proof of transport/UDP support.
                        if 'snapshot' in plan:
                            snapshot_nodes(root, profile, client, preferred)
                        child_name = f'{profile}-{alias}'
                        if not NAME.fullmatch(child_name):
                            raise ValueError('单服务器文件名超过长度限制')
                        child = compose(profile, 'mac', client, selected, preferred)
                        child = child.replace('# Network-Node config — device: mac', '# Network-Node shared client config', 1)
                        child += f'\n# Standalone server: {alias}; source: {profile}\n'
                        rendered[directory / (child_name + '.yaml')] = child
            bundles.append((directory, rendered))
        if snapshot_before is not None and snapshot_before != snapshot_path.read_bytes():
            raise ValueError('节点快照在生成期间发生变化，已保留原输出')
        # Render every requested target before publishing any output. Separate
        # ownership manifests prevent single-target renders removing the other.
        current = True
        for directory, rendered in bundles:
            current = write_outputs(directory, profile, rendered, check=check) and current
        if publish_to is not None:
            if not current:
                raise ValueError('Stash 配置缺失或过期；先 render，再发布')
            # Publish these verified bytes under the same source locks. Never
            # re-read a potentially changed output after releasing the locks.
            _publish_stash_files(profile, bundles[0][1], Path(publish_to))
    if check:
        print('汇总配置与所有当前源一致' if current else '汇总配置缺失或已过期，请重新 render')
        return 0 if current else 1
    print(f'已生成 {sum(len(files) for _, files in bundles)} 份汇总配置：' + '、'.join(targets))
    print('敏感服务使用显式主备顺序；手动选择集中在一个组。未部署或切换客户端。')
    return 0


def publish_stash(root, profile, destination=None):
    """Explicitly distribute current Stash outputs; never publish node state."""
    destination = Path(destination) if destination is not None else (
        Path.home() / 'Library/Mobile Documents/iCloud~ws~stash~icloud/Documents')
    return generate(root, profile, target='stash', check=True, publish_to=destination)


def _publish_stash_files(profile, rendered, destination):
    if destination.is_symlink():
        raise ValueError('iCloud 分发目录不能是符号链接')
    if not destination.is_dir():
        raise ValueError('Stash iCloud 目录不存在；确认 iCloud 已启用，或指定 --icloud-dir')
    copies = []
    for source, text in rendered.items():
        target = destination / source.name
        if target.is_symlink():
            raise ValueError('分发文件不能是符号链接')
        if target.exists():
            header = target.read_text().splitlines()[:5]
            if f'# Profile: {profile}' not in header or not any(line.startswith('# Client: stash;') for line in header):
                raise ValueError('目标文件归属不明；已保留，请选择独立分发目录')
        copies.append((target, text))
    for target, text in copies:
        atomic_write(target, text)
    print(f'已发布 {len(copies)} 份 Stash 配置到本地 iCloud 目录；远端同步和客户端加载需另行验证。')
    return 0
