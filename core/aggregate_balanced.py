"""Opt-in Mihomo main policy for manual sensitive routing and overseas DNS."""
from aggregate_daily import apple_ai_rules, overseas_dns_rules
from sensitive_policy import domain_rules


def sections(ai, overseas):
    return dict(
        ADDITIONAL_AI_RULES=apple_ai_rules(ai),
        OVERSEAS_DNS_RULES=overseas_dns_rules(overseas),
        FINAL_POLICY=overseas)


STUDIO_BACKENDS = ('alkalimakersuite-pa.clients6.google.com', 'waa-pa.clients6.google.com',
                   'people-pa.clients6.google.com')


def google_web_rules(proxy, *, studio_backends=False):
    rules = [
        f'  - DOMAIN-SUFFIX,aistudio.google.com,{proxy}',
        f'  - DOMAIN-SUFFIX,ai.google.dev,{proxy}',
        f'  - DOMAIN-SUFFIX,generativelanguage.googleapis.com,{proxy}',
        f'  - DOMAIN,accounts.google.com,{proxy}',
        f'  - DOMAIN,oauth2.googleapis.com,{proxy}',
        f'  - DOMAIN-SUFFIX,gemini.google.com,{proxy}',
        f'  - DOMAIN,geminiweb-pa.clients6.google.com,{proxy}',
    ]
    if studio_backends:
        rules.extend(f'  - DOMAIN,{host},{proxy}' for host in STUDIO_BACKENDS)
    return '\n'.join(rules)


def additional_google_web_rules(proxy):
    return '\n'.join((domain_rules(proxy, service_name='google_ai_web'),
                      f'  - DOMAIN-SUFFIX,notebooklm.google.com,{proxy}',
                      f'  - DOMAIN,notebooklm-pa.googleapis.com,{proxy}',
                      f'  - DOMAIN,aisandbox-pa.googleapis.com,{proxy}'))


def google_ai_rules(proxy, *, cli_proxy=None):
    """Pair Mihomo's process routing with the common Google AI web rules."""
    process_rules = [
        f'  - AND,((PROCESS-NAME,{process}),(DOMAIN-SUFFIX,googleapis.com)),{cli_proxy or proxy}'
        for process in ('agy_acp_server.par', 'localharness_external', 'agy')]
    process_rules.append(
        '  - AND,((PROCESS-PATH,/Applications/Antigravity.app/Contents/Resources/bin/language_server),'
        f'(DOMAIN-SUFFIX,googleapis.com)),{proxy}')
    return '\n'.join(process_rules + [google_web_rules(proxy, studio_backends=cli_proxy is not None)])
