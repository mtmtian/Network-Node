#!/usr/bin/env python3
"""Render one device configuration from explicitly selected local profiles."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'core'))
from client_aggregate import generate


def main():
    parser = argparse.ArgumentParser(description='汇总本地节点；不部署服务器、不显示凭据')
    parser.add_argument('action', choices=('render', 'check'))
    parser.add_argument('--profile', required=True, help='保存 aggregate.json 的汇总 profile')
    parser.add_argument('--client', choices=('stash', 'mihomo'))
    args = parser.parse_args()
    return generate(ROOT, args.profile, target=args.client, check=args.action == 'check')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        sys.exit(f'ERROR: {exc}')
