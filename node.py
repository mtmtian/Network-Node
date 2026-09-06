#!/usr/bin/env python3
"""Profile maintenance; cloud address writes require an explicit --apply."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))
from settings import NAME, load_settings, validate


def main():
    parser = argparse.ArgumentParser(description="配置管理与入口恢复；不显示凭据，云端写入需 --apply")
    parser.add_argument("action", choices=("status", "validate", "render", "check", "cdn-check",
                                           "ip-check", "ip-sync", "ip-rotate", "ip-rollback", "ip-finalize"))
    parser.add_argument("--profile", required=True)
    parser.add_argument("--client", choices=("stash", "mihomo"))
    parser.add_argument("--apply", action="store_true", help="执行换 IP、回滚或释放保留地址；省略时仅显示计划")
    args = parser.parse_args()
    if not NAME.fullmatch(args.profile):
        parser.error("profile 仅支持 1-64 位字母、数字、下划线和连字符")
    state = ROOT / "profiles" / args.profile
    if not (state / "deploy.conf").is_file():
        parser.error("profile 不存在；请先通过部署入口创建")
    settings = load_settings(state)
    if args.apply and args.action not in ('ip-rotate', 'ip-rollback', 'ip-finalize'):
        parser.error('--apply 仅用于 ip-rotate / ip-rollback / ip-finalize')
    if args.action.startswith('ip-'):
        if args.profile != 'gcloud':
            parser.error('当前 GCP 入口恢复仅支持 gcloud profile')
        if args.client:
            parser.error('IP 操作沿用 profile 的 CLIENT_TARGET，不接受 --client')
        from profile_lock import profile_lock
        sys.path.insert(0, str(ROOT / 'providers'))
        from gcp_ip import Rotation, check, render
        with profile_lock(state):
            if args.action in ('ip-check', 'ip-sync'):
                if args.action == 'ip-sync' and (state / 'ip-rotation.json').exists():
                    parser.error('存在换 IP 记录；先完成回滚或释放保留地址')
                check(state, persist=args.action == 'ip-sync')
                if args.action == 'ip-sync':
                    render(state)
                print('云端地址归属与绑定检查通过' + ('；已同步本地 YAML' if args.action == 'ip-sync' else '；本地 IP 一致'))
            else:
                operation = Rotation(state)
                getattr(operation, {'ip-rotate': 'rotate', 'ip-rollback': 'rollback',
                                    'ip-finalize': 'finalize'}[args.action])(apply=args.apply)
                if args.action == 'ip-rollback' and args.apply:
                    print('原地址绑定和本地 YAML 已恢复；请同步设备，未使用的新地址可用 ip-finalize 释放')
        return
    if args.action == 'cdn-check':
        from cdn_probe import check_cdn
        check_cdn(settings)
        print('CDN TLS / WebSocket / VLESS / HTTPS 请求全部通过；未通过直连节点回退')
        return
    if args.client:
        settings["CLIENT_TARGET"] = args.client
    if args.action == "status":
        print(f"Profile: {args.profile}")
        print("客户端输出: " + ("已停用" if settings.get("CLIENT_CONFIG_ENABLE", "true") == "false" else "已启用"))
        print(f"配置位置: {state / 'deploy.conf'}")
        print(f"密码/凭据位置: {state / '.secrets.env'}（工具自动管理，不需要记忆）")
        print(f"连接设置位置: {state / 'connection.conf'}")
        print(f"客户端文件位置: {ROOT / 'clash-configs'}")
        print("备份完整 profile 及其中的 ssh/；不要只备份 YAML，也不要上传或粘贴凭据。")
        return
    validate(settings, deployment=args.action == "validate")
    if args.action == "validate":
        print("本地配置校验通过；未修改凭据或访问服务器")
        return
    command = [sys.executable, str(ROOT / "core" / "gen-clash.py")]
    if args.action == "check":
        command.append("--check")
    if args.client:
        command += ["--client", args.client]
    env = os.environ | {"NETWORK_NODE_ROOT": str(ROOT), "NETWORK_NODE_STATE_DIR": str(state),
                        "NETWORK_NODE_PROFILE": args.profile}
    if args.action == 'render' and args.profile == 'gcloud':
        from profile_lock import profile_lock
        with profile_lock(state):
            return subprocess.call(command, env=env)
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        sys.exit(f"ERROR: {exc}")
