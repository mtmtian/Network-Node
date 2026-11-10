"""Opt-in Mihomo main policy for manual sensitive routing and overseas DNS."""
from aggregate_daily import OVERSEAS_DNS


def sections(ai, overseas):
    apple_ai = ''.join(f'  - DOMAIN,{host},{ai}\n' for host in (
        'apple-relay.apple.com', 'apple-relay.cloudflare.com',
        'apple-relay.fastly-edge.com', 'cp4.cloudflare.com'))
    return dict(
        DAILY_AI_RULES=apple_ai + f'  - DOMAIN-SUFFIX,smoot.apple.com,{ai}\n',
        OVERSEAS_DNS_RULES=''.join(f'  - IP-CIDR,{ip}/32,{overseas},no-resolve\n'
                                   for ip in OVERSEAS_DNS),
        FINAL_POLICY=overseas)


def agy_rules(proxy):
    """Only OMB's official ACP/harness Google API requests use the selected node."""
    return '\n'.join(
        f'  - AND,((PROCESS-NAME,{process}),(DOMAIN-SUFFIX,googleapis.com)),{proxy}'
        for process in ('agy_acp_server.par', 'localharness_external'))
