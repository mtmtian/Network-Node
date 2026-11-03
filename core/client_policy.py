"""Client-specific settings and strict AI routing over one shared template."""
import re


LIGHTPANDA_PRIVATE_CIDRS = (
    '0.0.0.0/8', '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12',
    '192.168.0.0/16', '169.254.0.0/16', '100.64.0.0/10',
    '::1/128', 'fc00::/7', 'fe80::/10',
)


def protect_lightpanda(config, target):
    """Prepend the Mihomo guard after all routing/strict-mode transformations.

    The process condition comes first, so other processes do not trigger DNS
    resolution here. IP conditions deliberately omit no-resolve: fake-IP hides
    private destinations from lightpanda-safe. Stash is returned unchanged.
    """
    if target != 'mihomo':
        return config
    rules = ''.join(
        f'  - AND,((PROCESS-NAME,lightpanda),({"IP-CIDR6" if ":" in cidr else "IP-CIDR"},{cidr})),REJECT\n'
        for cidr in LIGHTPANDA_PRIVATE_CIDRS)
    header, existing_rules = config.split('\nrules:\n', 1)
    return header + '\nrules:\n' + rules + existing_rules


def remove_section(config, start, end):
    first = config.index(start)
    last = config.index(end, first)
    return config[:first] + config[last:]


def adapt_config(config, target, strict, ai_nodes):
    if target == "stash":
        # Stash accepts only IP literals for the bootstrap default-nameserver.
        config = re.sub(r'(^  default-nameserver:\n)(.*?)(?=^  \S)',
                        lambda m: m[1] + re.sub(r'https://([0-9.]+)/dns-query', r'\1', m[2]),
                        config, flags=re.S | re.M)
        # Stash manages its own TUN and protocol sniffing.
        config = remove_section(config, "geodata-mode: true\n", "skip-proxy:\n")
        config = remove_section(config, "tun:\n", "dns:\n")
        # Stash's probe URL/timeout belong to each proxy, not the group.
        before, proxies = config.split('\nproxies:\n', 1)
        proxies, after = proxies.split('\nproxy-groups:\n', 1)
        proxies = re.sub(r'(?m)^(    type: .+)$', r'\1\n    benchmark-url: http://www.gstatic.com/generate_204\n    benchmark-timeout: 5', proxies)
        config = before + '\nproxies:\n' + proxies + '\nproxy-groups:\n' + after
    else:
        config = remove_section(config, "skip-proxy:\n", "tun:\n")
    if not strict:
        return config

    config = config.replace("  - captive.apple.com\n", "")
    config = remove_section(config, "  # 国内流量使用国内加密 DNS", "\nproxies:\n")
    first = config.index("proxy-groups:\n")
    last = config.index("rule-providers:\n", first)
    nodes = "\n".join(f'      - "{name}"' for name in ai_nodes)
    config = config[:first] + f'''proxy-groups:
  - name: "🤖 AI 隐私出口"
    type: fallback
    lazy: false
    url: https://www.gstatic.com/generate_204
    interval: 60
    proxies:
{nodes}
  - name: "🛑 屏蔽流量"
    type: select
    proxies:
      - REJECT
      - "🤖 AI 隐私出口"

''' + config[last:]

    prefix, rules = config.split("\nrules:\n", 1)
    strict_rules = []
    for line in rules.splitlines():
        if not line.startswith("  - "):
            continue
        fields = line[4:].split(",")
        kind = fields[0]
        if kind == "RULE-SET" and fields[1] not in ("ai", "ads-lite"):
            continue
        if kind in ("GEOSITE", "GEOIP", "IP-ASN") or fields[:2] == ["DOMAIN-SUFFIX", "cn"]:
            continue
        target_index = 1 if kind == "MATCH" else 2
        if fields[target_index] not in ("DIRECT", "🛑 屏蔽流量"):
            fields[target_index] = "🤖 AI 隐私出口"
        strict_rules.append("  - " + ",".join(fields))
    rules = "\n".join(strict_rules) + "\n"

    # Only AI/ad sets are needed; strict routing has no implicit GeoSite/ASN DB.
    before, providers = prefix.split("rule-providers:\n", 1)
    used = set(re.findall(r"RULE-SET,([^,]+),", rules))
    blocks = re.findall(r"(?m)^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)", providers, re.S)
    retained = []
    for name, body in blocks:
        if name in used:
            body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
            retained.append(f"  {name}:\n{body.rstrip()}\n")
    return before + "rule-providers:\n" + "\n".join(retained) + "\nrules:\n" + rules
