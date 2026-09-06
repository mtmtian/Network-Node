#!/usr/bin/env bash
# Google Cloud adapter for core/deploy.sh.
PROVIDER_TITLE="GCP 代理一键部署"
PROVIDER_DESCRIPTION="provider=GCP"

provider_init() {
  load_conf
  if [ -n "${GCP_HTTP_PROXY:-}" ]; then
    export HTTPS_PROXY="$GCP_HTTP_PROXY" HTTP_PROXY="$GCP_HTTP_PROXY"
  fi
}

provider_preflight() {
  PROFILE_NAME="$PROFILE_NAME" NETWORK_NODE_STATE_DIR="$STATE_DIR" \
    bash "$PROJECT_DIR/providers/gcp-preflight.sh"
}

provider_configure() {
  local default_proj in_proj proj in_region region in_zone zone in_dev devs
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
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
    printf '  设备列表 [mac iphone]: '; read -r in_dev
    devs="${in_dev:-mac iphone}"
    sed -e "s|^PROJECT_ID=.*|PROJECT_ID=${proj}|" \
        -e "s|^REGION=.*|REGION=${region}|" \
        -e "s|^ZONE=.*|ZONE=${zone}|" \
        -e "s|^DEVICES=.*|DEVICES=\"${devs}\"|" \
        "$CONFIG_TEMPLATE" > "$CONF_FILE"
    chmod 600 "$CONF_FILE"
    ok "已创建 GCP profile 配置"
  fi
  load_conf
  GCP_ACCOUNT="${GCP_ACCOUNT:-$(gcloud config get-value account 2>/dev/null || true)}"
  [ -n "$GCP_ACCOUNT" ] && [ "$GCP_ACCOUNT" != '(unset)' ] || die "缺少 GCP_ACCOUNT"
  export GCP_ACCOUNT
  # Pin the account on the first successful setup; later runs ignore global switches.
  python3 - "$CONF_FILE" <<'PY'
import os, pathlib, re, shlex, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text()
line = 'GCP_ACCOUNT=' + shlex.quote(os.environ['GCP_ACCOUNT'])
text = re.sub(r'^GCP_ACCOUNT=.*$', line, text, flags=re.M) if re.search(r'^GCP_ACCOUNT=', text, re.M) else text.rstrip() + '\n' + line + '\n'
path.write_text(text)
path.chmod(0o600)
PY
  PROVIDER_DESCRIPTION="provider=GCP  项目=$PROJECT_ID  区域=$REGION"
}

provider_provision() {
  PROFILE_NAME="$PROFILE_NAME" NETWORK_NODE_STATE_DIR="$STATE_DIR" \
    bash "$PROJECT_DIR/providers/gcp-provision.sh"
}

provider_install() {
  local setup_script="$1" download_script="$2" env_file="$3" attempt remote_dir=""
  : "${GCP_ACCOUNT:?deploy.conf 缺少 GCP_ACCOUNT}"
  local -a gc=(gcloud --account "$GCP_ACCOUNT" --project "$PROJECT_ID" --quiet)
  mkdir -p "$SSH_DIR"
  chmod 700 "$SSH_DIR"
  local ssh_key="$SSH_DIR/google_compute_engine"
  for attempt in 1 2 3; do
    if remote_dir="$("${gc[@]}" compute ssh --ssh-key-file "$ssh_key" --tunnel-through-iap --zone "$ZONE" "$INSTANCE_NAME" \
      --command 'umask 077; mktemp -d /tmp/network-node.XXXXXXXX')"; then
      break
    fi
    warn "SSH 尚未就绪，等待重试 ($attempt/3)..."
    sleep 15
  done
  [[ "$remote_dir" =~ ^/tmp/network-node\.[A-Za-z0-9]+$ ]] || die "无法创建安全的远端临时目录"
  if ! "${gc[@]}" compute scp --ssh-key-file "$ssh_key" --tunnel-through-iap --zone "$ZONE" \
    "$setup_script" "$download_script" "$env_file" "$INSTANCE_NAME:$remote_dir/"; then
    "${gc[@]}" compute ssh --ssh-key-file "$ssh_key" --tunnel-through-iap --zone "$ZONE" "$INSTANCE_NAME" \
      --command "rm -rf '$remote_dir'" || true
    die "上传失败，已尝试清理远端临时文件"
  fi
  "${gc[@]}" compute ssh --ssh-key-file "$ssh_key" --tunnel-through-iap --zone "$ZONE" "$INSTANCE_NAME" \
    --command "trap 'sudo rm -rf $remote_dir' EXIT HUP INT TERM; sudo bash '$remote_dir/setup-server.sh' '$remote_dir/server-env.sh'; exit \$?"

}

provider_print_summary() {
  echo "  Provider  : Google Cloud"
  echo "  服务器 IP : $STATIC_IP"
}
