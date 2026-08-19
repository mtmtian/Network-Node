#!/usr/bin/env bash
# Entry point: configure an already-provisioned Debian/Ubuntu VPS.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
用法：
  ./deploy-vps.sh --profile <name> --host <ip-or-host> [options]
  VPS_PROFILE=<name> VPS_SSH_KEY=<path> ./deploy-vps.sh <ip-or-host>

选项：
  --profile NAME              新服务器使用独立 profile（必填）
  --host HOST                 已安装 Debian/Ubuntu 且可 SSH 的主机
  --ssh-key PATH              本机 SSH 私钥路径
  --ssh-port PORT             SSH 端口，默认 22
  --bootstrap-user USER       首次 root 登录用户，默认 root
  --admin-user USER           部署后的 sudo 用户，默认 mt
  --install-key               若新机只有 root 密码，先交互式安装本机公钥
  --copy-config-from PROFILE  首次创建时复制旧 profile 的非密钥 deploy.conf
  --check-only                只做本机与远端 readiness 检查，不创建 profile 或改服务器
  -h, --help                  显示帮助

示例：
  ./deploy-vps.sh --profile cstone-next --host 203.0.113.10 \
    --ssh-key "$HOME/.ssh/cstone_ed25519" \
    --copy-config-from cstonecloud-cuii-a
USAGE
}

need_value() {
  [ "$#" -ge 2 ] && [ -n "$2" ] || {
    printf '选项 %s 缺少参数\n' "$1" >&2
    exit 2
  }
}

VPS_PROFILE="${VPS_PROFILE:-}"
VPS_HOST="${VPS_HOST:-}"
VPS_CHECK_ONLY=false
VPS_INSTALL_KEY="${VPS_INSTALL_KEY:-false}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)
      need_value "$@"; VPS_PROFILE="$2"; shift 2 ;;
    --host)
      need_value "$@"; VPS_HOST="$2"; shift 2 ;;
    --ssh-key)
      need_value "$@"; VPS_SSH_KEY="$2"; shift 2 ;;
    --ssh-port)
      need_value "$@"; VPS_SSH_PORT="$2"; shift 2 ;;
    --bootstrap-user)
      need_value "$@"; VPS_BOOTSTRAP_USER="$2"; shift 2 ;;
    --admin-user)
      need_value "$@"; VPS_ADMIN_USER="$2"; shift 2 ;;
    --install-key)
      VPS_INSTALL_KEY=true; shift ;;
    --copy-config-from)
      need_value "$@"; VPS_CONFIG_FROM_PROFILE="$2"; shift 2 ;;
    --check-only)
      VPS_CHECK_ONLY=true; shift ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift
      [ "$#" -le 1 ] || { printf '只允许一个主机参数\n' >&2; exit 2; }
      [ "$#" -eq 0 ] || VPS_HOST="${VPS_HOST:-$1}"
      break ;;
    -*)
      printf '未知选项：%s\n' "$1" >&2
      usage >&2
      exit 2 ;;
    *)
      [ "$#" -eq 1 ] || { printf '只允许一个主机参数\n' >&2; exit 2; }
      VPS_HOST="${VPS_HOST:-$1}"
      shift ;;
  esac
done

if [ -z "$VPS_PROFILE" ]; then
  printf '请显式设置 VPS_PROFILE / --profile，例如：./deploy-vps.sh --profile cstone-next --host <VPS_PUBLIC_IP>\n' >&2
  exit 2
fi
case "$VPS_PROFILE" in
  *[!A-Za-z0-9_-]*)
    printf 'VPS_PROFILE 只能包含字母、数字、下划线和连字符：%s\n' "$VPS_PROFILE" >&2
    exit 2
    ;;
esac
case "${VPS_CONFIG_FROM_PROFILE:-}" in
  "") ;;
  *[!A-Za-z0-9_-]*)
    printf '来源 profile 只能包含字母、数字、下划线和连字符：%s\n' "$VPS_CONFIG_FROM_PROFILE" >&2
    exit 2
    ;;
esac
[ "$VPS_CHECK_ONLY" != "true" ] || [ "$VPS_INSTALL_KEY" != "true" ] || {
  printf '%s\n' '--check-only 与 --install-key 不能同时使用；readiness 模式不会修改远端' >&2
  exit 2
}
PROFILE_NAME="$VPS_PROFILE"
. "$PROJECT_DIR/core/common.sh"
. "$PROJECT_DIR/providers/vps.sh"
. "$PROJECT_DIR/core/deploy.sh"

if [ "$VPS_CHECK_ONLY" = "true" ]; then
  provider_init
  provider_preflight
  provider_readiness
  ok "readiness 检查通过；未创建 profile，也未修改远端服务器"
  exit 0
fi

run_deploy
