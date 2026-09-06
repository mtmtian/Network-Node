#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$PROJECT_DIR/core/common.sh"
load_conf
load_secrets

: "${PROJECT_ID:?deploy.conf 缺少 PROJECT_ID}"
: "${REGION:?}" "${ZONE:?}" "${INSTANCE_NAME:?}" "${IP_NAME:?}"
: "${MACHINE_TYPE:=e2-micro}" "${NETWORK_TIER:=PREMIUM}"
: "${REALITY_PORT:=443}"
: "${HY2_PORT:?HY2_PORT 未生成，请先运行 secrets.sh}"
: "${ANYTLS_PORT:?ANYTLS_PORT 未生成，请先运行 secrets.sh}"
HY2_FIREWALL_PORT="${HY2_PORT_RANGE:-$HY2_PORT}"

: "${GCP_ACCOUNT:?deploy.conf 缺少 GCP_ACCOUNT，请通过 deploy-gcp.sh 初始化}"
GC=(gcloud --account "$GCP_ACCOUNT" --project "$PROJECT_ID" --quiet)

gcloud_retry() {
  local attempt status delay
  delay=3
  for attempt in 1 2 3; do
    if "${GC[@]}" "$@"; then
      return 0
    else
      status=$?
    fi
    if [ "$attempt" -lt 3 ]; then
      warn "gcloud 请求失败，${delay}s 后重试 (${attempt}/3)..."
      sleep "$delay"
      delay=$((delay * 2))
    fi
  done
  return "$status"
}

# Existing VMs must already own the configured reservation. Never silently
# publish an unattached address after a manual address change.
say "[1/4] 启用 Compute Engine API（幂等）"
gcloud_retry services enable compute.googleapis.com
python3 "$PROJECT_DIR/providers/gcp_ip.py" preflight "$STATE_DIR"

say "[2/4] 预留静态外部 IP：${IP_NAME}（${REGION} / ${NETWORK_TIER}）"
IP_EXISTS="$(gcloud_retry compute addresses list --regions "$REGION" --filter "name=$IP_NAME" --format='value(name)')"
if [ -n "$IP_EXISTS" ]; then
  ok "IP 已存在，复用"
else
  gcloud_retry compute addresses create "$IP_NAME" --region "$REGION" --network-tier "$NETWORK_TIER"
fi
STATIC_IP="$(gcloud_retry compute addresses describe "$IP_NAME" --region "$REGION" --format='value(address)')"
ok "已取得预留静态 IP，等待核验 VM 绑定后保存"

say "[3/4] 防火墙规则（幂等）"
FW_RULES="tcp:${REALITY_PORT},udp:${HY2_FIREWALL_PORT},tcp:${ANYTLS_PORT}"
if [ "${WARP_ENABLE:-false}" = "true" ]; then
  : "${WARP_REALITY_PORT:?WARP_ENABLE=true 但缺 WARP_REALITY_PORT}"
  FW_RULES="${FW_RULES},tcp:${WARP_REALITY_PORT}"
fi
if gcloud_retry compute firewall-rules describe allow-proxy >/dev/null 2>&1; then
  gcloud_retry compute firewall-rules update allow-proxy \
    --rules "$FW_RULES"
else
  gcloud_retry compute firewall-rules create allow-proxy \
    --network default --direction INGRESS --action ALLOW \
    --rules "$FW_RULES" \
    --source-ranges 0.0.0.0/0 --target-tags vpn-node
fi

CDN_ONLY_BLOCK_RULE="network-node-cdn-only-block"
if [ "${CDN_ONLY:-false}" = "true" ]; then
  if gcloud_retry compute firewall-rules describe "$CDN_ONLY_BLOCK_RULE" >/dev/null 2>&1; then
    gcloud_retry compute firewall-rules update "$CDN_ONLY_BLOCK_RULE" --no-disabled
  else
    gcloud_retry compute firewall-rules create "$CDN_ONLY_BLOCK_RULE" \
      --network default --direction INGRESS --action DENY \
      --rules "$FW_RULES" --priority 900 \
      --source-ranges 0.0.0.0/0 --target-tags vpn-node
  fi
else
  if gcloud_retry compute firewall-rules describe "$CDN_ONLY_BLOCK_RULE" >/dev/null 2>&1; then
    gcloud_retry compute firewall-rules update "$CDN_ONLY_BLOCK_RULE" --disabled
  fi
fi
if ! gcloud_retry compute firewall-rules describe allow-iap-ssh >/dev/null 2>&1; then
  gcloud_retry compute firewall-rules create allow-iap-ssh \
    --network default --direction INGRESS --action ALLOW \
    --rules tcp:22 --source-ranges 35.235.240.0/20
fi
ok "防火墙就绪（代理端口对公网、SSH 仅 IAP）"

say "[4/4] 创建 VM：${INSTANCE_NAME}（${MACHINE_TYPE} / Debian 12 / ${ZONE}）"
VM_EXISTS="$(gcloud_retry compute instances list --zones "$ZONE" --filter "name=$INSTANCE_NAME" --format='value(name)')"
if [ -n "$VM_EXISTS" ]; then
  ok "VM 已存在，跳过创建"
else
  gcloud_retry compute instances create "$INSTANCE_NAME" \
    --zone "$ZONE" \
    --machine-type "$MACHINE_TYPE" \
    --image-family debian-12 --image-project debian-cloud \
    --boot-disk-size 30GB --boot-disk-type pd-standard \
    --address "$STATIC_IP" \
    --network-tier "$NETWORK_TIER" \
    --tags vpn-node
  ok "VM 已创建，等待 SSH 就绪..."
  sleep 20
fi

python3 "$PROJECT_DIR/providers/gcp_ip.py" persist "$STATE_DIR"
ok "云资源就绪"
