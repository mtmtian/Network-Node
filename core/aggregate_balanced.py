"""Opt-in Mihomo main policy for manual sensitive routing and overseas DNS."""
from aggregate_daily import apple_ai_rules, overseas_dns_rules


def sections(ai, overseas):
    return dict(
        ADDITIONAL_AI_RULES=apple_ai_rules(ai),
        OVERSEAS_DNS_RULES=overseas_dns_rules(overseas),
        FINAL_POLICY=overseas)


STUDIO_BACKENDS = ('alkalimakersuite-pa.clients6.google.com', 'waa-pa.clients6.google.com',
                   'people-pa.clients6.google.com')


def google_ai_rules(proxy, *, cli_proxy=None):
    """Pin Google AI Studio, Gemini, and Antigravity requests to their configured exits."""
    process_rules = [
        f'  - AND,((PROCESS-NAME,{process}),(DOMAIN-SUFFIX,googleapis.com)),{cli_proxy or proxy}'
        for process in ('agy_acp_server.par', 'localharness_external', 'agy')]
    return '\n'.join(process_rules + [
        '  - AND,((PROCESS-PATH,/Applications/Antigravity.app/Contents/Resources/bin/language_server),'
        f'(DOMAIN-SUFFIX,googleapis.com)),{proxy}',
        f'  - DOMAIN-SUFFIX,aistudio.google.com,{proxy}',
        f'  - DOMAIN-SUFFIX,ai.google.dev,{proxy}',
        f'  - DOMAIN-SUFFIX,generativelanguage.googleapis.com,{proxy}',
        f'  - DOMAIN,accounts.google.com,{proxy}',
        f'  - DOMAIN,oauth2.googleapis.com,{proxy}',
        f'  - DOMAIN-SUFFIX,gemini.google.com,{proxy}',
        f'  - DOMAIN,geminiweb-pa.clients6.google.com,{proxy}',
    ] + ([f'  - DOMAIN,{host},{proxy}' for host in STUDIO_BACKENDS] if cli_proxy else []))
