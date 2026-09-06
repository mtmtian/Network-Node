#!/usr/bin/env bash
# Resilient downloads for the remote installer. Retries transient HTTP and network failures.

curl_retry() {
  curl -fsSL \
    --retry 4 \
    --retry-delay 1 \
    --retry-all-errors \
    --connect-timeout 15 \
    --max-time 180 \
    "$@"
}

download_file() {
  local destination="$1" url="$2"
  curl_retry -o "$destination" "$url"
}

fetch_url() {
  curl_retry "$1"
}

# SHA256 digests verified against official release asset metadata on 2026-09-05.
# Updating a component version requires updating its reviewed digest here as well.
release_sha256() {
  case "$1" in
    https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-64.zip) echo 23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae ;;
    https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-arm64-v8a.zip) echo 4d30283ae614e3057f730f67cd088a42be6fdf91f8639d82cb69e48cde80413c ;;
    https://github.com/apernet/hysteria/releases/download/app/v2.10.0/hysteria-linux-amd64) echo 04f7804159ef1d798de12a817d73aab4b9040ebe45fc62e223000c5c59e987fe ;;
    https://github.com/apernet/hysteria/releases/download/app/v2.10.0/hysteria-linux-arm64) echo 8995b33085f7b07769955e23c1c53468064ebf6c408b1d7b663044556898426a ;;
    https://github.com/anytls/anytls-go/releases/download/v0.0.13/anytls_0.0.13_linux_amd64.zip) echo 7e80fc099ea54a71110d256dd60648c47c63c70a3c499eb1f6d7aaa4edb7016f ;;
    https://github.com/anytls/anytls-go/releases/download/v0.0.13/anytls_0.0.13_linux_arm64.zip) echo 88cb762c3c8eb56b46a2d8d6feab9c0858655192143fc164874229499246a956 ;;
    https://github.com/cloudflare/cloudflared/releases/download/2026.7.2/cloudflared-linux-amd64) echo ec905ea7b7e327ff8abdde8cb64697a2152de74dbcdbf6aec9db8364eb3886cd ;;
    https://github.com/cloudflare/cloudflared/releases/download/2026.7.2/cloudflared-linux-arm64) echo 405df476437e027fc6d18729a5a77155c0a33a6082aeee60a799a688f3052e66 ;;
    *) echo "组件版本没有已验证的 SHA256；请先更新 core/download.sh" >&2; return 1 ;;
  esac
}

verify_sha256() {
  local actual
  actual="$(sha256sum < "$1")" || return
  [ "${actual%% *}" = "$2" ]
}

download_release() {
  local destination="$1" url="$2" expected cache_file
  expected="$(release_sha256 "$url")" || return
  if [ -n "${NETWORK_NODE_DOWNLOAD_CACHE:-}" ]; then
    mkdir -p "$NETWORK_NODE_DOWNLOAD_CACHE"
    cache_file="$NETWORK_NODE_DOWNLOAD_CACHE/$expected"
    if [ -f "$cache_file" ] && verify_sha256 "$cache_file" "$expected"; then
      cp "$cache_file" "$destination"
      return
    fi
  fi
  download_file "$destination" "$url" || return
  if ! verify_sha256 "$destination" "$expected"; then
    rm -f "$destination"
    echo "组件 SHA256 校验失败，已停止安装" >&2
    return 1
  fi
  if [ -n "${cache_file:-}" ]; then
    cp "$destination" "$cache_file.new"
    mv "$cache_file.new" "$cache_file"
  fi
}

install_binary() {
  local source="$1" destination="$2"
  if [ -f "$destination" ] && cmp -s "$source" "$destination"; then
    return
  fi
  [ ! -f "$destination" ] || cp -p "$destination" "$destination.previous"
  install -m 0755 "$source" "$destination.new"
  mv "$destination.new" "$destination"
}

print_first_line() {
  local output
  output="$("$@")"
  printf '%s\n' "${output%%$'\n'*}"
}
