"""Explicit Mihomo main-subscription policy; standalone and Stash stay strict."""

OVERSEAS_DNS = ('8.8.8.8', '8.8.4.4')


def apple_ai_rules(ai):
    return (''.join(f'  - DOMAIN,{host},{ai}\n' for host in (
        'apple-relay.apple.com', 'apple-relay.cloudflare.com',
        'apple-relay.fastly-edge.com', 'cp4.cloudflare.com'))
        + f'  - DOMAIN-SUFFIX,smoot.apple.com,{ai}\n')


def overseas_dns_rules(overseas):
    return ''.join(f'  - IP-CIDR,{ip}/32,{overseas},no-resolve\n' for ip in OVERSEAS_DNS)


def daily_sections(ai, sensitive, overseas, apple, cn):
    def rules(kind, names, policy):
        return ''.join(f'  - {kind},{name},{policy}\n' for name in names)

    ai_rules = (
        apple_ai_rules(ai)
        + rules('DOMAIN', ('login.live.com', 'login.microsoftonline.com', 'login.microsoft.com',
                          'login.windows.net', 'odc.officeapps.live.com', 'graph.microsoft.com',
                          'substrate.office.com', 'privacy.microsoft.com',
                          'cdn.odc.officeapps.live.com', 'logincdn.msauth.net'), ai)
        + rules('DOMAIN-SUFFIX', ('copilot.microsoft.com', 'copilot.cloud.microsoft', 'copilot.com',
                                 'x.com', 'twitter.com', 'twimg.com', 't.co'), ai)
        + rules('DOMAIN', ('aida.googleapis.com', 'aisandbox-pa.googleapis.com'), ai)
        + rules('DOMAIN-SUFFIX', ('chatgpt.livekit.cloud',), ai))
    relay = (rules('DOMAIN', ('mask-api.fe.apple-dns.net', 'mask-api.icloud.com',
                             'mask-t.apple-dns.net', 'mask.apple-dns.net'), overseas)
             + rules('DOMAIN-SUFFIX', ('mask-h2.icloud.com', 'mask.icloud.com'), overseas))
    return dict(
        CAPTIVE_RULE=rules('DOMAIN', ('captive.apple.com',), 'DIRECT'),
        OVERSEAS_DNS_RULES=overseas_dns_rules(overseas),
        DOWNLOAD_POLICY=overseas, ADDITIONAL_AI_RULES=ai_rules,
        APPLE_TIME_RULE=rules('DOMAIN-SUFFIX', ('time.apple.com',), apple),
        SIRI_RULE=rules('DOMAIN', ('guzzoni.apple.com',), sensitive),
        RELAY_RULES=relay, RELAY_POLICY=overseas,
        APPLE_RULES=rules('DOMAIN-SUFFIX', ('apple.com', 'icloud.com', 'icloud-content.com',
                                         'mzstatic.com', 'apple-dns.net', 'aaplimg.com',
                                         'cdn-apple.com', 'itunes.com'), apple),
        CN_IP_RULES=f'  - RULE-SET,cn-ip,{cn}\n  - GEOIP,CN,{cn}\n',
        FINAL_POLICY=overseas)
