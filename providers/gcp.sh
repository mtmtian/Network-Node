#!/usr/bin/env bash
# Google Cloud adapter for core/deploy.sh.
PROVIDER_TITLE="GCP 代理一键部署"
PROVIDER_DESCRIPTION="provider=GCP"

provider_init() { :; }

provider_preflight() {
  bash "$PROJECT_DIR/providers/gcp-preflight.sh"
}

provider_configure() {
  local default_proj in_proj proj in_region region in_zone zone in_dev devs
  if [ ! -f "$CONF_FILE" ]; then
    say "首次运行，开始交互式配置"
    default_proj="$(gcloud config get-value project 2>/dev/null || true)"
    printf '  GCP 项目 ID [%s]: ' "${default_proj:-请输入}"
    read -r in_proj
    proj="${in_proj:-$default_proj}"
    [ -n "$proj" ] || die "必须提供项目 ID"
    printf '  区域 REGION [us-west1]: '; read -r in_region
    region="${in_region:-us-west1}"
    printf '  可用区 ZONE [%s-a]: ' "$region"; read -r in_zone
    zone="${in_zone:-${region}-a}"
    printf '  设备列表 [mac iphone ipad laptop spare]: '; read -r in_dev
    devs="${in_dev:-mac iphone ipad laptop spare}"
    sed -e "s|^PROJECT_ID=.*|PROJECT_ID=${proj}|" \
        -e "s|^REGION=.*|REGION=${region}|" \
        -e "s|^ZONE=.*|ZONE=${zone}|" \
        -e "s|^DEVICES=.*|DEVICES=\"${devs}\"|" \
        "$CONFIG_TEMPLATE" > "$CONF_FILE"
    ok "已写入 deploy.conf"
  fi
  load_conf
  PROVIDER_DESCRIPTION="provider=GCP  项目=$PROJECT_ID  区域=$REGION"
}

provider_provision() {
  bash "$PROJECT_DIR/providers/gcp-provision.sh"
}

provider_install() {
  local setup_script="$1" env_file="$2" attempt scp_ok=0
  local -a gc=(gcloud --project "$PROJECT_ID" --quiet)
  for attempt in 1 2 3; do
    if "${gc[@]}" compute scp --tunnel-through-iap --zone "$ZONE" \
      "$setup_script" "$env_file" "$INSTANCE_NAME":/tmp/ 2>/dev/null; then
      scp_ok=1; break
    fi
    warn "SSH 尚未就绪，等待重试 ($attempt/3)..."
    sleep 15
  done
  [ "$scp_ok" -eq 1 ] || die "无法通过 IAP SSH 连接到 VM"
  "${gc[@]}" compute ssh --tunnel-through-iap --zone "$ZONE" "$INSTANCE_NAME" \
    --command 'bash /tmp/setup-server.sh /tmp/server-env.sh; rc=$?; rm -f /tmp/server-env.sh /tmp/setup-server.sh; exit $rc'
}

provider_print_summary() {
  echo "  Provider  : Google Cloud"
  echo "  服务器 IP : $STATIC_IP"
}
