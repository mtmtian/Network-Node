"""Opt-in Mihomo main policy for manual sensitive routing and overseas DNS."""
from aggregate_daily import apple_ai_rules, overseas_dns_rules


def sections(ai, overseas):
    return dict(
        ADDITIONAL_AI_RULES=apple_ai_rules(ai),
        OVERSEAS_DNS_RULES=overseas_dns_rules(overseas),
        FINAL_POLICY=overseas)


def google_ai_rules(proxy):
    """Pin agy/Antigravity Google APIs and Gemini's web generation to one exit."""
    process_rules = [
        f'  - AND,((PROCESS-NAME,{process}),(DOMAIN-SUFFIX,googleapis.com)),{proxy}'
        for process in ('agy_acp_server.par', 'localharness_external', 'agy')]
    return '\n'.join(process_rules + [
        '  - AND,((PROCESS-PATH,/Applications/Antigravity.app/Contents/Resources/bin/language_server),'
        f'(DOMAIN-SUFFIX,googleapis.com)),{proxy}',
        f'  - DOMAIN-SUFFIX,gemini.google.com,{proxy}',
        f'  - DOMAIN,geminiweb-pa.clients6.google.com,{proxy}',
    ])
