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

print_first_line() {
  local output
  output="$("$@")"
  printf '%s\n' "${output%%$'\n'*}"
}
