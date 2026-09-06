#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$PROJECT_DIR/core/common.sh"
load_conf
load_secrets
python3 "$PROJECT_DIR/core/settings.py" validate "$STATE_DIR"

say "生成/复用本地密钥..."

gen_uuid() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr 'A-Z' 'a-z'
  else
    python3 -c 'import uuid; print(uuid.uuid4())'
  fi
}
rand_psk()   { openssl rand -base64 16; }       # 16 字节 -> aes-128 主/用户密钥
rand_short() { openssl rand -hex 8; }            # Reality short-id

ensure_port() {
  local key="$1" min="$2" max="$3" current port
  current="$(varval "$key")"
  if [ -n "$current" ]; then
    setkv "$key" "$current"
    return
  fi

  current="$(secret_get "$key")"
  [ -n "$current" ] && return

  port="$(python3 - "$min" "$max" <<'PY'
import os, secrets, sys
used = {os.environ.get(key, "") for key in ("REALITY_PORT", "ANYTLS_PORT", "HY2_PORT", "WARP_REALITY_PORT", "VPS_SSH_PORT")}
used.add(os.environ.get("WARP_SOCKS_PORT", "40000"))
if os.environ.get("CDN_ENABLE") == "true":
    used.update(("8080", "20241"))
available = [port for port in range(int(sys.argv[1]), int(sys.argv[2]) + 1) if str(port) not in used]
print(secrets.choice(available))
PY
)"
  setkv "$key" "$port"
}

# HY2/AnyTLS 端口：deploy.conf 已指定则沿用，否则随机高位端口（落入 .secrets.env）
ensure_port HY2_PORT 30000 39999
ensure_port ANYTLS_PORT 20000 29999
if [ "${WARP_ENABLE:-false}" = "true" ]; then
  ensure_port WARP_REALITY_PORT 40000 49999
fi

# Reality short-id 与 AnyTLS 共享密码
ensure_secret REALITY_SHORTID "$(rand_short)"
ensure_secret ANYTLS_PASS     "$(rand_psk)"

# The reference AnyTLS server has one password per profile. Revoke it automatically
# when a device disappears, including the first run after upgrading this tool.
previous_devices="$(secret_get ANYTLS_DEVICES)"
if [ -z "$previous_devices" ]; then
  previous_devices="$(sed -n 's/^REALITY_UUID_\([A-Za-z0-9_]*\)=.*/\1/p' "$SECRETS_FILE")"
fi
rotated=false
for old_device in $previous_devices; do
  case " ${DEVICES:-mac iphone} " in
    *" $old_device "*) ;;
    *)
      if [ "$rotated" = "false" ]; then
        setkv ANYTLS_PASS "$(rand_psk)"
        warn "设备列表有移除：已自动轮换此 profile 的 AnyTLS 密码；部署后请在剩余设备导入新 YAML"
        rotated=true
      fi
      removed_tmp="$(mktemp "$STATE_DIR/.revoked.XXXXXX")"
      grep -vE "^(REALITY_UUID|HY2_PASS|CDN_UUID|WARP_REALITY_UUID)_${old_device}=" "$SECRETS_FILE" > "$removed_tmp" || true
      mv "$removed_tmp" "$SECRETS_FILE"
      chmod 600 "$SECRETS_FILE"
      ;;
  esac
done
setkv ANYTLS_DEVICES "${DEVICES:-mac iphone}"

# 每设备独立 Reality UUID 与 Hysteria2 密码（可单独作废）
for d in ${DEVICES:-mac iphone}; do
  ensure_secret "REALITY_UUID_$d" "$(gen_uuid)"
  ensure_secret "HY2_PASS_$d"     "$(rand_psk)"
  if [ "${WARP_ENABLE:-false}" = "true" ]; then
    ensure_secret "WARP_REALITY_UUID_$d" "$(gen_uuid)"
  fi
done

# ── Cloudflare CDN 套娃出口的密钥（仅 CDN_ENABLE=true 时）──
if [ "${CDN_ENABLE:-false}" = "true" ]; then
  if [ -z "$(secret_get CF_API_TOKEN)" ]; then
    die "CDN_ENABLE=true 但缺 CF_API_TOKEN；请先写入 $SECRETS_FILE 后重跑"
  fi
  # WS 路径：deploy.conf 指定则沿用，否则随机（不带前导斜杠，gen-clash 与服务端统一加）
  if [ -n "${CDN_WS_PATH:-}" ]; then
    setkv CDN_WS_PATH "${CDN_WS_PATH#/}"
  else
    ensure_secret CDN_WS_PATH "$(openssl rand -hex 12)"
  fi
  # 每设备独立 CDN UUID，与 Reality UUID 不同 -> 两条链路凭据隔离
  for d in ${DEVICES:-mac iphone}; do
    ensure_secret "CDN_UUID_$d" "$(gen_uuid)"
  done
fi

if [ "${HY2_OBFS_ENABLE:-false}" = "true" ]; then
  ensure_secret HY2_OBFS_PASSWORD "$(rand_psk)"
fi

ok "密钥由工具自动管理；位置：${SECRETS_FILE}（无需记忆，不显示密码）"
