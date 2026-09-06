"""Client-specific settings and strict AI routing over one shared template."""
import re


def remove_section(config, start, end):
    first = config.index(start)
    last = config.index(end, first)
    return config[:first] + config[last:]


def adapt_config(config, target, strict, ai_nodes):
    if target == "stash":
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
