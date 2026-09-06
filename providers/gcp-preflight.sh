#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$PROJECT_DIR/core/common.sh"

say "预检环境依赖..."

missing=0

need() {  # need CMD HINT
  if command -v "$1" >/dev/null 2>&1; then
    ok "$1 已安装"
  else
    warn "缺少 $1 — $2"
    missing=1
  fi
}

need gcloud   "安装方式见 https://cloud.google.com/sdk/docs/install"
need python3  "macOS: brew install python3 ；Debian/Ubuntu: sudo apt install python3"
need openssl  "通常系统自带；缺失请用包管理器安装"
need ssh-keygen "通常由 OpenSSH 提供"

# uuid 来源：uuidgen 或 python3 均可
if command -v uuidgen >/dev/null 2>&1; then
  ok "uuidgen 已安装"
else
  warn "缺少 uuidgen（将回退到 python3 生成 UUID）"
fi

[ "$missing" -eq 0 ] || die "请先安装上述缺失的依赖，再重新运行 ./deploy-gcp.sh"

# A saved account must take precedence over the workstation's active account.
load_conf
acct="${GCP_ACCOUNT:-$(gcloud config get-value account 2>/dev/null || true)}"
[ -n "$acct" ] && [ "$acct" != '(unset)' ] || die "请先登录 gcloud，并在 deploy.conf 设置 GCP_ACCOUNT"
if ! gcloud --account "$acct" auth print-access-token >/dev/null 2>&1; then
  die "GCP_ACCOUNT 的授权不可用，请重新登录该账号后重试"
fi
ok "指定 GCP 账号的授权有效"

ok "预检通过"
