"""Curated AI domains shared by single-profile and aggregate routing."""
import json
from pathlib import Path
import re

DATA = Path(__file__).with_name('sensitive-services.json')


def domain_rules(group):
    services = json.loads(DATA.read_text())
    seen = set()
    lines = []
    for service in services.values():
        if (not isinstance(service, dict)
                or not {'domains', 'suffixes'} <= set(service)
                or set(service) - {'domains', 'suffixes', 'keywords'}):
            raise ValueError('敏感服务需要 domains、suffixes，可选 keywords')
        for field, kind in (('domains', 'DOMAIN'), ('suffixes', 'DOMAIN-SUFFIX'),
                            ('keywords', 'DOMAIN-KEYWORD')):
            values = service.get(field, [])
            if not isinstance(values, list):
                raise ValueError('敏感服务规则字段必须为列表')
            for domain in values:
                if not isinstance(domain, str) or not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', domain):
                    raise ValueError('敏感服务域名格式无效')
                if (kind, domain) in seen:
                    raise ValueError('敏感服务域名重复')
                seen.add((kind, domain))
                lines.append(f'  - {kind},{domain},{group}')
    return '\n'.join(lines)


def app_rules(target, device, group):
    # App bundle prefix matching is Stash-specific; do not export it to Mihomo.
    # iOS ignores process rules, so its configuration relies on domain rules.
    if device != 'mac':
        return ''
    if target == 'stash':
        return '\n'.join(f'  - PROCESS-NAME,/Applications/{app}.app/,{group}'
                         for app in ('Antigravity', 'Antigravity IDE'))
    return f'  - PROCESS-PATH-REGEX,^/Applications/Antigravity( IDE)?[.]app/.*,{group}'
