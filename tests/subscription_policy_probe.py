"""Opt-in read-only comparison of verified local output with deployed HTTPS YAML.

Only prints status, counts, hashes and differing top-level section names.
Credentials stay in memory; this never publishes or refreshes a client.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subscription


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--server', action='append', default=[])
    args = parser.parse_args()
    config, base = subscription.settings()
    token = subscription.keychain_token(config['account_id'])
    results = []
    for server in [None, *args.server]:
        name = subscription.output_name(args.profile, server)
        local = subscription.verified_file(args.profile, server)
        status, remote, _ = subscription.fetch_subscription(
            subscription.subscription_url(base, name, token))
        if status != 200:
            raise subscription.PublishError(f'{name}: HTTP {status}')
        left, right = yaml.safe_load(local), yaml.safe_load(remote)
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise subscription.PublishError('订阅不是配置对象；内容已隐藏')
        different = sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))
        results.append(dict(name=name, http_status=status, semantic_equal=not different,
                            byte_equal=local == remote, differing_sections=different,
                            nodes=len(right.get('proxies', [])), rules=len(right.get('rules', [])),
                            cloud_sha256=hashlib.sha256(remote).hexdigest()))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r['semantic_equal'] for r in results) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except subscription.PublishError as exc:
        raise SystemExit(str(exc)) from None
    except (OSError, ValueError, yaml.YAMLError):
        raise SystemExit('配置读取或解析失败；内容已隐藏') from None
