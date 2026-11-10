"""Opt-in Mihomo main policy for manual sensitive routing and overseas DNS."""
from aggregate_daily import apple_ai_rules, overseas_dns_rules


def sections(ai, overseas):
    return dict(
        ADDITIONAL_AI_RULES=apple_ai_rules(ai),
        OVERSEAS_DNS_RULES=overseas_dns_rules(overseas),
        FINAL_POLICY=overseas)


def agy_rules(proxy):
    """Only OMB's official ACP/harness Google API requests use the selected node."""
    return '\n'.join(
        f'  - AND,((PROCESS-NAME,{process}),(DOMAIN-SUFFIX,googleapis.com)),{proxy}'
        for process in ('agy_acp_server.par', 'localharness_external'))
