#!/usr/bin/env python3
"""Render one device configuration from explicitly selected local profiles."""
import argparse
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'core'))
from client_aggregate import generate, publish_stash
from client_snapshot import import_snapshot


def main():
    parser = argparse.ArgumentParser(description='汇总本地节点；不部署服务器、不显示凭据')
    parser.add_argument('action', choices=('render', 'check', 'publish', 'import'))
    parser.add_argument('--profile', required=True, help='保存 aggregate.json 的汇总 profile')
    parser.add_argument('--client', choices=('stash', 'mihomo', 'both'),
                        help='默认同时输出两种客户端，互不覆盖')
    parser.add_argument('--icloud-dir', help='Stash 发布目录；默认使用 Stash iCloud Documents')
    parser.add_argument('--source', help='首次迁移的本地完整客户端 YAML；不上传')
    args = parser.parse_args()
    if args.action == 'import':
        if not args.source or args.client or args.icloud_dir:
            parser.error('import 需要 --source，且不接受 --client/--icloud-dir')
        return import_snapshot(ROOT, args.profile, args.source)
    if args.source:
        parser.error('--source 仅用于 import')
    if args.action == 'publish':
        if args.client == 'mihomo':
            if args.icloud_dir:
                parser.error('Mihomo 发布到私有 HTTPS，不接受 --icloud-dir')
            return subprocess.call([sys.executable, str(ROOT / 'subscription.py'),
                                    'publish', '--profile', args.profile])
        if args.client == 'both':
            parser.error('请明确分别发布 stash 或 mihomo，以便核对不同分发渠道')
        return publish_stash(ROOT, args.profile, args.icloud_dir)
    if args.icloud_dir:
        parser.error('--icloud-dir 仅用于 publish')
    return generate(ROOT, args.profile, target=args.client, check=args.action == 'check')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        sys.exit(f'ERROR: {exc}')
