"""Explicit ordinary-service allowlist; unknown destinations remain sensitive."""
import ipaddress
import json
from pathlib import Path
import re

DATA = Path(__file__).with_name('ordinary-services.json')
RULESETS = Path(__file__).with_name('ordinary-rulesets.json')
SHARED_ROOTS = {'google.com', 'googleapis.com', 'gstatic.com', 'googleusercontent.com',
                'ggpht.com', 'cloudfront.net', 'amazonaws.com', 'cloudflare.com',
                'akamaihd.net', 'akamaized.net', 'fastly.net', 'azureedge.net',
                'windows.net', 'blob.core.windows.net', 'storage.googleapis.com',
                'cloudflarestorage.com', 'pages.dev', 'workers.dev', 'r2.dev',
                'vercel.app', 'netlify.app', 'herokuapp.com', 'appspot.com',
                'github.io', 'gitlab.io'}


def domain_overlap(kind, value, protected_kind, protected_value):
    if value == protected_value:
        return True
    return ((kind == 'DOMAIN-SUFFIX' and protected_value.endswith('.' + value))
            or (protected_kind == 'DOMAIN-SUFFIX' and value.endswith('.' + protected_value)))


def ordinary_rules(group, protected):
    """Compile a reviewed catalog, rejecting broad clouds and sensitive overlap."""
    services = json.loads(DATA.read_text())
    if not isinstance(services, dict) or not services:
        raise ValueError('普通海外服务清单必须为非空对象')
    lines, seen = [], set()
    for service in services.values():
        if not isinstance(service, dict) or set(service) != {'domains', 'suffixes', 'ip_cidrs'}:
            raise ValueError('普通海外服务需要 domains、suffixes、ip_cidrs')
        for field, kind in (('domains', 'DOMAIN'), ('suffixes', 'DOMAIN-SUFFIX'), ('ip_cidrs', 'IP-CIDR')):
            if not isinstance(service[field], list):
                raise ValueError('普通海外清单字段必须为列表')
            for value in service[field]:
                if not isinstance(value, str):
                    raise ValueError('普通海外规则必须为字符串')
                if kind == 'IP-CIDR':
                    try:
                        network = ipaddress.ip_network(value)
                    except ValueError:
                        raise ValueError('普通海外 CIDR 无效') from None
                    if not network.is_global or network.prefixlen < (20 if network.version == 4 else 32):
                        raise ValueError('普通海外 CIDR 必须为明确的服务公网网段')
                    rule_kind = 'IP-CIDR6' if network.version == 6 else kind
                    line = f'  - {rule_kind},{value},{group},no-resolve'
                else:
                    if not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', value) or '.' not in value:
                        raise ValueError('普通海外域名格式无效')
                    if value in SHARED_ROOTS:
                        raise ValueError('不能把共享云或 CDN 整体加入普通海外清单')
                    if any(domain_overlap(kind, value, k, v) for k, v in protected):
                        raise ValueError('普通海外清单与敏感域名重叠，已停止生成')
                    line = f'  - {kind},{value},{group}'
                if (kind, value) in seen:
                    raise ValueError('普通海外规则重复')
                seen.add((kind, value))
                lines.append(line)
    return '\n'.join(lines) + '\n'


def ordinary_providers(group, *, target, download_proxy):
    """Reference reviewed, immutable upstream sets; rendering stays offline."""
    manifest = json.loads(RULESETS.read_text())
    if (not isinstance(manifest, dict) or set(manifest) != {'revision', 'categories'}
            or not isinstance(manifest['revision'], str)
            or not re.fullmatch(r'[a-f0-9]{40}', manifest['revision'])
            or not isinstance(manifest['categories'], dict) or not manifest['categories']):
        raise ValueError('普通规则集需要固定提交和分类清单')
    providers, rules, seen = [], [], set()
    for category, services in manifest['categories'].items():
        if (not isinstance(category, str) or not re.fullmatch('[a-z]+', category)
                or not isinstance(services, list) or not services):
            raise ValueError('普通规则集分类无效')
        rules.append(f'  # 普通海外 / {category}')
        for service in services:
            if (not isinstance(service, str) or not re.fullmatch('[a-z][a-z0-9-]*', service)
                    or service in seen or service.startswith(('category-', 'geolocation-'))
                    or service in {'cn', 'proxy', 'google', 'microsoft', 'facebook', 'instagram',
                                   'whatsapp', 'tiktok', 'openai', 'anthropic', 'github', 'gitlab'}):
                raise ValueError('普通规则集必须是唯一且经过审阅的服务子清单')
            seen.add(service)
            name = 'ordinary-' + service
            url = (f'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/'
                   f'{manifest["revision"]}/geo/geosite/{service}.mrs')
            providers.append(f'  {name}:\n'
                             '    type: http\n    behavior: domain\n    format: mrs\n'
                             f'    url: {url}\n    interval: 86400\n'
                             + (f'    proxy: {download_proxy}\n' if target == 'mihomo' else ''))
            rules.append(f'  - RULE-SET,{name},{group}')
    return '\n'.join(providers), '\n'.join(rules) + '\n'
